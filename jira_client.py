"""Jira REST API 읽기 전용 클라이언트: 인증 확인, Epic·하위 Task 조회, 페이지네이션, 재시도."""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable
from urllib.parse import quote

import requests

from models import ISSUE_KEY_RE, Epic, Viewer
from settings import Settings

log = logging.getLogger(__name__)

PAGE_SIZE = 100
MAX_PAGES = 500
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 30.0

EPIC_FIELDS = ("summary", "assignee", "status", "updated")
TASK_FIELDS = ("summary", "issuetype", "status", "assignee", "priority", "duedate", "updated")

_STATUS_KINDS = {400: "bad_request", 401: "auth", 403: "forbidden", 404: "not_found", 429: "rate_limited"}
_KIND_MESSAGES = {
    "bad_request": "Jira가 요청을 거부했습니다(400). 유형 ID·프로젝트 키·필드 설정을 확인하세요.",
    "auth": "Jira 인증에 실패했습니다(401).",
    "forbidden": "조회 권한이 없거나 API 접근 정책으로 차단되었습니다(403).",
    "not_found": "Jira에서 대상을 찾을 수 없습니다(404).",
    "rate_limited": "Jira 요청 한도를 초과했습니다(429).",
    "server": "Jira 서버 오류가 발생했습니다(5xx).",
}


class JiraError(Exception):
    """Jira 호출 실패. partial_items에는 실패 전까지 수집한 항목이 담긴다."""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.partial_items: list[dict[str, Any]] = []


def _error_for_status(status: int) -> JiraError:
    kind = _STATUS_KINDS.get(status) or ("server" if status >= 500 else "http")
    message = _KIND_MESSAGES.get(kind, f"Jira 요청이 실패했습니다(HTTP {status}).")
    return JiraError(kind, message, status)


