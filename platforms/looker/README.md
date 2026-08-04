# Looker Adapter (contract only — not implemented)

This folder is intentionally documentation-only. It shows how
`metrics/registry.yaml` would map onto Looker's semantic layer, without
building a full LookML project for a demo that has no real Looker instance
behind it.

## The mapping

Looker's unit of metric definition is a LookML `measure` inside a `view`.
Each entry in the registry maps like this:

| Registry field | LookML equivalent |
|---|---|
| `id` | measure name |
| `name` | `label:` |
| `description` | `description:` |
| `formula_sql` / `formula_sql_template` | `sql:` (DuckDB-specific syntax, e.g. `INTERVAL 90 DAY`, would need translating to the warehouse's SQL dialect) |
| `filterable_dimensions` | LookML dimensions the measure can be sliced by in an Explore |
| `owner` | a LookML `tag:` or governance metadata, surfaced via a content validator |

Example, hand-translated from `net_revenue` in the registry:

```lookml
view: fact_orders {
  sql_table_name: fact_orders ;;

  dimension: channel { type: string; sql: ${TABLE}.channel ;; }
  dimension: region  { type: string; sql: ${TABLE}.region ;; }
  dimension: category { type: string; sql: ${TABLE}.category ;; }

  measure: net_revenue {
    type: sum
    sql: ${TABLE}.revenue ;;
    label: "Net Revenue"
    description: "Total revenue recognized across all order line items."
    value_format_name: usd
  }
}
```

## What would make this real

1. A generation script that reads `metrics/registry.yaml` and emits LookML
   `measure` blocks — the same pattern as the CI verification step, just
   targeting LookML output instead of a pytest assertion.
2. A `content_validator` policy tying each measure back to its
   `verified_by` test, so a registry change that breaks the golden test
   also fails Looker CI (via the Looker API) before it ships.
3. Row-level `access_grant`s if any metric needed to be restricted by
   region/team — not needed for this synthetic dataset.

The point of keeping this to a contract: adding a *second* full platform
implementation wouldn't teach anything new about the architecture — the
registry-as-source-of-truth pattern is already proven by Shiny + the Slack
bot. This doc exists so the pattern's reach is legible without the extra
build cost.
