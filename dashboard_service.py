"""조회 조합, Task 유형 선정, 정규화, 집계·필터."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from jira_client import JiraClient, JiraError
from models import (
    CATEGORY_LABELS,
    DONE,
    IN_PROGRESS,
    ISSUE_KEY_RE,
    TODO,
    UNKNOWN,
    Assignee,
    DashboardResult,
    Epic,
    Issue,
    LoadWarning,
    Summary,
)
from settings import Settings

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
STATUS_ALL = "ALL"
UNASSIGNED_ID = "__unassigned__"
UNASSIGNED_LABEL = "미지정"
EMPTY_MARK = "—"

STATUS_CATEGORY_MAP = {"indeterminate": IN_PROGRESS, "done": DONE, "new": TODO}
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

_FATAL_MESSAGES = {
    "auth": "Jira 인증에 실패했습니다(401). JIRA_PAT가 만료·폐기되지 않았는지 확인하고 인증 설정을 재설정한 뒤 앱을 재시작하세요.",
    "forbidden": "Jira 조회 권한이 없거나 API 접근 정책으로 차단되었습니다(403). PAT 사용 허용 여부와 권한을 확인하세요.",
    "not_found": "Jira API 경로를 찾을 수 없습니다(404). JIRA_BASE_URL에 context path가 포함되었는지 확인하세요.",
}
_EPIC_MESSAGES = {
    "not_found": "Epic을 찾을 수 없습니다(404). 삭제되었거나 접근이 제한되었을 수 있습니다.",
    "forbidden": "이 Epic의 하위 일감을 조회할 권한이 없습니다(403).",
}


class DashboardLoadError(Exception):
    """결과를 제공할 수 없는 전체 조회 실패."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class AssigneeGroup:
    assignee_id: str
    label: str
    total: int
    in_progress: int
    done: int
    todo: int
    unknown: int
    rows: pd.DataFrame


# ---------------------------------------------------------------- 정규화

def classify_status(status_category_key: Any) -> str:
    return STATUS_CATEGORY_MAP.get(status_category_key, UNKNOWN) if isinstance(status_category_key, str) else UNKNOWN


def parse_jira_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def to_iso_utc(value: Any) -> str | None:
    parsed = parse_jira_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def format_kst(iso_value: str | None) -> str:
    parsed = parse_jira_datetime(iso_value) if isinstance(iso_value, str) else None
    return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M") if parsed else EMPTY_MARK


def build_issue_url(base_url: str, key: str) -> str | None:
    if not ISSUE_KEY_RE.match(key):
        return None
    return f"{base_url.rstrip('/')}/browse/{key}"


def is_included_task(raw: dict[str, Any], task_type_ids: tuple[str, ...]) -> bool:
    issue_type = (raw.get("fields") or {}).get("issuetype") or {}
    return str(issue_type.get("id")) in task_type_ids and not issue_type.get("subtask", False)


def normalize_issue(raw: dict[str, Any], epic_key: str, base_url: str) -> Issue | None:
    key = str(raw.get("key") or "")
    issue_id = str(raw.get("id") or key)
    if not issue_id:
        return None
    fields = raw.get("fields") or {}
    status = fields.get("status") or {}
    category_key = (status.get("statusCategory") or {}).get("key")

    assignee = None
    raw_assignee = fields.get("assignee")
    if isinstance(raw_assignee, dict):
        assignee_id = raw_assignee.get("key") or raw_assignee.get("accountId") or raw_assignee.get("name")
        if assignee_id:
            assignee = Assignee(str(assignee_id), str(raw_assignee.get("displayName") or assignee_id))

    due = fields.get("duedate")
    return Issue(
        id=issue_id,
        key=key,
        summary=str(fields.get("summary") or ""),
        epic_key=epic_key,
        assignee=assignee,
        status_name=str(status.get("name") or EMPTY_MARK),
        status_category_key=category_key if isinstance(category_key, str) else None,
        category=classify_status(category_key),
        priority=(fields.get("priority") or {}).get("name"),
        due_date=due if isinstance(due, str) and _DATE_RE.match(due) else None,
        updated_at=to_iso_utc(fields.get("updated")),
        url=build_issue_url(base_url, key),
    )


def compute_summary(issues: list[Issue] | tuple[Issue, ...], epic_count: int) -> Summary:
    counts = {IN_PROGRESS: 0, DONE: 0, TODO: 0, UNKNOWN: 0}
    for issue in issues:
        counts[issue.category] += 1
    return Summary(
        epic_count=epic_count,
        task_count=len(issues),
        in_progress_count=counts[IN_PROGRESS],
        done_count=counts[DONE],
        todo_count=counts[TODO],
        unknown_count=counts[UNKNOWN],
    )


