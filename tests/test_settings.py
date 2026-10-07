import pytest

from settings import SettingsError, load_settings

VALID = {
    "JIRA_BASE_URL": "https://jira.example.test/jira/",
    "JIRA_PAT": "abc123",
    "JIRA_EPIC_TYPE_ID": "10000",
    "JIRA_TASK_TYPE_IDS": "10002, 10005",
}


def test_valid_settings_and_defaults():
    s = load_settings(env=VALID)
    assert s.base_url == "https://jira.example.test/jira"
    assert s.task_type_ids == ("10002", "10005")
    assert s.project_keys == ()
    assert (s.connect_timeout, s.read_timeout, s.collection_timeout) == (5.0, 10.0, 60.0)
    assert "abc123" not in repr(s)


def test_ac20_missing_items_reported():
    with pytest.raises(SettingsError) as exc:
        load_settings(env={}, secrets={})
    joined = " ".join(exc.value.problems)
    for name in ("JIRA_BASE_URL", "JIRA_PAT", "JIRA_EPIC_TYPE_ID", "JIRA_TASK_TYPE_IDS"):
        assert name in joined


def test_placeholders_and_example_host_rejected():
    secrets = {
        "JIRA_BASE_URL": "https://jira.company.com",
        "JIRA_PAT": "REPLACE_WITH_YOUR_PAT",
        "JIRA_EPIC_TYPE_ID": "REPLACE_WITH_EPIC_TYPE_ID",
        "JIRA_TASK_TYPE_IDS": "REPLACE_WITH_TASK_TYPE_ID",
    }
    with pytest.raises(SettingsError) as exc:
        load_settings(env={}, secrets=secrets)
    assert len(exc.value.problems) == 4


def test_env_takes_priority_over_secrets():
    s = load_settings(env={"JIRA_PAT": "from-env"}, secrets={**VALID, "JIRA_PAT": "from-secrets"})
    assert s.pat == "from-env"


def test_invalid_values_rejected():
    env = {**VALID, "JIRA_EPIC_TYPE_ID": "Epic", "JIRA_PROJECT_KEYS": "dp", "JIRA_READ_TIMEOUT_SECONDS": "-1"}
    with pytest.raises(SettingsError) as exc:
        load_settings(env=env)
    assert len(exc.value.problems) == 3
