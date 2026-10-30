# LookML Layer (working code, no Looker instance)

A LookML project that exposes every registry metric in Looker, built on
the dbt marts in `platforms/dbt`. There's no Looker instance behind this
demo, so the LookML isn't executed here. Instead, CI checks the structural
guarantees that keep it from becoming a second, ungoverned set of metric
definitions (see [Tests](#tests)).

## Files

| File | Contents |
|---|---|
| `bi_framework.model.lkml` | Connection, a `dbt_build` datagroup that refreshes caches when dbt adds new orders, and four explores |
| `views/fct_order_items.view.lkml` | Order-item fact: Net Revenue, Orders, Average Order Value, sliceable by channel, region, category, and order date |
| `views/dim_customers.view.lkml` | Customer-grain cohort metrics: 90-Day LTV, 90-Day Churn Rate, and the acquisition funnel (customer count by acquisition channel × purchase outcome) |
| `views/repeat_purchase.view.lkml` | Repeat Purchase Rate, filter-aware via templated filters (see below) |
| `views/channel_acquisition_cost.view.lkml` | Marketing spend, acquired customers, and CAC by channel |

## Design choices worth calling out

**Looker reads dbt, never raw tables.** Every view's `sql_table_name` and
derived-table SQL references the `analytics` schema dbt builds. Looker
inherits dbt's tests and the registry parity checks instead of re-deriving
joins of its own, and a test enforces it.

**Every governed measure is tagged to the registry.** Each measure that
implements a registry metric carries `tags: ["registry:<metric_id>"]`, and
its label and description come from the registry entry.

**Repeat purchase rate uses templated filters, not a plain measure.**
"Repeat buyer" has to be decided *after* filtering. A customer with two
orders overall but only one on `paid_social` is a one-time buyer when the
explore is filtered to `paid_social`. A measure on `fct_order_items` can't
express that, so `repeat_purchase` pushes the channel/region/category
filters into a derived table before counting orders per customer. That
matches the registry's filterable formula: filtered to `paid_social`, both
return 40.9% (versus 78.7% unfiltered).

**CAC keeps its inputs additive.** `channel_acquisition_cost` exposes spend
and acquired customers as separate `sum` measures and computes CAC as their
ratio. That's correct per channel and still correct when channels are
combined, and it aggregates both inputs to channel grain before joining,
the same fix applied to the registry's CAC formula.

**AOV is computed at order grain.** It's Net Revenue divided by distinct
orders, so multi-item orders aren't double counted.

## Tests

`tests/test_lookml_coverage.py` runs in CI:

1. Every registry metric has exactly one LookML measure tagged
   `registry:<metric_id>`, and no tag points at a metric that doesn't exist.
2. LookML reads only from the `analytics` schema, never from raw tables.
3. Each tagged measure's label matches the registry's metric name (uses
   the `lkml` parser: `pip install -r platforms/looker/requirements.txt`).

All five files parse cleanly with `lkml`. The measures' SQL was also
checked by hand-translating each measure into the query Looker would
generate and running it against the dbt tables. Net revenue, AOV, and
repeat purchase rate (each unfiltered and filtered by channel), LTV, churn,
the acquisition funnel, and CAC all match `resolve_metric()`.

## Pointing it at a real Looker instance

Looker doesn't support DuckDB as a connection dialect. To use this for
real, build the dbt project into a Looker-supported warehouse (Redshift,
Snowflake, BigQuery, Postgres), create a connection named
`bi_framework_warehouse`, and add these files to a LookML project. The
LookML SQL is standard ANSI; only the dbt models use DuckDB-specific
syntax (`interval 90 day`), and dbt handles that per adapter.

Natural next steps for a production setup: run the Looker content
validator and LookML validator in CI via the Looker API, and add
`access_grant`s if any metric needed row-level restrictions.
