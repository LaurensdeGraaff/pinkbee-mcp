"""Tests for reading the settings from the environment."""

import pytest

from pinkbee_mcp.config import Config, ConfigError, load_config

ALL_VARIABLES = [
    "PINKBEE_DATA_SOURCE",
    "PINKBEE_BASE_URL",
    "PINKBEE_LOGIN",
    "PINKBEE_PASSWORD",
    "PINKBEE_ALLOW_PERSONAL_DATA",
    "ENABLE_WRITE_TO_PINKBEE",
    "PINKBEE_TIMEZONE",
    "PINKBEE_MCP_TOKEN",
    "PINKBEE_ALLOWED_SENDERS",
    "PINKBEE_DISABLED_CALLS",
    "PINKBEE_ALLOW_INSECURE_HTTP_TO_LOCALHOST",
    "PINKBEE_TIMEOUT_SECONDS",
]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def set_live_credentials(monkeypatch):
    monkeypatch.setenv("PINKBEE_DATA_SOURCE", "live")
    monkeypatch.setenv("PINKBEE_BASE_URL", "https://example.mijnpinkbee.nl/")
    monkeypatch.setenv("PINKBEE_LOGIN", "someone@example.org")
    monkeypatch.setenv("PINKBEE_PASSWORD", "secret")


def test_an_empty_environment_gives_mock_data():
    """The safe default: no configuration means no live connection."""
    config = load_config()
    assert config.data_source == "mock"
    assert config.is_live is False


def test_personal_data_is_off_by_default():
    assert load_config().allow_personal_data is False


def test_live_writes_require_explicit_opt_in(monkeypatch):
    set_live_credentials(monkeypatch)
    assert load_config().enable_write_to_pinkbee is False
    monkeypatch.setenv("ENABLE_WRITE_TO_PINKBEE", "true")
    assert load_config().enable_write_to_pinkbee is True
    monkeypatch.setenv("ENABLE_WRITE_TO_PINKBEE", "false")
    assert load_config().enable_write_to_pinkbee is False


def test_mock_mode_needs_no_credentials():
    config = load_config()
    assert config.login == ""
    assert config.password == ""


def test_live_mode_lists_everything_that_is_missing(monkeypatch):
    monkeypatch.setenv("PINKBEE_DATA_SOURCE", "live")
    monkeypatch.setenv("PINKBEE_LOGIN", "someone@example.org")
    with pytest.raises(ConfigError) as error:
        load_config()
    message = str(error.value)
    assert "PINKBEE_BASE_URL" in message
    assert "PINKBEE_PASSWORD" in message
    assert "PINKBEE_LOGIN" not in message


def test_live_mode_works_with_all_credentials(monkeypatch):
    set_live_credentials(monkeypatch)
    config = load_config()
    assert config.is_live is True
    assert config.base_url == "https://example.mijnpinkbee.nl"  # trailing slash removed


def test_live_mode_rejects_a_url_without_a_scheme(monkeypatch):
    set_live_credentials(monkeypatch)
    monkeypatch.setenv("PINKBEE_BASE_URL", "example.mijnpinkbee.nl")
    with pytest.raises(ConfigError, match="http"):
        load_config()


def test_an_unknown_data_source_is_rejected(monkeypatch):
    monkeypatch.setenv("PINKBEE_DATA_SOURCE", "production")
    with pytest.raises(ConfigError, match="must be 'mock' or 'live'"):
        load_config()


def test_personal_data_flag_accepts_several_spellings(monkeypatch):
    for value in ["true", "TRUE", "yes", "on", "1"]:
        monkeypatch.setenv("PINKBEE_ALLOW_PERSONAL_DATA", value)
        assert load_config().allow_personal_data is True
    for value in ["false", "no", "off", "0"]:
        monkeypatch.setenv("PINKBEE_ALLOW_PERSONAL_DATA", value)
        assert load_config().allow_personal_data is False


def test_timezone_defaults_to_amsterdam():
    assert load_config().timezone == "Europe/Amsterdam"


def test_an_unknown_timezone_is_rejected(monkeypatch):
    monkeypatch.setenv("PINKBEE_TIMEZONE", "Mars/Olympus_Mons")
    with pytest.raises(ConfigError, match="not a known timezone"):
        load_config()


def test_sender_allowlist_is_empty_by_default():
    assert load_config().allowed_senders == ()


def test_sender_allowlist_accepts_ips_and_domains(monkeypatch):
    monkeypatch.setenv("PINKBEE_ALLOWED_SENDERS", "192.168.1.42, agent.example.com")
    assert load_config().allowed_senders == ("192.168.1.42", "agent.example.com")


def test_disabled_calls_are_empty_by_default():
    assert load_config().disabled_calls == ()


def test_disabled_calls_are_read_as_a_list(monkeypatch):
    monkeypatch.setenv(
        "PINKBEE_DISABLED_CALLS",
        "pinkbee_list_group_emails, pinkbee_list_registrations",
    )
    assert load_config().disabled_calls == (
        "pinkbee_list_group_emails",
        "pinkbee_list_registrations",
    )


def test_write_call_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PINKBEE_DISABLED_CALLS", "pinkbee_set_week_registration_possibilities")
    assert load_config().disabled_calls == ("pinkbee_set_week_registration_possibilities",)


def test_duplicate_disabled_calls_are_deduplicated(monkeypatch):
    monkeypatch.setenv(
        "PINKBEE_DISABLED_CALLS",
        "pinkbee_check_connection,pinkbee_check_connection",
    )
    assert load_config().disabled_calls == ("pinkbee_check_connection",)


def test_unknown_disabled_call_is_rejected(monkeypatch):
    monkeypatch.setenv("PINKBEE_DISABLED_CALLS", "pinkbee_delete_everything")
    with pytest.raises(ConfigError, match="unknown calls"):
        load_config()


def test_the_password_and_token_never_appear_in_the_text_form():
    config = Config(password="my-password", token="my-token", login="someone@example.org")
    text = repr(config)
    assert "my-password" not in text
    assert "my-token" not in text
    assert "someone@example.org" in text
