"""Per-run keys on an Otari gateway, for budget enforcement and cost per run.

When `settings.otari.url` is set, every run gets a key of its own, minted just
before its execution starts and deactivated when it finalizes:

- The key belongs to an Otari user named for the agent (`hackbot-<agent>`), so
  the budget on that user caps what the agent spends across all its runs (for
  example $200 a day), and Otari's usage pages break spend down per agent.
- `settings.otari.run_budget_id`, when set, also caps each run on its own: a
  scoped budget on the key, so one runaway run cannot drain the agent's budget.
- The key expires with the job, like the signed upload policy, so a leaked one
  is short-lived even if finalize never runs.

The run's cost is read back from Otari at finalize and stored on the run, so it
no longer depends on each agent summing `total_cost_usd` itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_API = "/api/v1"


@dataclass(frozen=True)
class RunKey:
    id: str
    key: str


def is_enabled() -> bool:
    return bool(settings.otari.url)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.otari.url.rstrip("/") + _API,
        headers={"Authorization": f"Bearer {settings.otari.master_key}"},
        timeout=30,
    )


def agent_user_id(agent: str) -> str:
    return f"hackbot-{agent}"


async def _ensure_agent_user(client: httpx.AsyncClient, agent: str) -> str:
    user_id = agent_user_id(agent)
    resp = await client.post(
        "/users",
        json={
            "user_id": user_id,
            "budget_id": settings.otari.agent_budget_id,
            "metadata": {"source": "hackbot", "agent": agent},
        },
    )
    # 409: the user exists already, with whatever budget an operator gave it.
    if resp.status_code != 409:
        resp.raise_for_status()
    return user_id


async def mint_run_key(
    agent: str, run_id: str, requested_by: str | None
) -> RunKey | None:
    """Mint the key a run calls the gateway with, or None when Otari is off."""
    if not is_enabled():
        return None

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.job_execution_timeout_seconds
        + settings.signed_policy_grace_seconds
    )
    async with _client() as client:
        user_id = await _ensure_agent_user(client, agent)
        resp = await client.post(
            "/keys",
            json={
                "key_name": f"hackbot-run-{run_id}",
                "user_id": user_id,
                "expires_at": expires_at.isoformat(),
                # Claude Code sends its own telemetry id as metadata.user_id;
                # spend still binds to this key's user.
                "reject_user_mismatch": False,
                "metadata": {
                    "source": "hackbot",
                    "agent": agent,
                    "run_id": run_id,
                    "requested_by": requested_by,
                },
            },
        )
        resp.raise_for_status()
        created = resp.json()
        run_key = RunKey(id=created["id"], key=created["key"])

        if settings.otari.run_budget_id:
            resp = await client.post(
                "/scoped-budgets",
                json={
                    "scope_type": "api_token",
                    "scope_id": run_key.id,
                    "budget_id": settings.otari.run_budget_id,
                    "name": f"hackbot-run-{run_id}",
                },
            )
            resp.raise_for_status()

    return run_key


def run_env(run_key: RunKey | None) -> dict[str, str]:
    """The agent container's env for routing through the gateway."""
    if run_key is None:
        return {}
    env = {
        "OTARI_BASE_URL": settings.otari.url.rstrip("/") + _API,
        "OTARI_API_KEY": run_key.key,
    }
    if settings.otari.web_search:
        env["OTARI_WEB_SEARCH"] = settings.otari.web_search
    return env


async def close_run_key(key_id: str, since: datetime) -> float | None:
    """Revoke a finished run's key and return what the run spent.

    Best effort: the key expires on its own, and a missing cost is only a gap
    in reporting, so neither failure fails the finalize.
    """
    cost: float | None = None
    async with _client() as client:
        try:
            resp = await client.get(
                "/usage/summary",
                params={
                    "api_key_id": key_id,
                    "start_date": since.isoformat(),
                    "dimensions": "none",
                },
            )
            resp.raise_for_status()
            cost = resp.json()["totals"]["cost"]
        except httpx.HTTPError, KeyError:
            log.warning("Could not read the spend of Otari key %s", key_id)
        # Deactivate rather than delete: deleting a key clears it from its
        # usage rows and leaves its scoped budget behind.
        try:
            resp = await client.patch(f"/keys/{key_id}", json={"is_active": False})
            if resp.status_code != 404:
                resp.raise_for_status()
        except httpx.HTTPError:
            log.warning("Could not revoke Otari key %s; it expires on its own", key_id)
    return cost
