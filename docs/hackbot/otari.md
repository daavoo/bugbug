# Routing model traffic through Otari (optional)

[Otari](https://github.com/mozilla-ai/otari) is an Anthropic-compatible LLM gateway. Routing
runs through it gives the platform four things it does not have today:

- **Spend caps that are enforced**, per agent (for example $200 a day) and per run, instead of
  a run count kept in memory.
- **Cost per run, per agent and per requester**, recorded by the gateway rather than added up
  by each agent from `total_cost_usd`.
- **Other providers, open-weight models included**, behind the model ids agents already pin,
  with no change to agent code.
- **One trace per run** of every model call, across every `query()` and subagent the run
  makes.

Everything here is opt-in. With no Otari settings, runs talk to Anthropic exactly as before.

## How it works

```
hackbot-api ── mint key (user hackbot-<agent>, expires with the job,
   │            optional per-run budget) ──> Otari
   │
   └─ env overrides: OTARI_BASE_URL, OTARI_API_KEY ──> agent container
                                                          │
         hackbot-runtime points the Claude SDK at Otari ──┘
         (ANTHROPIC_BASE_URL, bearer key, Otari-Conversation-Id: hackbot-<run_id>)

finalize ── read the run's spend into runs.llm_cost_usd, revoke the key ──> Otari
```

- **hackbot-api** ([app/otari.py](../../services/hackbot-api/app/otari.py)) mints one key per
  run, beside the signed upload policy. The key belongs to an Otari user named for the agent
  (`hackbot-<agent>`), so the budget on that user caps the agent across all its runs. When
  `OTARI_RUN_BUDGET_ID` is set, a scoped budget on the key also caps the run on its own. The
  key expires at the job timeout plus the grace window. At finalize the API reads the run's
  spend into `runs.llm_cost_usd`, exposed on `RunDoc`, and revokes the key.
- **hackbot-runtime** ([hackbot_runtime/otari.py](../../libs/hackbot-runtime/hackbot_runtime/otari.py))
  sees `OTARI_BASE_URL` and points the Claude SDK and CLI at the gateway. It replaces any real
  Anthropic key in the environment with the run key, so that key never reaches the gateway, and
  adds `Otari-Conversation-Id: hackbot-<run_id>` to every request.

## Configuration

**hackbot-api**

| Variable                | Meaning                                                             |
| ----------------------- | ------------------------------------------------------------------- |
| `OTARI_URL`             | Gateway origin. Unset disables everything below.                    |
| `OTARI_MASTER_KEY`      | Operator credential for minting and revoking keys (Secret Manager). |
| `OTARI_AGENT_BUDGET_ID` | Budget given to each agent's Otari user when it is first created.   |
| `OTARI_RUN_BUDGET_ID`   | Budget capping each run on its own.                                 |
| `OTARI_WEB_SEARCH`      | `auto`, `otari` or `provider`, passed to runs as below.             |

**Agent container** (set per run by hackbot-api; set them by hand for a local run)

| Variable           | Meaning                                                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `OTARI_BASE_URL`   | Gateway origin.                                                                                                          |
| `OTARI_API_KEY`    | The run's key.                                                                                                           |
| `OTARI_WEB_SEARCH` | Optional. Sends `Otari-Web-Search`, so Claude Code's WebSearch is run by Otari on a model that has no search of its own. |

Gateway routing and Anthropic WIF are mutually exclusive: a run with both
`OTARI_BASE_URL` and `ANTHROPIC_FEDERATION_RULE_ID` fails before the agent starts.

**Model ids.** Agents pin bare ids such as `claude-opus-5-5`. Give each one an alias in the
gateway's config so it resolves, and point the alias at another provider to swap the model
without touching the agent:

```yaml
aliases:
  claude-opus-5-5: anthropic:claude-opus-5-5
  # An open-weight model behind a name an agent can be run with (MODEL=open-weight).
  open-weight: mistral:mistral-small-latest
```

Claude Code also makes background calls on its default small model. Alias that id too, or
set `ANTHROPIC_DEFAULT_HAIKU_MODEL` on the Job.

## Running it locally

1. Start Otari against Postgres with the aliases above, and create the budgets:

   ```sh
   curl -X POST $OTARI/api/v1/budgets -H "Authorization: Bearer $MASTER" \
     -d '{"name": "hackbot-agent-daily", "max_budget": 5, "reset_alignment": "calendar_day"}'
   curl -X POST $OTARI/api/v1/budgets -H "Authorization: Bearer $MASTER" \
     -d '{"name": "hackbot-per-run", "max_budget": 0.5}'
   ```

2. Mint a run key (hackbot-api does this for deployed runs) and pass it to the agent's
   compose service with `OTARI_BASE_URL` and `OTARI_API_KEY`. Leave `ANTHROPIC_API_KEY` out
   of the agent's environment.

3. Read the run's cost and trace from Otari: `GET /api/v1/usage/summary?api_key_id=<id>` and
   `GET /api/v1/traces`.

## Trade-offs

- **The gateway holds the Anthropic key.** WIF keeps every long-lived model credential out of
  the platform; with Otari, the gateway holds one. The agent container still holds nothing
  long-lived: the run key is capped, expires with the job and is revoked at finalize. Like the
  upload policy, it is visible in the execution's env overrides.
- **Tracing stays in Weave.** Otari's per-run trace covers model calls only. Exporting
  Claude Code's OpenTelemetry to Otari as well would count each call's cost twice, so it is
  not wired.
- **MCP stays in the broker.** Otari calls MCP servers but does not serve one, so the
  broker's per-run, loopback MCP servers remain the way agents reach Bugzilla and Phabricator.
- **Non-Claude models lose Claude-only features.** On a model Otari bridges from another
  provider, prompt caching, extended thinking and beta features may not carry over.
