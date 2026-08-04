# Verification Layer

The premise of letting Claude act as a "mini analyst" across a shared repo
only works if drift gets caught before it ships. This repo's verification
layer has three parts, from cheapest to most expensive to bypass:

## 1. The registry itself is a guardrail, not just storage

`metrics/resolver.py` refuses to run a query that isn't in
`metrics/registry.yaml`, refuses filters on columns outside an allow-list
(`ALLOWED_FILTER_COLUMNS`), and refuses filters on dimensions a specific
metric doesn't declare support for. This means a Claude session generating
new dashboard or bot code structurally *can't* introduce an ad hoc
metric definition or an unvalidated filter — it can only call
`resolve_metric(id, filters)` and get back exactly what the registry says.
Filters are always parameter-bound (`?` placeholders passed to DuckDB),
never string-interpolated, so a typed filter value can't become a SQL
injection vector even though it originates from free text in the Slack
bot's filter prompt.

## 2. Golden-query regression tests

`tests/test_metrics_registry.py` runs every metric's formula against the
synthetic warehouse (built with a fixed random seed, so results are
reproducible) and asserts on the actual values — not just "did it run
without erroring." Changing a formula's logic changes its output, which
fails the pinned assertion, which is the point: a silent redefinition
gets caught immediately instead of shipping as a dashboard that quietly
shows a different number than it did yesterday.

`tests/test_metrics_registry.py::test_registry_is_well_formed` additionally
checks structural invariants — every metric has an owner, a description,
exactly one of `formula_sql`/`formula_sql_template`, and consistency
between `filterable_dimensions` and which formula field is used. This
catches the class of error where someone adds a new metric correctly in
spirit but misses a required field.

## 3. CI gate

`.github/workflows/verify-metrics.yml` runs the full suite on every PR
that touches `metrics/`, `data/generate_synthetic_data.py`, or `tests/`,
and on every push to `main`. A metric change that breaks its own test
can't merge. This is the actual enforcement mechanism — sections 1 and 2
are what make the gate meaningful; this is what makes it non-optional.

## What this doesn't cover (yet)

- **Semantic correctness beyond the pinned values.** The tests confirm a
  formula produces the same number it always has, not that the formula is
  *right*. That judgment call — is 90-day churn the correct churn window
  for this business — stays a human (analyst/manager) decision, encoded
  by writing the formula and its test in the first place.
- **Cross-platform consistency at runtime.** Shiny and the Slack bot both
  import the same `resolve_metric()`, so they can't drift by construction
  — but the Looker/Power BI/dbt adapters are documentation-only (see
  `platforms/*/README.md`), so nothing here actually verifies a real
  Looker measure matches the registry. Doing that for real would mean the
  generation-script approach sketched in those READMEs, with its own CI
  check.