# ---------------------------------------------------------------- 조회 조합

def _fatal(stage: str, err: JiraError) -> DashboardLoadError:
    message = _FATAL_MESSAGES.get(err.kind, err.message)
    return DashboardLoadError(err.kind, f"{stage}: {message}")


def _epic_warning(epic: Epic, err: JiraError) -> LoadWarning:
    detail = _EPIC_MESSAGES.get(err.kind, err.message)
    if err.partial_items:
        tail = f" 수집된 {len(err.partial_items)}건만 반영했으며 실제 건수는 더 많을 수 있습니다."
    else:
        tail = " 이 Epic의 Task는 집계에 포함되지 않았습니다(0건으로 확정하지 않음)."
    return LoadWarning(kind=err.kind, message=f"{epic.key}: {detail}{tail}", epic_key=epic.key)


def load_dashboard(settings: Settings, client: JiraClient | None = None) -> DashboardResult:
    """Jira에서 전체 결과 묶음을 수집한다. 결과를 줄 수 없으면 DashboardLoadError를 던진다."""
    own_client = client is None
    client = client or JiraClient(settings)
    started = time.monotonic()
    try:
        client.begin_collection()
        try:
            viewer = client.get_myself()
        except JiraError as err:
            raise _fatal("계정 확인(/myself) 실패", err) from None
        try:
            epics = client.search_epics()
        except JiraError as err:
            raise _fatal("담당 Epic 조회 실패", err) from None

        epic_ids = {e.id for e in epics}
        issues: dict[str, Issue] = {}
        warnings: list[LoadWarning] = []
        failed: list[JiraError] = []

        for index, epic in enumerate(epics):
            try:
                raws = client.get_epic_issues(epic.key)
            except JiraError as err:
                if err.kind == "auth":
                    raise _fatal("하위 Task 조회 실패", err) from None
                raws = err.partial_items
                failed.append(err)
                warnings.append(_epic_warning(epic, err))
                if err.kind == "timeout":
                    skipped = [e.key for e in epics[index + 1:]]
                    if skipped:
                        warnings.append(LoadWarning(
                            kind="timeout",
                            message="전체 수집 제한 시간을 초과해 조회하지 못한 Epic: " + ", ".join(skipped),
                        ))
                        failed.extend(JiraError("timeout", "") for _ in skipped)
                    _collect(raws, epic, settings, epic_ids, issues)
                    break
            _collect(raws, epic, settings, epic_ids, issues)

        if epics and len(failed) == len(epics) and not issues:
            if all(err.kind == "not_found" for err in failed) and not settings.epic_link_field_id:
                raise DashboardLoadError(
                    "not_found",
                    "모든 Epic의 하위 조회가 404로 실패했습니다. Agile Epic API를 지원하지 않는 환경일 수 있으니 "
                    "JIRA_EPIC_LINK_FIELD_ID(Epic Link 필드 ID) 설정을 확인하세요.",
                )
            raise DashboardLoadError("all_failed", "모든 Epic의 하위 Task 조회에 실패했습니다. " + failed[0].message)

        ordered = sorted(issues.values(), key=lambda i: i.key)
        result = DashboardResult(
            viewer=viewer,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            is_partial=bool(failed),
            epics=tuple(epics),
            issues=tuple(ordered),
            summary=compute_summary(ordered, len(epics)),
            warnings=tuple(warnings),
        )
        log.info(
            "조회 완료: epics=%d tasks=%d failed_epics=%d requests=%d elapsed=%.2fs",
            len(epics), len(ordered), len(failed), getattr(client, "request_count", 0), time.monotonic() - started,
        )
        return result
    except DashboardLoadError as err:
        log.error("조회 실패(%s) elapsed=%.2fs", err.kind, time.monotonic() - started)
        raise
    finally:
        if own_client:
            client.close()


def _collect(
    raws: list[dict[str, Any]],
    epic: Epic,
    settings: Settings,
    epic_ids: set[str],
    issues: dict[str, Issue],
) -> None:
    for raw in raws:
        if not is_included_task(raw, settings.task_type_ids):
            continue
        issue = normalize_issue(raw, epic.key, settings.base_url)
        if issue is None or issue.id in epic_ids or issue.id in issues:
            continue
        issues[issue.id] = issue


# ---------------------------------------------------------------- 집계·필터 (pandas)

FRAME_COLUMNS = [
    "id", "key", "summary", "epic_key", "assignee_id", "assignee_name",
    "status_name", "category", "priority", "due_date", "updated_at", "url",
]


