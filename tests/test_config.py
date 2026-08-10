"""Tests for reading the settings from the environment."""

import pytest

from pinkbee_mcp.config import Config, ConfigError, load_config

ALL_VARIABLES = [
    "PINKBEE_DATA_SOURCE",
    "PINKBEE_BASE_URL",
    "PINKBEE_LOGIN",
    "PINKBEE_PASSWORD",
    "PINKBEE_ALLOW_PERSONAL_DATA",
    "PINKBEE_TIMEZONE",
    "PINKBEE_MCP_TRANSPORT",
    "PINKBEE_MCP_PORT",
    "PINKBEE_MCP_TOKEN",
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


def test_an_unknown_transport_is_rejected(monkeypatch):
    monkeypatch.setenv("PINKBEE_MCP_TRANSPORT", "sse")
    with pytest.raises(ConfigError, match="streamable-http"):
        load_config()


def test_a_non_numeric_port_is_rejected(monkeypatch):
    monkeypatch.setenv("PINKBEE_MCP_PORT", "eight-thousand")
    with pytest.raises(ConfigError, match="whole number"):
        load_config()


def test_the_password_and_token_never_appear_in_the_text_form():
    config = Config(password="my-password", token="my-token", login="someone@example.org")
    text = repr(config)
    assert "my-password" not in text
    assert "my-token" not in text
    assert "someone@example.org" in text
