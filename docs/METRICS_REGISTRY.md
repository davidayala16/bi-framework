# Metric Governance

`metrics/registry.yaml` is the single place a metric formula is allowed to
be defined in this repo. Every platform (Shiny, the Slack bot, and the
documented Looker/Power BI/dbt adapters) reads from it through
`metrics/resolver.py` rather than writing its own SQL. This document is
the "why," not the schema — the schema is documented inline at the top of
the registry file itself.

## The rule this repo is built to enforce

**Nobody — human or Claude — redefines a metric inline in a dashboard, a
bot handler, or an ad hoc query.** If a number needs to exist, it either
already has an entry in the registry, or someone adds one (with an owner,
a description, and a test) before any platform code references it.

This is the actual point of the whole architecture. Without it, "Claude as
a mini analyst" degrades fast: ask five different sessions to build five
different dashboards, and without a shared registry each one quietly
invents its own version of "active customer" or "churn." The registry
isn't a nice-to-have doc — it's the thing that keeps five parallel Claude
sessions (or five human analysts) from producing five incompatible
numbers for the same name.

## Ownership

Every metric has an `owner` field — a team or role, not a person, since
the point is that the definition survives personnel changes. In a real
deployment this maps to who has merge rights on changes to that metric's
block in the registry (via `CODEOWNERS`, not shown here since this repo
has one contributor).

## Filterable vs. cohort metrics

Metrics fall into two shapes, and the registry is explicit about which:

- **Filterable** (`net_revenue`, `aov`, `repeat_purchase_rate`): built on
  a shared `base_fact_sql`, sliceable by any of `channel`, `region`,
  `category` via a parameterized `{where}` clause.
- **Cohort** (`cac_by_channel`, `ltv_90d`, `churn_rate_90d`):
  `filterable_dimensions: []`. Their logic depends on cross-time joins
  (first order date, last order date, spend-by-channel) that don't
  compose with a simple row-level filter. The registry says so explicitly
  rather than silently ignoring a filter someone tries to apply — see
  `metrics/resolver.py`'s `UnsupportedFilterError`.

That distinction is deliberate and worth calling out to anyone reading
this repo: not everything is naively sliceable, and pretending otherwise
is how BI teams end up with a dashboard filter that quietly produces a
wrong number instead of an error.

## Changing a metric definition

1. Edit the block in `metrics/registry.yaml`.
2. Update or add the corresponding test in `tests/test_metrics_registry.py`
   (the `verified_by` field should point at it).
3. Run `pytest tests/` locally — this is exactly what
   `.github/workflows/verify-metrics.yml` runs on every PR touching
   `metrics/`.
4. If the change affects what a dashboard/bot displays, no platform code
   needs to change — that's the test that the registry is actually being
   used as the source of truth, not just documentation everyone ignores.