def issues_frame(issues: tuple[Issue, ...] | list[Issue]) -> pd.DataFrame:
    rows = [
        {
            "id": i.id,
            "key": i.key,
            "summary": i.summary,
            "epic_key": i.epic_key,
            "assignee_id": i.assignee.id if i.assignee else UNASSIGNED_ID,
            "assignee_name": i.assignee.display_name if i.assignee else UNASSIGNED_LABEL,
            "status_name": i.status_name,
            "category": i.category,
            "priority": i.priority,
            "due_date": i.due_date,
            "updated_at": i.updated_at,
            "url": i.url,
        }
        for i in issues
    ]
    df = pd.DataFrame(rows, columns=FRAME_COLUMNS)
    df["updated_ts"] = pd.to_datetime(df["updated_at"], utc=True, errors="coerce")
    key_parts = df["key"].astype(str).str.extract(r"^(.*)-([0-9]+)$")
    df["key_project"] = key_parts[0].fillna(df["key"].astype(str))
    df["key_number"] = pd.to_numeric(key_parts[1], errors="coerce").fillna(0)
    return df


def scope_frame(df: pd.DataFrame, epic_key: str | None = None, assignee_id: str | None = None) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if epic_key:
        mask &= df["epic_key"] == epic_key
    if assignee_id:
        mask &= df["assignee_id"] == assignee_id
    return df[mask]


def _category_counts(df: pd.DataFrame) -> dict[str, int]:
    counts = df["category"].value_counts()
    return {c: int(counts.get(c, 0)) for c in (IN_PROGRESS, DONE, TODO, UNKNOWN)}


def summarize(df: pd.DataFrame, epic_count: int) -> Summary:
    counts = _category_counts(df)
    return Summary(
        epic_count=epic_count,
        task_count=len(df),
        in_progress_count=counts[IN_PROGRESS],
        done_count=counts[DONE],
        todo_count=counts[TODO],
        unknown_count=counts[UNKNOWN],
    )


def filter_status(df: pd.DataFrame, status: str) -> pd.DataFrame:
    return df if status == STATUS_ALL else df[df["category"] == status]


def sort_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        ["updated_ts", "key_project", "key_number"],
        ascending=[False, True, True],
        na_position="last",
    )


def assignee_labels(df: pd.DataFrame) -> dict[str, str]:
    """담당자 ID → 표시 라벨. 표시명이 겹치면 식별자를 덧붙여 구분한다. 미지정은 마지막."""
    names = df.drop_duplicates("assignee_id").set_index("assignee_id")["assignee_name"].to_dict()
    name_counts = pd.Series(list(names.values()), dtype=object).value_counts()
    labels = {
        aid: (f"{name} ({aid})" if name_counts.get(name, 0) > 1 and aid != UNASSIGNED_ID else name)
        for aid, name in names.items()
    }
    return dict(sorted(labels.items(), key=lambda kv: (kv[0] == UNASSIGNED_ID, kv[1], kv[0])))


def assignee_groups(scoped: pd.DataFrame, status: str, labels: dict[str, str]) -> list[AssigneeGroup]:
    groups: list[AssigneeGroup] = []
    for assignee_id, part in scoped.groupby("assignee_id", sort=False):
        counts = _category_counts(part)
        rows = sort_rows(filter_status(part, status))
        if status == IN_PROGRESS and rows.empty:
            continue
        groups.append(AssigneeGroup(
            assignee_id=str(assignee_id),
            label=labels.get(assignee_id, str(part["assignee_name"].iloc[0])),
            total=len(part),
            in_progress=counts[IN_PROGRESS],
            done=counts[DONE],
            todo=counts[TODO],
            unknown=counts[UNKNOWN],
            rows=rows,
        ))
    groups.sort(key=lambda g: (g.assignee_id == UNASSIGNED_ID, -g.in_progress, g.label, g.assignee_id))
    return groups


def _text_or_mark(value: Any) -> str:
    return EMPTY_MARK if value is None or pd.isna(value) or value == "" else str(value)


def display_table(rows: pd.DataFrame, epic_titles: dict[str, str]) -> pd.DataFrame:
    records = [
        {
            "일감": r.url,
            "제목": r.summary,
            "Epic": f"{r.epic_key} {epic_titles.get(r.epic_key, '')}".strip(),
            "상태": f"{CATEGORY_LABELS[r.category]} · {r.status_name}",
            "우선순위": _text_or_mark(r.priority),
            "기한": _text_or_mark(r.due_date),
            "최근 변경": format_kst(r.updated_at),
        }
        for r in rows.itertuples(index=False)
    ]
    return pd.DataFrame(records, columns=["일감", "제목", "Epic", "상태", "우선순위", "기한", "최근 변경"])
