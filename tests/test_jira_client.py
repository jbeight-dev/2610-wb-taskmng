import pytest
import requests

from jira_client import JiraClient, JiraError, build_epic_jql
from settings import Settings


def make_settings(**overrides):
    values = dict(
        base_url="https://jira.example.test",
        pat="test-token",
        epic_type_id="10000",
        task_type_ids=("10002",),
        collection_timeout=60.0,
    )
    values.update(overrides)
    return Settings(**values)


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, json_ok=True):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self._json_ok = json_ok

    def json(self):
        if not self._json_ok:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.handler(method, url, kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(handler, settings=None, clock=None):
    clock = clock or FakeClock()
    session = FakeSession(handler)
    client = JiraClient(settings or make_settings(), session=session, clock=clock, sleep=clock.sleep)
    client.begin_collection()
    return client, session, clock


def issues(n, prefix="DP"):
    return [{"id": str(1000 + i), "key": f"{prefix}-{i}", "fields": {"summary": f"S{i}"}} for i in range(1, n + 1)]


def test_bearer_header_and_myself_uses_user_key():
    client, session, _ = make_client(
        lambda m, u, k: FakeResponse(payload={"key": "user-key-1", "name": "login", "displayName": "홍길동"})
    )
    viewer = client.get_myself()
    assert viewer.jira_user_id == "user-key-1"
    assert viewer.display_name == "홍길동"
    assert session.headers["Authorization"] == "Bearer test-token"
    assert session.calls[0][1] == "https://jira.example.test/rest/api/2/myself"


def test_epic_jql_uses_type_id_current_user_and_projects():
    jql = build_epic_jql(make_settings(project_keys=("DP", "OPS")))
    assert jql.startswith("issuetype = 10000 AND assignee = currentUser()")
    assert 'project in ("DP", "OPS")' in jql


def test_pagination_advances_by_returned_count_when_server_returns_fewer():
    data = issues(5)

    def handler(method, url, kwargs):
        start = kwargs["json"]["startAt"]
        return FakeResponse(payload={"startAt": start, "total": 5, "issues": data[start:start + 2]})

    client, session, _ = make_client(handler)
    epics = client.search_epics()
    assert [e.key for e in epics] == [f"DP-{i}" for i in range(1, 6)]
    assert [c[2]["json"]["startAt"] for c in session.calls] == [0, 2, 4]


def test_agile_epic_issue_pagination():
    data = issues(3)

    def handler(method, url, kwargs):
        assert url.endswith("/rest/agile/1.0/epic/DP-100/issue")
        start = kwargs["params"]["startAt"]
        return FakeResponse(payload={"total": 3, "issues": data[start:start + 1]})

    client, session, _ = make_client(handler)
    assert [r["key"] for r in client.get_epic_issues("DP-100")] == ["DP-1", "DP-2", "DP-3"]
    assert len(session.calls) == 3


def test_empty_page_before_total_is_incomplete_with_partial_items():
    data = issues(2)

    def handler(method, url, kwargs):
        start = kwargs["params"]["startAt"]
        return FakeResponse(payload={"total": 10, "issues": data[start:start + 2]})

    client, _, _ = make_client(handler)
    with pytest.raises(JiraError) as exc:
        client.get_epic_issues("DP-100")
    assert exc.value.kind == "incomplete"
    assert len(exc.value.partial_items) == 2


def test_failure_mid_pagination_keeps_partial_items():
    data = issues(4)

    def handler(method, url, kwargs):
        start = kwargs["params"]["startAt"]
        if start >= 2:
            return FakeResponse(status=403)
        return FakeResponse(payload={"total": 4, "issues": data[start:start + 2]})

    client, _, _ = make_client(handler)
    with pytest.raises(JiraError) as exc:
        client.get_epic_issues("DP-100")
    assert exc.value.kind == "forbidden"
    assert [r["key"] for r in exc.value.partial_items] == ["DP-1", "DP-2"]


@pytest.mark.parametrize("status,kind", [(400, "bad_request"), (401, "auth"), (403, "forbidden"), (404, "not_found")])
def test_client_errors_are_not_retried(status, kind):
    client, session, clock = make_client(lambda m, u, k: FakeResponse(status=status))
    with pytest.raises(JiraError) as exc:
        client.get_myself()
    assert exc.value.kind == kind
    assert len(session.calls) == 1
    assert clock.sleeps == []


def test_transient_5xx_is_retried_then_succeeds():
    responses = [FakeResponse(status=503), FakeResponse(payload={"key": "u1", "displayName": "A"})]
    client, session, clock = make_client(lambda m, u, k: responses.pop(0))
    assert client.get_myself().jira_user_id == "u1"
    assert len(session.calls) == 2
    assert clock.sleeps == [0.5]


def test_429_honors_retry_after():
    responses = [
        FakeResponse(status=429, headers={"Retry-After": "3"}),
        FakeResponse(payload={"key": "u1", "displayName": "A"}),
    ]
    client, _, clock = make_client(lambda m, u, k: responses.pop(0))
    client.get_myself()
    assert clock.sleeps == [3.0]


def test_network_errors_retry_limited_times():
    client, session, _ = make_client(lambda m, u, k: requests.ConnectionError("down"))
    with pytest.raises(JiraError) as exc:
        client.get_myself()
    assert exc.value.kind == "network"
    assert len(session.calls) == 3


def test_html_login_page_is_reported_as_invalid_response():
    client, _, _ = make_client(lambda m, u, k: FakeResponse(payload=None, json_ok=False))
    with pytest.raises(JiraError) as exc:
        client.get_myself()
    assert exc.value.kind == "invalid_response"


def test_collection_budget_stops_pagination():
    clock = FakeClock()
    data = issues(10)

    def handler(method, url, kwargs):
        clock.now += 2.0
        start = kwargs["params"]["startAt"]
        return FakeResponse(payload={"total": 10, "issues": data[start:start + 2]})

    client, session, _ = make_client(handler, settings=make_settings(collection_timeout=3.0), clock=clock)
    with pytest.raises(JiraError) as exc:
        client.get_epic_issues("DP-100")
    assert exc.value.kind == "timeout"
    assert len(exc.value.partial_items) == 4
    assert len(session.calls) == 2


def test_epic_link_field_mode_uses_search_jql():
    def handler(method, url, kwargs):
        assert url.endswith("/rest/api/2/search")
        assert kwargs["json"]["jql"].startswith('cf[10014] = "DP-100" AND issuetype in (10002)')
        return FakeResponse(payload={"total": 0, "issues": []})

    client, _, _ = make_client(handler, settings=make_settings(epic_link_field_id="customfield_10014"))
    assert client.get_epic_issues("DP-100") == []


def test_invalid_epic_key_rejected_before_request():
    client, session, _ = make_client(lambda m, u, k: FakeResponse(payload={}))
    with pytest.raises(JiraError):
        client.get_epic_issues('DP-1" OR 1=1')
    assert session.calls == []
