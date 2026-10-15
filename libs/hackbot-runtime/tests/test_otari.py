"""Tests for routing model traffic through an Otari gateway."""

import os

import pytest
from hackbot_runtime import anthropic_wif, otari
from hackbot_runtime.providers import ProviderError


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        otari.BASE_URL_ENV,
        otari.KEY_ENV,
        otari.WEB_SEARCH_ENV,
        otari.CUSTOM_HEADERS_ENV,
        anthropic_wif.RULE_ID_ENV,
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_inert_without_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    assert otari.configure("r1") is False
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-real"
    assert "ANTHROPIC_BASE_URL" not in os.environ


def test_points_the_sdk_at_the_gateway(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example/api/v1/")
    monkeypatch.setenv(otari.KEY_ENV, "tk-run")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")

    assert otari.configure("r1") is True

    assert os.environ["ANTHROPIC_BASE_URL"] == "https://otari.example/api"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "tk-run"
    # The real Anthropic key must never reach the gateway.
    assert os.environ["ANTHROPIC_API_KEY"] == "tk-run"
    assert os.environ[otari.CUSTOM_HEADERS_ENV] == "Otari-Conversation-Id: hackbot-r1"


def test_keeps_existing_custom_headers_and_adds_web_search(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example")
    monkeypatch.setenv(otari.KEY_ENV, "tk-run")
    monkeypatch.setenv(otari.WEB_SEARCH_ENV, "auto")
    monkeypatch.setenv(otari.CUSTOM_HEADERS_ENV, "X-Existing: 1\n")

    otari.configure("r1")

    assert os.environ[otari.CUSTOM_HEADERS_ENV].splitlines() == [
        "X-Existing: 1",
        "Otari-Conversation-Id: hackbot-r1",
        "Otari-Web-Search: auto",
    ]


def test_rejects_an_unknown_web_search_mode(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example")
    monkeypatch.setenv(otari.KEY_ENV, "tk-run")
    monkeypatch.setenv(otari.WEB_SEARCH_ENV, "always")
    with pytest.raises(ProviderError, match=otari.WEB_SEARCH_ENV):
        otari.configure("r1")


def test_requires_a_run_key(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example")
    with pytest.raises(ProviderError, match=otari.KEY_ENV):
        otari.configure("r1")


def test_refuses_to_combine_with_federation(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example")
    monkeypatch.setenv(otari.KEY_ENV, "tk-run")
    monkeypatch.setenv(anthropic_wif.RULE_ID_ENV, "fdrl_abc")
    with pytest.raises(ProviderError, match="not both"):
        otari.configure("r1")
