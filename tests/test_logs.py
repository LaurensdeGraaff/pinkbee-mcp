"""Tests for the logging, including the promise that it never leaks personal data."""

import logging
import re

import pytest

from pinkbee_mcp import server
from pinkbee_mcp.config import Config
from pinkbee_mcp.logs import (
    RequestLogger,
    answer_text_of,
    describe_arguments,
    setup_logging,
    shorten,
    summarise_answer,
)
from pinkbee_mcp.mock import MockPinkbee

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


@pytest.fixture(autouse=True)
def personal_data_allowed():
    """Worst case for leaking: live-shaped data with personal data switched on."""
    server.setup(Config(allow_personal_data=True), MockPinkbee())


# --- summarise_answer: shape, never content -------------------------------


def test_summarise_keeps_top_level_numbers():
    assert summarise_answer('{"count": 40, "start_date": "2026-08-10"}') == (
        "count=40, start_date=2026-08-10"
    )


def test_summarise_reports_list_lengths_but_not_their_contents():
    summary = summarise_answer('{"emails": ["a@b.nl", "c@d.nl"], "count": 2}')
    assert "count=2" in summary
    assert "emails[]=2" in summary
    assert "a@b.nl" not in summary


def test_summarise_ignores_nested_objects():
    summary = summarise_answer('{"person": {"name": "Ann", "email": "a@b.nl"}, "count": 1}')
    assert "Ann" not in summary
    assert "a@b.nl" not in summary
    assert "count=1" in summary


def test_summarise_falls_back_to_a_length_for_plain_text():
    assert summarise_answer("OK: connected") == "13 chars of text"


def test_summarise_handles_a_json_list():
    assert summarise_answer('[{"email": "a@b.nl"}]') == "21 chars of JSON"


def test_shorten_cuts_long_text():
    assert shorten("x" * 300, limit=10) == "x" * 10 + "…"


# --- describe_arguments ---------------------------------------------------


def test_describe_arguments_shows_the_tool_and_its_arguments():
    described = describe_arguments(
        {"name": "pinkbee_list_open_shifts", "arguments": {"weeks": 6, "group_ids": [2]}}
    )
    assert described == "pinkbee_list_open_shifts(group_ids=[2], weeks=6)"


def test_describe_arguments_handles_a_tool_without_arguments():
    assert describe_arguments({"name": "pinkbee_check_connection", "arguments": {}}) == (
        "pinkbee_check_connection()"
    )


def test_describe_arguments_survives_unexpected_params():
    assert describe_arguments(None) == "?"
    assert describe_arguments({}) == "?()"


# --- answer_text_of -------------------------------------------------------


def test_answer_text_of_reads_a_dict_shaped_result():
    assert answer_text_of({"content": [{"type": "text", "text": "hello"}]}) == "hello"


def test_answer_text_of_returns_none_for_other_shapes():
    assert answer_text_of(None) is None
    assert answer_text_of({"content": []}) is None
    assert answer_text_of({}) is None


# --- the middleware -------------------------------------------------------


class FakeContext:
    def __init__(self, method="tools/call", params=None, request_id=1):
        self.method = method
        self.params = params or {}
        self.request_id = request_id


async def test_middleware_logs_one_info_line_per_call(caplog):
    caplog.set_level(logging.INFO, logger="pinkbee_mcp")
    ctx = FakeContext(params={"name": "pinkbee_check_connection", "arguments": {}})

    async def call_next(_):
        return {"content": [{"type": "text", "text": '{"count": 3}'}]}

    await RequestLogger()(ctx, call_next)
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1
    assert "pinkbee_check_connection()" in lines[0]
    assert "count=3" in lines[0]
    assert "ms" in lines[0]


async def test_middleware_logs_a_tool_error_as_a_warning(caplog):
    caplog.set_level(logging.INFO, logger="pinkbee_mcp")
    ctx = FakeContext(params={"name": "pinkbee_list_group_emails", "arguments": {}})

    async def call_next(_):
        return {"content": [{"type": "text", "text": "Error: switched off"}]}

    await RequestLogger()(ctx, call_next)
    assert caplog.records[0].levelno == logging.WARNING
    assert "Error: switched off" in caplog.records[0].getMessage()


async def test_middleware_logs_and_reraises_a_crash(caplog):
    caplog.set_level(logging.INFO, logger="pinkbee_mcp")
    ctx = FakeContext(params={"name": "pinkbee_check_connection", "arguments": {}})

    async def call_next(_):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await RequestLogger()(ctx, call_next)
    assert "raised RuntimeError" in caplog.records[0].getMessage()


async def test_middleware_does_not_add_info_noise_for_notifications(caplog):
    caplog.set_level(logging.INFO, logger="pinkbee_mcp")
    ctx = FakeContext(method="notifications/initialized", request_id=None)

    async def call_next(_):
        return None

    await RequestLogger()(ctx, call_next)
    assert caplog.records == []


# --- the promise: no personal data in the logs, at any level --------------


async def test_debug_logs_of_every_tool_contain_no_email_address(caplog):
    """The strongest guarantee this project makes about its own logging."""
    caplog.set_level(logging.DEBUG)

    await server.pinkbee_check_connection()
    await server.pinkbee_list_groups_and_shifts()
    await server.pinkbee_get_week_schedule(dates=["2026-08-13"])
    await server.pinkbee_list_open_shifts(start_date="2026-08-10", weeks=2)
    await server.pinkbee_list_group_emails(group_ids=[2, 15], with_names=True)
    await server.pinkbee_list_registrations(start_date="2026-08-10", end_date="2026-08-31")

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert logged, "expected some debug output"
    assert not EMAIL.search(logged), f"an email address reached the log: {logged}"


async def test_debug_logs_of_every_tool_contain_no_volunteer_name(caplog):
    caplog.set_level(logging.DEBUG)
    await server.pinkbee_list_group_emails(group_ids=[2], with_names=True)
    await server.pinkbee_list_registrations(start_date="2026-08-10", end_date="2026-08-31")

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for surname in ["Bakker", "de Vries", "Smit", "Jansen", "Molenaar", "Visser"]:
        assert surname not in logged, f"{surname} reached the log"


async def test_the_middleware_summary_of_the_email_tool_leaks_nothing(caplog):
    caplog.set_level(logging.INFO, logger="pinkbee_mcp")
    answer = await server.pinkbee_list_group_emails(group_ids=[2])

    async def call_next(_):
        return {"content": [{"type": "text", "text": answer}]}

    ctx = FakeContext(params={"name": "pinkbee_list_group_emails", "arguments": {"group_ids": [2]}})
    await RequestLogger()(ctx, call_next)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "emails[]=" in logged  # the count is useful
    assert not EMAIL.search(logged)  # the addresses are not there


# --- setup_logging --------------------------------------------------------


def test_setup_logging_applies_the_named_level():
    try:
        setup_logging("WARNING")
        assert logging.getLogger().level == logging.WARNING
        setup_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG
    finally:
        setup_logging("INFO")


def test_setup_logging_falls_back_to_info_for_nonsense():
    try:
        setup_logging("chatty")
        assert logging.getLogger().level == logging.INFO
    finally:
        setup_logging("INFO")
