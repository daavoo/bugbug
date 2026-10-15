# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from bugbug.tools.core import llms


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (llms.OTARI_API_KEY_ENV, llms.OTARI_BASE_URL_ENV):
        monkeypatch.delenv(var, raising=False)
    # Neither provider key may leak into a gateway-bound model.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-real")


def test_without_otari_defers_to_init_chat_model(monkeypatch):
    import langchain.chat_models

    calls = []
    monkeypatch.setattr(
        langchain.chat_models,
        "init_chat_model",
        lambda model, **kwargs: calls.append((model, kwargs)) or "llm",
    )

    assert (
        llms.create_llm("claude-opus-5-5", tool="code_review", effort="high") == "llm"
    )
    assert calls == [("claude-opus-5-5", {"effort": "high"})]


def test_claude_goes_to_otari_messages_api(monkeypatch):
    pytest.importorskip("langchain_anthropic")
    monkeypatch.setenv(llms.OTARI_API_KEY_ENV, "tk-otari")
    monkeypatch.setenv(llms.OTARI_BASE_URL_ENV, "https://otari.example/api/v1/")

    llm = llms.create_llm(
        "claude-opus-5-5", tool="code_review", max_tokens=1000, effort="high"
    )

    assert type(llm).__name__ == "ChatAnthropic"
    assert llm.model == "anthropic:claude-opus-5-5"
    assert llm.anthropic_api_url == "https://otari.example/api"
    assert llm.anthropic_api_key.get_secret_value() == "tk-otari"
    assert llm.default_headers == {"Otari-Tags": "app=bugbug,tool=code_review"}
    assert llm.effort == "high"


def test_other_models_go_through_chat_otari(monkeypatch):
    pytest.importorskip("langchain_otari")
    monkeypatch.setenv(llms.OTARI_API_KEY_ENV, "tk-otari")
    monkeypatch.setenv(llms.OTARI_BASE_URL_ENV, "https://otari.example/api/v1")

    llm = llms.create_llm("gpt-5.6-sol", tool="comment_matching")

    assert type(llm).__name__ == "ChatOtari"
    assert llm.model_name == "openai:gpt-5.6-sol"
    assert llm.openai_api_base == "https://otari.example/api/v1"
    assert llm.openai_api_key.get_secret_value() == "tk-otari"
    assert llm.default_headers == {"Otari-Tags": "app=bugbug,tool=comment_matching"}


def test_a_named_provider_is_kept(monkeypatch):
    pytest.importorskip("langchain_otari")
    monkeypatch.setenv(llms.OTARI_API_KEY_ENV, "tk-otari")

    llm = llms.create_llm("mistral:mistral-small-latest")

    assert type(llm).__name__ == "ChatOtari"
    assert llm.model_name == "mistral:mistral-small-latest"
    assert llm.default_headers == {"Otari-Tags": "app=bugbug"}
