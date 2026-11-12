# Architecture

## The core idea

One repo is the shared substrate for a BI team's metrics, templates, and
platform code — and human analysts and AI agent sessions (Claude, or
anything else — see [Agent-agnostic by construction](#agent-agnostic-by-construction))
work against it the same way, through the same registry, under the same
tests.

```mermaid
flowchart TD
    subgraph Source of truth
        REG["metrics/registry.yaml<br/>(formulas, owners, filterable dims)"]
        DATA["data/generate_synthetic_data.py<br/>(synthetic DTC warehouse)"]
    end

    RES["metrics/resolver.py<br/>(the only thing that runs a formula)"]

    REG --> RES
    DATA --> RES

    RES --> SHINY["platforms/shiny<br/>(working dashboard)"]
    RES --> SLACK["platforms/slack-bot<br/>(working local mock)"]
    RES -.contract only.-> PBI["platforms/powerbi"]

    DBT["platforms/dbt<br/>(staging → marts → metric models)"]
    LOOKER["platforms/looker<br/>(LookML on dbt marts)"]
    DATA --> DBT --> LOOKER

    TESTS["tests/<br/>golden-query, dbt parity, LookML coverage"]
    CI[".github/workflows/verify-metrics.yml"]
    REG --> TESTS --> CI
    DBT -.checked against registry.-> TESTS
    LOOKER -.checked against registry.-> TESTS

    ANALYST["Analyst + AI agent session<br/>(isolated via git worktree)"]
    ANALYST -- edits --> REG
    ANALYST -- PR --> CI
    CI -- merge --> REG
```

## Why the registry sits *between* the agent and every platform

The failure mode this architecture exists to prevent: five agent sessions
(Claude, ChatGPT, Copilot — or five human analysts), each asked to "add a
churn chart," each inventing a slightly different churn definition inline
in whatever dashboard/bot code they're writing. The fix isn't a better
prompt — it's making the correct path structurally easier than the wrong
one. `metrics/resolver.py` doesn't expose a way to run arbitrary SQL; it
only exposes `resolve_metric(id, filters)` against
`metrics/registry.yaml`. Generating new dashboard code means calling that
function, not writing a new formula. This holds regardless of who or what
is generating the code, which is the whole point.

## Why the agent reads an instructions file first

The root `CLAUDE.md` is the explicit instruction set this repo ships for
Claude Code: where the registry lives, that it's authoritative, and what
"done" looks like (new metric → registry entry + test, not a number
computed inline). Without it, a fresh session has no way to know this
convention exists — it would just write working code, correctly, that
happens to bypass the one rule that matters. `CLAUDE.md` is what turns "an
agent that writes correct SQL" into "an agent that participates in this
team's governance model."

## Agent-agnostic by construction

Nothing about the mechanism above is Claude-specific, and that's
deliberate — a BI team can't bet its governance model on every analyst
standardizing on one vendor's tool. Separate the two layers and it's
obvious:

- **The enforcement layer** — `metrics/resolver.py`, the golden-query
  tests, the CI gate — is plain Python, YAML, and pytest. It has no
  concept of "Claude." It rejects a bad change the same way whether a
  human, Claude, ChatGPT, Cursor, or Copilot produced it. This layer is
  *why* the governance holds, and it has zero AI dependency — an analyst
  hand-writing SQL against `metrics.resolver.resolve_metric()` gets
  exactly the same guarantees an agent does.
- **The instruction layer** — `CLAUDE.md` — is the one piece that's
  tool-specific, because Claude Code specifically looks for that exact
  filename. It's not special content, though: it's this repo's instance
  of a pattern most agent tooling now supports in some form (a root
  instructions file, an `AGENTS.md`, a `.cursorrules`, a Copilot
  custom-instructions file, or a pasted system prompt for a tool with no
  native mechanism). Point a different agent at this repo with an
  equivalent instructions file and the same rule applies, because the
  instructions layer only ever does one job: tell the agent the
  enforcement layer exists and that it's not optional.

The practical implication: this repo's core bet isn't "use Claude." It's
"put the governance in code and tests, not in a prompt or in trust," which
is a bet that pays off identically whether the team standardizes on one
agent, several, or none at all.

## Warehouse-agnostic by construction

The same argument applies one layer down. The governance model shouldn't
depend on which warehouse a team runs, so the dbt project is written to
build unchanged on DuckDB, Snowflake, Databricks, and Redshift:

- **Models contain no dialect-specific SQL.** The few places engines
  disagree (date arithmetic, 64-bit float type names, boolean
  expressions) go through dbt's cross-database macros or small
  adapter-dispatched macros in `platforms/dbt/macros/`.
- **The warehouse is a `--target`.** `platforms/dbt/profiles.yml` has one
  output per warehouse. Every credential is an `env_var()`; nothing
  secret is in the repo.
- **The registry stays the single definition.** Its formula SQL is DuckDB
  dialect and is only ever run on DuckDB. On a cloud warehouse, dbt's
  output is compared against the resolver's DuckDB results on the same
  seeded synthetic data, so there's still exactly one place a metric is
  defined, and the cloud build is checked against it rather than against
  a translated copy.

What CI does and doesn't verify, stated plainly:

- **CI verifies DuckDB only**, with no credentials: the full `dbt build`,
  registry parity, and the portability plumbing (no literal credentials in
  `profiles.yml`, no DuckDB-only SQL in the models, and the load script's
  export-and-load path, exercised against a second DuckDB file).
- **CI does not run Snowflake, Databricks, or Redshift.** Those targets
  are verified by hand: load the synthetic data, `dbt build --target
  <name>`, then `DBT_PARITY_TARGET=<name> pytest tests/test_dbt_parity.py`.
  Until someone does that against a live account, the claim for that
  warehouse is "compiles against the real adapter and parses in its
  dialect," not "runs."

See `platforms/dbt/README.md#run-on-a-cloud-warehouse`.

## What's real vs. what's a contract

- **Real, tested, running:** the registry, the resolver, the synthetic
  data generator, the Shiny app, the Slack bot mock, the dbt project, the
  pytest suite, the CI workflow.
- **Real code, run by hand:** the Snowflake, Databricks, and Redshift dbt
  targets, the warehouse load script, and the cross-warehouse parity
  tests. They need your own credentials, so CI skips them (see above).
- **Real code, structurally tested:** the LookML layer. There's no Looker
  instance behind the demo, so CI verifies coverage, labels, and that
  LookML reads only dbt tables rather than running Looker queries (see
  `platforms/looker/README.md`).
- **Documented but not built:** the Power BI adapter. dbt and Looker were
  built because they test something new: whether the registry can govern
  a transformation layer and a semantic layer that don't import the
  resolver at all. A third BI tool would prove the same point again.

## How this scales past a demo

`docs/WORKTREE_WORKFLOW.md` covers running multiple agent sessions on one
analyst's machine in parallel. `docs/VERIFICATION.md` covers what actually
stops a bad change from shipping. `docs/METRICS_REGISTRY.md` covers the
governance rule itself. Together those three, plus this diagram, are the
whole architecture — everything else in the repo is one instance of it
applied to a synthetic e-commerce business.
