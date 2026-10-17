"""Route an agent's model traffic through an Otari gateway.

Otari (https://github.com/mozilla-ai/otari) is an Anthropic-compatible LLM
gateway: it enforces spend caps, records the cost of every request, and can
serve a run from a provider other than Anthropic, open-weight models included.
The Claude SDK/CLI only needs a different base URL, so no agent code changes:

  ``OTARI_BASE_URL``    the gateway's API root (``…/api/v1``)  ── set by deploy
  ``OTARI_WEB_SEARCH``  ``auto`` | ``otari`` | ``provider``   ── optional

Authentication is unchanged. Otari answers the same Workload Identity
Federation exchange Anthropic does, so a deployed run keeps its Google identity
token and :mod:`anthropic_wif`; the deploy points ``ANTHROPIC_FEDERATION_RULE_ID``
and ``ANTHROPIC_ORGANIZATION_ID`` at the Otari rule and organization, and
``ANTHROPIC_IDENTITY_TOKEN_AUDIENCE`` at the audience that rule matches. A local
run sets ``ANTHROPIC_API_KEY`` to an Otari key instead.

Every request carries ``Otari-Conversation-Id: hackbot-<run_id>``, which groups
a run's model calls into one trace on the gateway, across every ``query()`` and
subagent the run makes, and ``Otari-Tags: app=hackbot,agent=<agent>``, which
splits usage by agent. ``OTARI_WEB_SEARCH`` sets ``Otari-Web-Search``, so Claude
Code's WebSearch is run by Otari's search backend where asked.

When ``OTARI_BASE_URL`` is absent this module is inert and the runtime talks to
Anthropic directly.
"""

from __future__ import annotations

import logging
import os

from hackbot_runtime.providers import ProviderError

log = logging.getLogger("hackbot_runtime.otari")

BASE_URL_ENV = "OTARI_BASE_URL"
WEB_SEARCH_ENV = "OTARI_WEB_SEARCH"

CONVERSATION_HEADER = "Otari-Conversation-Id"
TAGS_HEADER = "Otari-Tags"
WEB_SEARCH_HEADER = "Otari-Web-Search"
WEB_SEARCH_MODES = ("auto", "otari", "provider")

# Claude Code reads extra request headers from this variable, one
# ``Name: value`` per line.
CUSTOM_HEADERS_ENV = "ANTHROPIC_CUSTOM_HEADERS"


def is_enabled() -> bool:
    """True when the deploy points the runtime at an Otari gateway."""
    return bool(os.environ.get(BASE_URL_ENV))


def _headers(run_id: str, agent: str) -> list[str]:
    headers = [
        f"{CONVERSATION_HEADER}: hackbot-{run_id}",
        f"{TAGS_HEADER}: app=hackbot,agent={agent}",
    ]
    web_search = os.environ.get(WEB_SEARCH_ENV)
    if web_search:
        if web_search not in WEB_SEARCH_MODES:
            raise ProviderError(
                f"{WEB_SEARCH_ENV} must be one of {', '.join(WEB_SEARCH_MODES)}; "
                f"got {web_search!r}."
            )
        headers.append(f"{WEB_SEARCH_HEADER}: {web_search}")
    return headers


def configure(run_id: str, agent: str) -> bool:
    """Point the Claude SDK/CLI at the gateway when the deploy enables it.

    Returns ``True`` when the gateway was configured, ``False`` when it is not
    enabled. Raises :class:`ProviderError` on an invalid ``OTARI_WEB_SEARCH``.
    """
    if not is_enabled():
        return False

    # Same convention as langchain-otari. The SDK appends /v1/messages, and the
    # federation exchange /v1/oauth/token, itself.
    api_root = os.environ[BASE_URL_ENV].rstrip("/")
    os.environ["ANTHROPIC_BASE_URL"] = api_root.removesuffix("/v1")

    existing = os.environ.get(CUSTOM_HEADERS_ENV, "")
    lines = [line for line in existing.splitlines() if line.strip()]
    lines.extend(_headers(run_id, agent))
    os.environ[CUSTOM_HEADERS_ENV] = "\n".join(lines)

    log.info("Model traffic routed through Otari at %s", os.environ[BASE_URL_ENV])
    return True
