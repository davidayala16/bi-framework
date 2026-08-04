# Architecture

## The core idea

One repo is the shared substrate for a BI team's metrics, templates, and
platform code — and both human analysts and Claude sessions work against
it the same way, through the same registry, under the same tests.

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
    RES -.contract only.-> LOOKER["platforms/looker"]
    RES -.contract only.-> PBI["platforms/powerbi"]
    RES -.contract only.-> DBT["platforms/dbt"]

    TESTS["tests/test_metrics_registry.py<br/>golden-query regression tests"]
    CI[".github/workflows/verify-metrics.yml"]
    REG --> TESTS --> CI

    ANALYST["Analyst + Claude session<br/>(isolated via git worktree)"]
    ANALYST -- edits --> REG
    ANALYST -- PR --> CI
    CI -- merge --> REG
```

## Why the registry sits *between* Claude and every platform

The failure mode this architecture exists to prevent: five Claude sessions
(or five analysts), each asked to "add a churn chart," each inventing a
slightly different churn definition inline in whatever dashboard/bot code
they're writing. The fix isn't a better prompt — it's making the correct
path structurally easier than the wrong one. `metrics/resolver.py` doesn't
expose a way to run arbitrary SQL; it only exposes `resolve_metric(id,
filters)` against `metrics/registry.yaml`. Generating new dashboard code
means calling that function, not writing a new formula.

## Why Claude reads `CLAUDE.md` first

The root `CLAUDE.md` is the explicit instruction set: where the registry
lives, that it's authoritative, and what "done" looks like (new metric →
registry entry + test, not a number computed inline). Without it, a fresh
Claude session has no way to know this convention exists — it would just
write working code, correctly, that happens to bypass the one rule that
matters. `CLAUDE.md` is what turns "Claude that writes correct SQL" into
"Claude that participates in this team's governance model."

## What's real vs. what's a contract

- **Real, tested, running:** the registry, the resolver, the synthetic
  data generator, the Shiny app, the Slack bot mock, the pytest suite, the
  CI workflow.
- **Documented but not built:** Looker, Power BI, and dbt adapters (see
  their READMEs under `platforms/`). Building all of them would prove the
  same point three more times at three times the cost — the docs exist so
  the pattern's reach is legible without that cost.

## How this scales past a demo

`docs/WORKTREE_WORKFLOW.md` covers running multiple Claude sessions on one
analyst's machine in parallel. `docs/VERIFICATION.md` covers what actually
stops a bad change from shipping. `docs/METRICS_REGISTRY.md` covers the
governance rule itself. Together those three, plus this diagram, are the
whole architecture — everything else in the repo is one instance of it
applied to a synthetic e-commerce business.