def _retry_after_seconds(response: requests.Response) -> float | None:
    try:
        seconds = float(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def build_epic_jql(settings: Settings) -> str:
    clauses = [f"issuetype = {settings.epic_type_id}", "assignee = currentUser()"]
    if settings.project_keys:
        keys = ", ".join(f'"{k}"' for k in settings.project_keys)
        clauses.append(f"project in ({keys})")
    # 수집 중 수정으로 순서가 바뀌어 누락되지 않도록 키 기준으로 페이지를 넘긴다.
    return " AND ".join(clauses) + " ORDER BY key ASC"


def build_epic_link_jql(settings: Settings, epic_key: str) -> str:
    field_number = settings.epic_link_field_id.removeprefix("customfield_")
    type_ids = ", ".join(settings.task_type_ids)
    return f'cf[{field_number}] = "{epic_key}" AND issuetype in ({type_ids}) ORDER BY key ASC'


class JiraClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._settings = settings
        self._base_url = settings.base_url.rstrip("/")
        self._session = session or requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {settings.pat}", "Accept": "application/json"}
        )
        self._verify: str | bool = settings.ca_bundle or True
        self._clock = clock
        self._sleep = sleep
        self._deadline: float | None = None
        self.request_count = 0

    def close(self) -> None:
        self._session.close()

    def begin_collection(self) -> None:
        """전체 수집 예산을 시작한다. 이후 모든 요청·재시도 대기는 남은 예산 안에서만 수행한다."""
        self._deadline = self._clock() + self._settings.collection_timeout

    def _remaining(self) -> float:
        return math.inf if self._deadline is None else self._deadline - self._clock()

    def _request(self, method: str, path: str, *, params=None, json=None) -> dict[str, Any]:
        url = self._base_url + path
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = self._remaining()
            if remaining <= 0:
                raise JiraError("timeout", "전체 수집 제한 시간을 초과했습니다.")
            timeout = (
                min(self._settings.connect_timeout, remaining),
                min(self._settings.read_timeout, remaining),
            )
            self.request_count += 1
            try:
                response = self._session.request(
                    method, url, params=params, json=json, timeout=timeout, verify=self._verify
                )
            except requests.exceptions.SSLError:
                raise JiraError(
                    "tls", "TLS 인증서 검증에 실패했습니다. 사내 CA가 필요하면 JIRA_CA_BUNDLE을 설정하세요."
                ) from None
            except (requests.ConnectionError, requests.Timeout):
                error = JiraError("network", "Jira 서버에 연결하지 못했습니다. 사내망/VPN·프록시를 확인하세요.")
                wait = 0.5 * attempt
            else:
                if response.status_code < 400:
                    try:
                        data = response.json()
                    except ValueError:
                        data = None
                    if not isinstance(data, dict):
                        raise JiraError(
                            "invalid_response",
                            "Jira 응답이 JSON이 아닙니다. SSO 로그인 페이지로 이동했을 수 있으며 PAT 인증이 적용되지 않았을 수 있습니다.",
                            response.status_code,
                        )
                    return data
                error = _error_for_status(response.status_code)
                if response.status_code not in RETRYABLE_STATUS:
                    raise error
                retry_after = _retry_after_seconds(response) if response.status_code == 429 else None
                wait = retry_after if retry_after is not None else 0.5 * attempt
                if wait > MAX_RETRY_AFTER_SECONDS:
                    raise error
            if attempt == MAX_ATTEMPTS or wait >= self._remaining():
                raise error
            log.warning("Jira 요청 재시도 %d/%d (%s): %.1fs 후", attempt, MAX_ATTEMPTS, error.kind, wait)
            self._sleep(wait)
        raise AssertionError("unreachable")

    def _paginate(self, fetch_page: Callable[[int], dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        start_at = 0
        for _ in range(MAX_PAGES):
            try:
                data = fetch_page(start_at)
            except JiraError as err:
                err.partial_items = items
                raise
            page = data.get("issues")
            if not isinstance(page, list):
                err = JiraError("invalid_response", "Jira 응답에 일감 목록이 없습니다.")
                err.partial_items = items
                raise err
            total = data.get("total")
            has_total = isinstance(total, int) and not isinstance(total, bool)
            items.extend(page)
            # 서버가 요청보다 적게 반환할 수 있으므로 실제 반환 건수만큼 이동한다.
            start_at += len(page)
            if has_total and start_at >= total:
                return items
            if not page:
                if has_total:
                    err = JiraError("incomplete", f"전체 {total}건 중 {start_at}건까지만 반환되었습니다.")
                    err.partial_items = items
                    raise err
                return items
        err = JiraError("incomplete", "페이지 수 제한을 초과해 수집을 중단했습니다.")
        err.partial_items = items
        raise err

    def get_myself(self) -> Viewer:
        data = self._request("GET", "/rest/api/2/myself")
        # Server/DC는 key, Cloud는 accountId가 고유 식별자다.
        user_id = data.get("key") or data.get("accountId") or data.get("name")
        if not user_id:
            raise JiraError("invalid_response", "/myself 응답에서 사용자 식별자를 찾을 수 없습니다.")
        return Viewer(jira_user_id=str(user_id), display_name=str(data.get("displayName") or user_id))

    def search_epics(self) -> list[Epic]:
        jql = build_epic_jql(self._settings)
        raws = self._paginate(lambda start_at: self._request(
            "POST",
            "/rest/api/2/search",
            json={"jql": jql, "startAt": start_at, "maxResults": PAGE_SIZE, "fields": list(EPIC_FIELDS)},
        ))
        epics: list[Epic] = []
        seen: set[str] = set()
        for raw in raws:
            key = str(raw.get("key") or "")
            epic_id = str(raw.get("id") or key)
            if not ISSUE_KEY_RE.match(key) or epic_id in seen:
                continue
            seen.add(epic_id)
            fields = raw.get("fields") or {}
            epics.append(Epic(
                id=epic_id,
                key=key,
                summary=str(fields.get("summary") or ""),
                status_name=(fields.get("status") or {}).get("name"),
            ))
        return epics

    def get_epic_issues(self, epic_key: str) -> list[dict[str, Any]]:
        """Epic에 직접 연결된 하위 일감 원본 목록. 유형 선정은 호출 측에서 수행한다."""
        if not ISSUE_KEY_RE.match(epic_key):
            raise JiraError("bad_request", f"올바르지 않은 Epic 키입니다: {epic_key}")
        if self._settings.epic_link_field_id:
            jql = build_epic_link_jql(self._settings, epic_key)
            return self._paginate(lambda start_at: self._request(
                "POST",
                "/rest/api/2/search",
                json={"jql": jql, "startAt": start_at, "maxResults": PAGE_SIZE, "fields": list(TASK_FIELDS)},
            ))
        path = f"/rest/agile/1.0/epic/{quote(epic_key, safe='')}/issue"
        return self._paginate(lambda start_at: self._request(
            "GET",
            path,
            params={"startAt": start_at, "maxResults": PAGE_SIZE, "fields": ",".join(TASK_FIELDS)},
        ))
