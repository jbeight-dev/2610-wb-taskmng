"""로컬 설정 로드 및 검증. 같은 키는 환경변수가 우선이고, 없으면 Streamlit secrets를 사용한다."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

PLACEHOLDER_MARKERS = ("REPLACE_WITH", "YOUR_PAT", "CHANGE_ME")
EXAMPLE_HOSTS = frozenset({"jira.company.com"})
TYPE_ID_RE = re.compile(r"^[0-9]+$")
PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FIELD_ID_RE = re.compile(r"^customfield_[0-9]+$")


class SettingsError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class Settings:
    base_url: str
    pat: str = field(repr=False)
    epic_type_id: str
    task_type_ids: tuple[str, ...]
    project_keys: tuple[str, ...] = ()
    ca_bundle: str | None = None
    # 설정 시 Agile Epic API 대신 Epic Link 필드 검색으로 하위 Task를 조회한다.
    epic_link_field_id: str | None = None
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    collection_timeout: float = 60.0

    def fingerprint(self) -> str:
        """인증·조회 범위 설정 변경 감지용 해시. 토큰 원문은 노출하지 않는다."""
        parts = [
            self.base_url,
            self.pat,
            self.epic_type_id,
            ",".join(self.task_type_ids),
            ",".join(self.project_keys),
            self.ca_bundle or "",
            self.epic_link_field_id or "",
        ]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _split(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in value.split(",") if p.strip())


def load_settings(
    env: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
) -> Settings:
    env = os.environ if env is None else env
    secrets = secrets or {}
    problems: list[str] = []

    def raw(name: str) -> str:
        value = env.get(name)
        if value is None or not str(value).strip():
            value = secrets.get(name)
        return "" if value is None else str(value).strip()

    def is_placeholder(value: str) -> bool:
        upper = value.upper()
        return any(marker in upper for marker in PLACEHOLDER_MARKERS)

    def required(name: str) -> str:
        value = raw(name)
        if not value:
            problems.append(f"{name}: 값이 설정되지 않았습니다.")
            return ""
        if is_placeholder(value):
            problems.append(f"{name}: 예시 값이 그대로 입력되어 있습니다. 실제 값으로 바꾸세요.")
            return ""
        return value

    def optional_float(name: str, default: float) -> float:
        value = raw(name)
        if not value:
            return default
        try:
            number = float(value)
        except ValueError:
            problems.append(f"{name}: 숫자(초)여야 합니다.")
            return default
        if number <= 0:
            problems.append(f"{name}: 0보다 커야 합니다.")
            return default
        return number

    base_url = required("JIRA_BASE_URL").rstrip("/")
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            problems.append("JIRA_BASE_URL: http(s)로 시작하는 전체 주소여야 합니다.")
        elif parsed.hostname in EXAMPLE_HOSTS:
            problems.append("JIRA_BASE_URL: 문서의 예시 주소입니다. 실제 사내 Jira 주소로 바꾸세요.")
        elif parsed.query or parsed.fragment:
            problems.append("JIRA_BASE_URL: 쿼리나 # 없이 기준 주소(context path 포함)만 입력하세요.")

    pat = required("JIRA_PAT")
    if pat and any(ch.isspace() for ch in pat):
        problems.append("JIRA_PAT: 공백이 포함되어 있습니다.")

    epic_type_id = required("JIRA_EPIC_TYPE_ID")
    if epic_type_id and not TYPE_ID_RE.match(epic_type_id):
        problems.append("JIRA_EPIC_TYPE_ID: 이슈 유형의 숫자 ID여야 합니다(표시명 아님).")

    task_type_ids = _split(required("JIRA_TASK_TYPE_IDS"))
    if any(not TYPE_ID_RE.match(t) for t in task_type_ids):
        problems.append("JIRA_TASK_TYPE_IDS: 쉼표로 구분된 숫자 ID여야 합니다.")
    if epic_type_id and epic_type_id in task_type_ids:
        problems.append("JIRA_TASK_TYPE_IDS: Epic 유형 ID를 포함할 수 없습니다.")

    project_keys = _split(raw("JIRA_PROJECT_KEYS"))
    if any(not PROJECT_KEY_RE.match(k) for k in project_keys):
        problems.append("JIRA_PROJECT_KEYS: 대문자 프로젝트 키를 쉼표로 구분해 입력하세요.")

    ca_bundle = raw("JIRA_CA_BUNDLE") or None
    if ca_bundle and not Path(ca_bundle).is_file():
        problems.append("JIRA_CA_BUNDLE: 인증서 파일을 찾을 수 없습니다.")

    epic_link_field_id = raw("JIRA_EPIC_LINK_FIELD_ID") or None
    if epic_link_field_id and not FIELD_ID_RE.match(epic_link_field_id):
        problems.append("JIRA_EPIC_LINK_FIELD_ID: customfield_12345 형식이어야 합니다.")

    connect_timeout = optional_float("JIRA_CONNECT_TIMEOUT_SECONDS", 5.0)
    read_timeout = optional_float("JIRA_READ_TIMEOUT_SECONDS", 10.0)
    collection_timeout = optional_float("JIRA_COLLECTION_TIMEOUT_SECONDS", 60.0)

    if problems:
        raise SettingsError(problems)

    return Settings(
        base_url=base_url,
        pat=pat,
        epic_type_id=epic_type_id,
        task_type_ids=task_type_ids,
        project_keys=project_keys,
        ca_bundle=ca_bundle,
        epic_link_field_id=epic_link_field_id,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        collection_timeout=collection_timeout,
    )
