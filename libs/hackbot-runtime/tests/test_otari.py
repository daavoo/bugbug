"""Tests for routing model traffic through an Otari gateway."""

import os

import pytest
from hackbot_runtime import anthropic_wif, otari
from hackbot_runtime.providers import ProviderError


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        otari.BASE_URL_ENV,
        otari.WEB_SEARCH_ENV,
        otari.CUSTOM_HEADERS_ENV,
        anthropic_wif.AUDIENCE_ENV,
        "ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_inert_without_base_url():
    assert otari.configure("r1", "bug-fix") is False
    assert "ANTHROPIC_BASE_URL" not in os.environ
    assert otari.CUSTOM_HEADERS_ENV not in os.environ


def test_points_the_sdk_at_the_gateway(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example/api/v1/")

    assert otari.configure("r1", "bug-fix") is True

    assert os.environ["ANTHROPIC_BASE_URL"] == "https://otari.example/api"
    assert os.environ[otari.CUSTOM_HEADERS_ENV].splitlines() == [
        "Otari-Conversation-Id: hackbot-r1",
        "Otari-Tags: app=hackbot,agent=bug-fix",
    ]


def test_leaves_authentication_to_the_runtime(monkeypatch):
    """Federation and a local key both pass through untouched."""
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example/api/v1")
    monkeypatch.setenv(anthropic_wif.RULE_ID_ENV, "rule-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "tk-local")

    otari.configure("r1", "bug-fix")

    assert os.environ[anthropic_wif.RULE_ID_ENV] == "rule-1"
    assert os.environ["ANTHROPIC_API_KEY"] == "tk-local"


def test_keeps_existing_custom_headers(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example/api/v1")
    monkeypatch.setenv(otari.CUSTOM_HEADERS_ENV, "X-Existing: 1\n")

    otari.configure("r1", "bug-fix")

    assert os.environ[otari.CUSTOM_HEADERS_ENV].splitlines()[0] == "X-Existing: 1"


@pytest.mark.parametrize("mode", otari.WEB_SEARCH_MODES)
def test_web_search_header(monkeypatch, mode):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example/api/v1")
    monkeypatch.setenv(otari.WEB_SEARCH_ENV, mode)

    otari.configure("r1", "bug-fix")

    assert f"Otari-Web-Search: {mode}" in os.environ[otari.CUSTOM_HEADERS_ENV]


def test_rejects_an_unknown_web_search_mode(monkeypatch):
    monkeypatch.setenv(otari.BASE_URL_ENV, "https://otari.example/api/v1")
    monkeypatch.setenv(otari.WEB_SEARCH_ENV, "always")

    with pytest.raises(ProviderError, match="OTARI_WEB_SEARCH"):
        otari.configure("r1", "bug-fix")


def test_identity_token_audience_override(monkeypatch):
    """A token minted for the gateway names the gateway's audience, not Anthropic's."""
    captured = {}

    def fake_fetch(audience):
        captured["audience"] = audience
        return "jwt"

    monkeypatch.setattr(anthropic_wif, "fetch_gcp_identity_token", fake_fetch)
    monkeypatch.setattr(anthropic_wif, "_refresher", None)
    monkeypatch.setenv(anthropic_wif.RULE_ID_ENV, "rule-1")
    monkeypatch.setenv(anthropic_wif.AUDIENCE_ENV, "https://otari.example")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(anthropic_wif.TOKEN_FILE_ENV, raising=False)

    assert anthropic_wif.configure() is True
    anthropic_wif._refresher.stop()

    assert captured["audience"] == "https://otari.example"
