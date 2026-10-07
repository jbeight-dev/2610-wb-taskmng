import pytest

import dashboard_service as svc
from jira_client import JiraError
from models import DONE, IN_PROGRESS, TODO, UNKNOWN, Epic, Viewer
from settings import Settings

SETTINGS = Settings(
    base_url="https://jira.example.test",
    pat="test-token",
    epic_type_id="10000",
    task_type_ids=("10002",),
)
STORY, BUG, SUBTASK = "10001", "10004", "10003"


def raw(
    num,
    *,
    type_id="10002",
    subtask=False,
    cat="indeterminate",
    status="개발 중",
    assignee=("u-a", "담당자 A"),
    updated="2026-10-07T09:00:00.000+0900",
    priority="High",
    due=None,
):
    fields = {
        "summary": f"일감 {num}",
        "issuetype": {"id": type_id, "subtask": subtask},
        "status": {"name": status, "statusCategory": {"key": cat}} if cat is not None else {"name": status},
        "assignee": {"key": assignee[0], "displayName": assignee[1]} if assignee else None,
        "priority": {"name": priority} if priority else None,
        "duedate": due,
        "updated": updated,
    }
    return {"id": str(num), "key": f"DP-{num}", "fields": fields}


class FakeClient:
    def __init__(self, epics, children, viewer=Viewer("me", "나")):
        self.viewer = viewer
        self.epics = epics
        self.children = children
        self.calls = []
        self.request_count = 0

    def begin_collection(self):
        pass

    def get_myself(self):
        if isinstance(self.viewer, Exception):
            raise self.viewer
        return self.viewer

    def search_epics(self):
        return self.epics

    def get_epic_issues(self, key):
        self.calls.append(key)
        value = self.children[key]
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        pass


def epic(num, summary="Epic"):
    return Epic(id=str(num), key=f"DP-{num}", summary=f"{summary} {num}")


def error(kind, partial=()):
    err = JiraError(kind, f"{kind} error")
    err.partial_items = list(partial)
    return err


def test_ac04_status_categories_counted():
    children = {"DP-100": [
        raw(1), raw(2, status="리뷰 중"), raw(3, status="QA"),
        raw(4, cat="done", status="완료"), raw(5, cat="done", status="취소"),
        raw(6, cat="new", status="할 일"),
    ]}
    result = svc.load_dashboard(SETTINGS, FakeClient([epic(100)], children))
    s = result.summary
    assert (s.task_count, s.in_progress_count, s.done_count, s.todo_count, s.unknown_count) == (6, 3, 2, 1, 0)
    # AC-05: 서로 다른 상태명이 같은 카테고리로 분류되고 원본 상태명을 유지
    names = {i.status_name for i in result.issues if i.category == IN_PROGRESS}
    assert names == {"개발 중", "리뷰 중", "QA"}


def test_ac10_ac11_only_configured_task_types_and_no_subtasks():
    children = {"DP-100": [
        raw(1), raw(2, type_id=STORY), raw(3, type_id=BUG), raw(4, type_id=SUBTASK, subtask=True),
        raw(5, type_id="10002", subtask=True),
    ]}
    result = svc.load_dashboard(SETTINGS, FakeClient([epic(100)], children))
    assert [i.key for i in result.issues] == ["DP-1"]


def test_epic_itself_and_duplicates_counted_once():
    children = {
        "DP-100": [raw(1), raw(1), raw(100)],
        "DP-200": [raw(1), raw(2)],
    }
    result = svc.load_dashboard(SETTINGS, FakeClient([epic(100), epic(200)], children))
    assert sorted(i.key for i in result.issues) == ["DP-1", "DP-2"]
    assert result.summary.task_count == 2


def test_ac12_partial_failure_marks_partial_and_keeps_successes():
    children = {
        "DP-100": [raw(1)],
        "DP-200": error("not_found"),
        "DP-300": error("server", partial=[raw(3)]),
    }
    result = svc.load_dashboard(SETTINGS, FakeClient([epic(100), epic(200), epic(300)], children))
    assert result.is_partial
    assert sorted(i.key for i in result.issues) == ["DP-1", "DP-3"]
    assert {w.epic_key for w in result.warnings} == {"DP-200", "DP-300"}
    assert all("test-token" not in w.message for w in result.warnings)


def test_timeout_skips_remaining_epics_with_warning():
    client = FakeClient([epic(100), epic(200), epic(300)], {"DP-100": [raw(1)], "DP-200": error("timeout")})
    result = svc.load_dashboard(SETTINGS, client)
    assert client.calls == ["DP-100", "DP-200"]
    assert result.is_partial
    assert any("DP-300" in w.message for w in result.warnings)


def test_auth_failure_is_fatal():
    with pytest.raises(svc.DashboardLoadError) as exc:
        svc.load_dashboard(SETTINGS, FakeClient([], {}, viewer=error("auth")))
    assert exc.value.kind == "auth"


def test_ac13_invalid_response_on_myself_is_fatal_not_disguised():
    with pytest.raises(svc.DashboardLoadError) as exc:
        svc.load_dashboard(SETTINGS, FakeClient([epic(100)], {"DP-100": [raw(1)]}, viewer=error("invalid_response")))
    assert exc.value.kind == "invalid_response"


