"""Route an agent's model traffic through an Otari gateway.

Otari (https://github.com/mozilla-ai/otari) is an Anthropic-compatible LLM
gateway: it enforces spend caps per key, records the cost of every request, and
can serve a model id from a provider other than Anthropic, open-weight models
included. Pointing the Claude SDK/CLI at it is a matter of environment
variables, so no agent code changes:

  ``OTARI_BASE_URL``    the gateway's API root (``…/api/v1``) ── set by deploy
  ``OTARI_API_KEY``     a key minted for this run            ── set per run
  ``OTARI_WEB_SEARCH``  ``auto`` | ``otari`` | ``provider``  ── optional

hackbot-api mints ``OTARI_API_KEY`` per run, capped by a budget and expiring
with the job, so the agent container still holds no long-lived credential.

Every request carries ``Otari-Conversation-Id: hackbot-<run_id>``, which groups
a run's model calls into one trace on the gateway, across every ``query()`` and
subagent the run makes. ``OTARI_WEB_SEARCH`` sets ``Otari-Web-Search``, so
Claude Code's WebSearch keeps working on a model with no search of its own.

When ``OTARI_BASE_URL`` is absent this module is inert and the runtime talks to
Anthropic directly, through WIF or ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import logging
import os

from hackbot_runtime import anthropic_wif
from hackbot_runtime.providers import ProviderError

log = logging.getLogger("hackbot_runtime.otari")

BASE_URL_ENV = "OTARI_BASE_URL"
KEY_ENV = "OTARI_API_KEY"
WEB_SEARCH_ENV = "OTARI_WEB_SEARCH"

CONVERSATION_HEADER = "Otari-Conversation-Id"
WEB_SEARCH_HEADER = "Otari-Web-Search"
WEB_SEARCH_MODES = ("auto", "otari", "provider")

# Claude Code reads extra request headers from this variable, one
# ``Name: value`` per line.
CUSTOM_HEADERS_ENV = "ANTHROPIC_CUSTOM_HEADERS"


def is_enabled() -> bool:
    """True when the deploy points the runtime at an Otari gateway."""
    return bool(os.environ.get(BASE_URL_ENV))


def _headers(run_id: str) -> list[str]:
    headers = [f"{CONVERSATION_HEADER}: hackbot-{run_id}"]
    web_search = os.environ.get(WEB_SEARCH_ENV)
    if web_search:
        if web_search not in WEB_SEARCH_MODES:
            raise ProviderError(
                f"{WEB_SEARCH_ENV} must be one of {', '.join(WEB_SEARCH_MODES)}; "
                f"got {web_search!r}."
            )
        headers.append(f"{WEB_SEARCH_HEADER}: {web_search}")
    return headers


def configure(run_id: str) -> bool:
    """Point the Claude SDK/CLI at the gateway when the deploy enables it.

    Returns ``True`` when the gateway was configured, ``False`` when it is not
    enabled. Raises :class:`ProviderError` on a configuration that would send
    traffic somewhere other than intended.
    """
    if not is_enabled():
        return False

    # Federation would mint an Anthropic token the gateway has no use for, and
    # leave it unclear which path a request took.
    if anthropic_wif.is_enabled():
        raise ProviderError(
            f"{BASE_URL_ENV} and {anthropic_wif.RULE_ID_ENV} are both set; "
            "route through the gateway or federate with Anthropic, not both."
        )

    key = os.environ.get(KEY_ENV)
    if not key:
        raise ProviderError(
            f"{BASE_URL_ENV} is set but {KEY_ENV} is not; the run has no "
            "credential for the gateway."
        )

    # Same convention as langchain-otari. The SDK appends /v1/messages itself.
    api_root = os.environ[BASE_URL_ENV].rstrip("/")
    os.environ["ANTHROPIC_BASE_URL"] = api_root.removesuffix("/v1")
    # Both names carry the gateway key, which also replaces any real Anthropic
    # key in the environment so it is never sent to the gateway. The CLI sends
    # the auth token as a bearer and the Python SDK sends the API key as
    # x-api-key; Otari accepts either.
    os.environ["ANTHROPIC_AUTH_TOKEN"] = key
    os.environ["ANTHROPIC_API_KEY"] = key

    existing = os.environ.get(CUSTOM_HEADERS_ENV, "")
    lines = [line for line in existing.splitlines() if line.strip()]
    lines.extend(_headers(run_id))
    os.environ[CUSTOM_HEADERS_ENV] = "\n".join(lines)

    log.info("Model traffic routed through Otari at %s", os.environ[BASE_URL_ENV])
    return True
