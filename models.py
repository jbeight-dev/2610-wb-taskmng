"""대시보드 내부 데이터 모델."""
from __future__ import annotations

import re
from dataclasses import dataclass

IN_PROGRESS = "IN_PROGRESS"
DONE = "DONE"
TODO = "TODO"
UNKNOWN = "UNKNOWN"

CATEGORY_LABELS = {
    IN_PROGRESS: "진행 중",
    DONE: "완료",
    TODO: "대기",
    UNKNOWN: "분류 확인 필요",
}

# Jira 일감 키 형식. 링크 생성과 JQL 구성 전에 검증한다.
ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-[0-9]+$")


@dataclass(frozen=True)
class Viewer:
    jira_user_id: str
    display_name: str


@dataclass(frozen=True)
class Assignee:
    id: str
    display_name: str


@dataclass(frozen=True)
class Epic:
    id: str
    key: str
    summary: str
    status_name: str | None = None


@dataclass(frozen=True)
class Issue:
    id: str
    key: str
    summary: str
    epic_key: str
    assignee: Assignee | None
    status_name: str
    status_category_key: str | None
    category: str
    priority: str | None
    due_date: str | None
    updated_at: str | None
    url: str | None


@dataclass(frozen=True)
class Summary:
    epic_count: int
    task_count: int
    in_progress_count: int
    done_count: int
    todo_count: int
    unknown_count: int


@dataclass(frozen=True)
class LoadWarning:
    kind: str
    message: str
    epic_key: str | None = None


@dataclass(frozen=True)
class DashboardResult:
    viewer: Viewer
    fetched_at: str
    is_partial: bool
    epics: tuple[Epic, ...]
    issues: tuple[Issue, ...]
    summary: Summary
    warnings: tuple[LoadWarning, ...]
