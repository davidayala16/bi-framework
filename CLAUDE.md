# CLAUDE.md

Instructions for any Claude Code session working in this repo. Read this
before generating dashboard code, bot code, or anything that touches a
metric.

## What this repo is

A reference architecture for AI-augmented BI teams, built on a synthetic
DTC e-commerce dataset. See `docs/ARCHITECTURE.md` for the full picture.
The short version: `metrics/registry.yaml` is the only place a metric
formula is defined, and every platform reads it through
`metrics/resolver.py`.

## The one rule that matters

**Never write a metric formula inline.** If a dashboard, bot handler, or
script needs a number, it must come from `metrics.resolver.resolve_metric(
metric_id, filters)`. If the metric doesn't exist yet, add it to
`metrics/registry.yaml` first — with an `owner`, a `description`, and a
corresponding test in `tests/test_metrics_registry.py` referenced by
`verified_by` — before writing any code that uses it. See
`docs/METRICS_REGISTRY.md` for the full governance rationale.

## Before you're done with any change touching `metrics/`

1. Run `python data/generate_synthetic_data.py` if the warehouse doesn't
   exist yet or the generator changed.
2. Run `pytest tests/ -v`. All tests must pass — this is what
   `.github/workflows/verify-metrics.yml` enforces on every PR.
3. If you added or changed a metric, confirm `tests/test_metrics_registry.py`
   has a test pinning its actual output value, not just asserting it runs.

## Filters

Only `channel`, `region`, and `category` are valid filter columns (see
`ALLOWED_FILTER_COLUMNS` in `metrics/resolver.py`), and only for metrics
that declare them in `filterable_dimensions`. Cohort metrics (currently
`cac_by_channel`, `ltv_90d`, `churn_rate_90d`) declare
`filterable_dimensions: []` on purpose — don't add filter support to them
without first reading why in `docs/METRICS_REGISTRY.md`. Filter values are
always parameter-bound, never string-interpolated into SQL — keep it that
way even for what looks like a harmless internal demo value.

## Adding a new platform

Real, working platforms (currently Shiny and the Slack bot) live under
`platforms/<name>/` and import `metrics.resolver` — they contain no SQL of
their own. Documented-only adapters (Looker, Power BI, dbt) are a
`README.md` describing the mapping, not working code — that's deliberate,
see the note at the bottom of `docs/ARCHITECTURE.md`. Don't build a full
implementation for a fourth platform without checking with whoever's
driving the repo first; the pattern is already proven twice.

## Scope

This repo is a portfolio/reference-architecture demo. Keep additions
consistent with that: synthetic data only, no real company data or
metrics, no external service dependencies beyond what's already declared
in `requirements.txt`, and no infrastructure a recruiter cloning this
repo can't run locally in a few minutes.
