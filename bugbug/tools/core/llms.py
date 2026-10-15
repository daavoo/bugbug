# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os
from logging import INFO, basicConfig, getLogger

basicConfig(level=INFO)
logger = getLogger(__name__)


DEFAULT_OPENAI_MODEL = "gpt-5.6-sol"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"

# Setting OTARI_API_KEY routes every model create_llm() builds through an Otari
# gateway (https://github.com/mozilla-ai/otari): spend caps, cost per tool, and
# other providers, open-weight models included. OTARI_BASE_URL is a self-hosted
# gateway's API root (".../api/v1"); unset, it is otari.ai's.
OTARI_API_KEY_ENV = "OTARI_API_KEY"
OTARI_BASE_URL_ENV = "OTARI_BASE_URL"
OTARI_DEFAULT_BASE_URL = "https://api.otari.ai/api/v1"
OTARI_TAGS_HEADER = "Otari-Tags"


def _otari_selector(model: str) -> tuple[str, str]:
    """The Otari provider and selector for a model id.

    A bare id gets the provider init_chat_model would infer
    (``anthropic:claude-opus-5-5``); an id that names one already
    (``mistral:mistral-small-latest``) is kept as is.
    """
    if ":" in model:
        return model.split(":", 1)[0], model
    provider = "anthropic" if model.startswith("claude") else "openai"
    return provider, f"{provider}:{model}"


def create_llm(model: str, *, tool: str | None = None, **kwargs):
    """Build a LangChain chat model, through Otari when OTARI_API_KEY is set.

    Without the gateway this is ``init_chat_model(model, **kwargs)``. Through
    it, Claude models go to Otari's Anthropic-compatible Messages API, so
    Anthropic-only options such as ``thinking`` and ``effort`` keep their
    meaning; every other model goes through ``ChatOtari``. ``tool`` tags the
    requests so spend can be split per tool.
    """
    api_key = os.environ.get(OTARI_API_KEY_ENV)
    if not api_key:
        from langchain.chat_models import init_chat_model

        return init_chat_model(model, **kwargs)

    headers = {OTARI_TAGS_HEADER: f"app=bugbug,tool={tool}" if tool else "app=bugbug"}
    provider, selector = _otari_selector(model)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        base_url = os.environ.get(OTARI_BASE_URL_ENV) or OTARI_DEFAULT_BASE_URL
        return ChatAnthropic(
            model=selector,
            # The Anthropic SDK appends /v1/messages itself.
            base_url=base_url.rstrip("/").removesuffix("/v1"),
            api_key=api_key,
            default_headers=headers,
            **kwargs,
        )

    from langchain_otari import ChatOtari

    return ChatOtari(model=selector, default_headers=headers, **kwargs)


def get_tokenizer(model_name):
    import tiktoken

    try:
        return tiktoken.encoding_for_model(model_name)
    except KeyError:
        FALLBACK_ENCODING = "cl100k_base"
        logger.info(
            "Tokenizer couldn't be found for %s, falling back to %s",
            model_name,
            FALLBACK_ENCODING,
        )
        return tiktoken.get_encoding(FALLBACK_ENCODING)