def test_all_epics_failed_is_fatal():
    children = {"DP-100": error("not_found"), "DP-200": error("not_found")}
    with pytest.raises(svc.DashboardLoadError) as exc:
        svc.load_dashboard(SETTINGS, FakeClient([epic(100), epic(200)], children))
    assert "JIRA_EPIC_LINK_FIELD_ID" in exc.value.message


def test_no_epics_returns_empty_result():
    result = svc.load_dashboard(SETTINGS, FakeClient([], {}))
    assert result.epics == () and result.issues == () and not result.is_partial


def test_ac17_unknown_category():
    children = {"DP-100": [raw(1, cat=None, status="이상"), raw(2, cat="weird"), raw(3)]}
    result = svc.load_dashboard(SETTINGS, FakeClient([epic(100)], children))
    s = result.summary
    assert s.unknown_count == 2
    assert s.task_count == s.in_progress_count + s.done_count + s.todo_count + s.unknown_count


def test_normalization_url_dates_and_unassigned():
    issue = svc.normalize_issue(
        raw(7, assignee=None, priority=None, due="2026-10-10", updated="2026-10-07T09:00:00.000+0900"),
        "DP-100",
        "https://jira.example.test/ctx/",
    )
    assert issue.assignee is None
    assert issue.url == "https://jira.example.test/ctx/browse/DP-7"
    assert issue.updated_at == "2026-10-07T00:00:00Z"
    assert issue.due_date == "2026-10-10"
    assert svc.format_kst(issue.updated_at) == "2026-10-07 09:00"
    assert svc.build_issue_url("https://x", "<script>") is None


def _frame(children, epics=None):
    epics = epics or [epic(100)]
    result = svc.load_dashboard(SETTINGS, FakeClient(epics, children))
    return result, svc.issues_frame(result.issues)


def test_ac02_ac08_groups_by_id_with_unassigned_last():
    children = {"DP-100": [
        raw(1, assignee=("u-a", "김개발")),
        raw(2, assignee=("u-b", "김개발")),
        raw(3, assignee=("u-b", "김개발")),
        raw(4, assignee=None),
        raw(5, assignee=("u-c", "가나다"), cat="done"),
    ]}
    _, df = _frame(children)
    labels = svc.assignee_labels(df)
    assert labels["u-a"] == "김개발 (u-a)" and labels["u-b"] == "김개발 (u-b)"
    assert list(labels)[-1] == svc.UNASSIGNED_ID

    groups = svc.assignee_groups(df, svc.STATUS_ALL, labels)
    assert [g.assignee_id for g in groups] == ["u-b", "u-a", "u-c", svc.UNASSIGNED_ID]
    assert sum(g.total for g in groups) == len(df)

    # 진행 중 필터에서는 진행 중 일감이 없는 담당자를 숨긴다.
    in_progress = svc.assignee_groups(df, IN_PROGRESS, labels)
    assert "u-c" not in [g.assignee_id for g in in_progress]


def test_ac06_scope_affects_summary_status_only_affects_rows():
    children = {
        "DP-100": [
            raw(1, assignee=("u-a", "A")),
            raw(2, assignee=("u-a", "A"), cat="done"),
            raw(3, assignee=("u-b", "B"), cat="done"),
        ],
        "DP-200": [raw(4, assignee=("u-a", "A"), cat="done")],
    }
    result, df = _frame(children, [epic(100), epic(200)])
    scoped = svc.scope_frame(df, "DP-100", "u-a")
    summary = svc.summarize(scoped, epic_count=1)
    assert (summary.task_count, summary.in_progress_count, summary.done_count) == (2, 1, 1)

    groups = svc.assignee_groups(scoped, DONE, svc.assignee_labels(df))
    assert len(groups) == 1
    assert list(groups[0].rows["key"]) == ["DP-2"]
    assert groups[0].in_progress == 1


def test_rows_sorted_by_updated_desc_then_key():
    children = {"DP-100": [
        raw(10, updated="2026-10-07T09:00:00.000+0900"),
        raw(9, updated="2026-10-07T09:00:00.000+0900"),
        raw(11, updated="2026-10-08T09:00:00.000+0900"),
        raw(12, updated=None),
    ]}
    _, df = _frame(children)
    assert list(svc.sort_rows(df)["key"]) == ["DP-11", "DP-9", "DP-10", "DP-12"]


def test_display_table_columns_and_placeholders():
    _, df = _frame({"DP-100": [raw(1, priority=None, cat="new", status="할 일")]})
    table = svc.display_table(df, {"DP-100": "카탈로그 개선"})
    row = table.iloc[0]
    assert row["일감"] == "https://jira.example.test/browse/DP-1"
    assert row["Epic"] == "DP-100 카탈로그 개선"
    assert row["상태"] == "대기 · 할 일"
    assert row["우선순위"] == "—" and row["기한"] == "—"


def test_classify_status():
    assert svc.classify_status("indeterminate") == IN_PROGRESS
    assert svc.classify_status("done") == DONE
    assert svc.classify_status("new") == TODO
    assert svc.classify_status(None) == UNKNOWN
    assert svc.classify_status("undefined") == UNKNOWN
