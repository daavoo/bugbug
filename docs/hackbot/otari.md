# Routing model traffic through Otari (optional)

[Otari](https://github.com/mozilla-ai/otari) is an Anthropic-compatible LLM gateway. Routing
runs through it gives the platform:

- **Spend caps that are enforced**, per agent (for example $3 a day), checked before each
  model call.
- **Cost per run and per agent**, recorded by the gateway from its own pricing, rather than
  the SDK's `total_cost_usd`, which assumes Claude prices for every model.
- **Other providers, open-weight models included**, picked per run with the `model` input
  every agent already takes. No agent code changes.
- **One trace per run** of every model call and tool call, across every `query()` and
  subagent the run makes.
- **Web search on any model.** Otari can answer Claude Code's `WebSearch` from its own
  search backend, so a run keeps searching when its model has no search of its own.

Everything here is opt-in. With no Otari settings, runs talk to Anthropic exactly as before.

## How it works

```
Cloud Run job ── Google identity token (anthropic_wif, unchanged) ──┐
                                                                    ▼
hackbot-runtime: ANTHROPIC_BASE_URL = Otari          Otari /api/v1/oauth/token
                 Otari-Conversation-Id: hackbot-<run_id>   (federation rule → key)
                 Otari-Tags: app=hackbot,agent=<agent>          │
                                                                ▼
Claude SDK/CLI ── /v1/messages ──▶ Otari ── budget, cost, trace ──▶ Anthropic,
                                                                    OpenAI, Mistral, ...
```

- **Authentication does not change.** Otari answers the same Workload Identity Federation
  exchange Anthropic does, so `anthropic_wif` keeps writing and refreshing the Google identity
  token, and the SDK trades it at Otari instead of at Anthropic. Hackbot holds no Otari key.
- **hackbot-runtime** ([hackbot_runtime/otari.py](../../libs/hackbot-runtime/hackbot_runtime/otari.py))
  sees `OTARI_BASE_URL`, points the SDK at the gateway, and adds the run and agent headers.
- **hackbot-api does not change.** Budgets and keys live in Otari, set up once per agent.

## Configuration

**Agent Job** (static env, per agent)

| Variable                            | Value                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------- |
| `OTARI_BASE_URL`                    | Gateway API root, `<origin>/api/v1`, as `langchain-otari` reads it.    |
| `ANTHROPIC_FEDERATION_RULE_ID`      | The Otari federation rule's `id`.                                      |
| `ANTHROPIC_ORGANIZATION_ID`         | The Otari organization's UUID.                                         |
| `ANTHROPIC_IDENTITY_TOKEN_AUDIENCE` | The audience the rule matches, for example `https://otari.example`.    |
| `OTARI_WEB_SEARCH`                  | Optional: `otari` runs every `WebSearch` on Otari's backend; `auto` only for models with no search of their own. |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL`     | Optional: on a non-Claude run, the model Claude Code uses for background calls and `WebSearch`. |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS`     | Optional: Otari holds the worst case of a call against the budget, so lower this when budgets are tight. |

The audience keeps a token minted for Otari from being one Anthropic would accept. Without
`ANTHROPIC_IDENTITY_TOKEN_AUDIENCE` the token is minted for `https://api.anthropic.com`.

**Otari** (once)

```yaml
federation_issuers: ["https://accounts.google.com"]
web_search_url: "http://searxng:8080"     # or web_search_provider: tavily | brave
providers:
  anthropic: {api_key: "${ANTHROPIC_API_KEY}"}
  openai: {api_key: "${OPENAI_API_KEY}", messages_api: responses}
  mistral: {api_key: "${MISTRAL_API_KEY}"}
aliases:
  # The bare ids agents pin, and Claude Code's background model.
  claude-opus-5-5: anthropic:claude-opus-5-5
  claude-haiku-4-5: anthropic:claude-haiku-4-5
```

Then, per agent: a user with a budget, a key for it with `reject_user_mismatch: false`
(Claude Code sends its own id in `metadata.user_id`), and a federation rule on the key naming
the agent's service account email and the audience above. Price Otari's search tool
(`otari:web_search`) when `require_pricing` is on, or its calls are refused with a 402.

## What was run

A small triage agent with build-repair's tool set (`Bash`, `WebSearch`, `WebFetch`), on the
real runtime, against a local Otari, signing in with a real Google identity token (from
`gcloud` instead of the metadata server):

| Run | Model | Search | Otari cost | SDK said |
| --- | ----- | ------ | ---------- | -------- |
| As today | `claude-haiku-4-5` | Anthropic's | $0.060 (+$0.01 search not billed, below) | $0.070 |
| Otari search | `claude-haiku-4-5` | Otari's | $0.016 | $0.016 |
| Open-weight | `mistral:mistral-small-latest` | Otari's | $0.061 | $0.285 |
| OpenAI | `openai:gpt-5-mini` (Responses API) | Otari's | $0.041 | $0.202 |
| Over budget | `claude-haiku-4-5` | | refused before the first call | |

## Known gaps

- **Anthropic's own web search is not billed by Otari.** Otari does not read
  `usage.server_tool_use.web_search_requests`, so a run that uses Claude's search costs $0.01
  a search more than Otari records.
- **A budget refusal reads as an authentication failure.** Otari answers it with a 403, which
  Claude Code reports as "Failed to authenticate".
- **Search providers.** Claude Code's `WebSearch` runs on Tavily, Brave or SearXNG through
  Otari. Exa is available on Otari's direct search endpoint only.
- **Non-Claude models lose Claude-only features**, such as prompt caching markers and beta
  features. Through the Responses API, OpenAI keeps reasoning across turns and caches
  prompts on its own.
- **Tracing stays in Weave.** Otari's trace holds no prompt or tool content.
