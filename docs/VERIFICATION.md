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

## 4. Cross-layer parity (dbt and LookML)

dbt and LookML don't import `resolve_metric()`, so they can't be governed
by construction the way Shiny and the Slack bot are. They're governed by
tests instead:

- `tests/test_dbt_parity.py` checks that every registry metric has a dbt
  model, that dbt's `fct_order_items` is row-for-row identical to
  `base_fact_sql`, and that every `metric_*` table equals the resolver's
  output. A plausible-looking dbt change, such as AOV at line-item grain,
  passes dbt's own tests and fails here.
- `tests/test_lookml_coverage.py` checks that every registry metric has
  exactly one tagged LookML measure with a matching label, and that
  LookML reads only from dbt-built tables.

## What this doesn't cover (yet)

- **Semantic correctness beyond the pinned values.** The tests confirm a
  formula produces the same number it always has, not that the formula is
  *right*. That judgment call — is 90-day churn the correct churn window
  for this business — stays a human (analyst/manager) decision, encoded
  by writing the formula and its test in the first place.
- **Pinned values that only check shape.** A test that asserts a
  metric's *shape* (positive values, the right channel is largest) can
  pass while the formula is wrong. `cac_by_channel` once fanned spend out
  across customer rows and returned total channel spend as "CAC"; its test
  only checked that paid_social was the highest, so it passed. Pin actual
  values.
- **LookML at runtime.** The LookML coverage tests are structural. Nothing
  here executes a Looker query, since there's no Looker instance; doing
  that for real means running the Looker content validator in CI via the
  Looker API.
