"""Tests for per-run Otari keys: minting, the agent env, and closing."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from app import otari
from app.config import settings


@pytest.fixture
def gateway(monkeypatch):
    """Point settings at a fake Otari and record every request it receives."""
    requests: list[httpx.Request] = []
    responses: dict[tuple[str, str], httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.get(
            (request.method, request.url.path), httpx.Response(404, json={})
        )

    monkeypatch.setattr(settings.otari, "url", "https://otari.example")
    monkeypatch.setattr(settings.otari, "master_key", "mk")
    monkeypatch.setattr(
        otari,
        "_client",
        lambda: httpx.AsyncClient(
            base_url="https://otari.example/api/v1",
            headers={"Authorization": "Bearer mk"},
            transport=httpx.MockTransport(handler),
        ),
    )
    return requests, responses


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


async def test_mint_is_a_no_op_without_a_gateway(monkeypatch):
    monkeypatch.setattr(settings.otari, "url", "")
    assert await otari.mint_run_key("bug-fix", "r1", None) is None
    assert otari.run_env(None) == {}


async def test_mint_creates_the_agent_user_and_a_run_key(gateway, monkeypatch):
    requests, responses = gateway
    monkeypatch.setattr(settings.otari, "agent_budget_id", "daily-200")
    responses[("POST", "/api/v1/users")] = httpx.Response(201, json={})
    responses[("POST", "/api/v1/keys")] = httpx.Response(
        201, json={"id": "key-1", "key": "tk-secret"}
    )

    run_key = await otari.mint_run_key("bug-fix", "r1", "dev@mozilla.com")

    assert run_key == otari.RunKey(id="key-1", key="tk-secret")
    user, key = (_body(r) for r in requests)
    assert user["user_id"] == "hackbot-bug-fix"
    assert user["budget_id"] == "daily-200"
    assert key["user_id"] == "hackbot-bug-fix"
    assert key["key_name"] == "hackbot-run-r1"
    assert key["reject_user_mismatch"] is False
    assert key["metadata"]["requested_by"] == "dev@mozilla.com"
    assert datetime.fromisoformat(key["expires_at"]) > datetime.now(timezone.utc)
    # No run budget configured, so no scoped budget.
    assert len(requests) == 2


async def test_mint_tolerates_an_existing_user_and_caps_the_run(gateway, monkeypatch):
    requests, responses = gateway
    monkeypatch.setattr(settings.otari, "run_budget_id", "per-run-20")
    responses[("POST", "/api/v1/users")] = httpx.Response(409, json={})
    responses[("POST", "/api/v1/keys")] = httpx.Response(
        201, json={"id": "key-1", "key": "tk-secret"}
    )
    responses[("POST", "/api/v1/scoped-budgets")] = httpx.Response(201, json={})

    await otari.mint_run_key("bug-fix", "r1", None)

    scoped = _body(requests[-1])
    assert scoped["scope_type"] == "api_token"
    assert scoped["scope_id"] == "key-1"
    assert scoped["budget_id"] == "per-run-20"


async def test_mint_fails_when_the_gateway_refuses_the_key(gateway):
    _, responses = gateway
    responses[("POST", "/api/v1/users")] = httpx.Response(201, json={})
    responses[("POST", "/api/v1/keys")] = httpx.Response(403, json={})

    with pytest.raises(httpx.HTTPStatusError):
        await otari.mint_run_key("bug-fix", "r1", None)


def test_run_env_carries_the_gateway_and_web_search(monkeypatch):
    monkeypatch.setattr(settings.otari, "url", "https://otari.example")
    monkeypatch.setattr(settings.otari, "web_search", "auto")

    env = otari.run_env(otari.RunKey(id="key-1", key="tk-secret"))

    assert env == {
        "OTARI_BASE_URL": "https://otari.example",
        "OTARI_API_KEY": "tk-secret",
        "OTARI_WEB_SEARCH": "auto",
    }


async def test_close_reads_the_spend_and_revokes(gateway):
    requests, responses = gateway
    responses[("GET", "/api/v1/usage/summary")] = httpx.Response(
        200, json={"totals": {"cost": 3.5}}
    )
    responses[("DELETE", "/api/v1/keys/key-1")] = httpx.Response(204)

    cost = await otari.close_run_key("key-1", datetime.now(timezone.utc))

    assert cost == 3.5
    assert requests[0].url.params["api_key_id"] == "key-1"
    assert requests[1].method == "DELETE"


async def test_close_is_best_effort(gateway):
    _, responses = gateway
    responses[("GET", "/api/v1/usage/summary")] = httpx.Response(500, json={})
    responses[("DELETE", "/api/v1/keys/key-1")] = httpx.Response(500, json={})

    assert await otari.close_run_key("key-1", datetime.now(timezone.utc)) is None
