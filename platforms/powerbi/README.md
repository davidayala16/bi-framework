# Power BI Adapter (contract only — not implemented)

Documentation-only, same reasoning as `platforms/looker/README.md`: shows
the mapping without shipping a `.pbix` file that would just be a translated
copy of the Shiny app with no new architectural signal.

## The mapping

Power BI's equivalent of the registry is a DAX measure inside the semantic
model (either import mode or DirectQuery over the warehouse).

| Registry field | Power BI equivalent |
|---|---|
| `id` | measure name in the model |
| `name` | Display Name |
| `description` | Description (shown in the field list tooltip) |
| `formula_sql` / `formula_sql_template` | translated to DAX, or left as a SQL view the model queries via DirectQuery so the DuckDB SQL stays canonical |
| `filterable_dimensions` | columns marked as usable in slicers / cross-filtering |
| `owner` | a model-level annotation, or tracked in the workspace's metadata catalog |

Example, hand-translated from `aov`:

```dax
Average Order Value =
DIVIDE(
    SUMX(
        SUMMARIZE(fact_orders, fact_orders[order_id], "order_total", SUM(fact_orders[revenue])),
        [order_total]
    ),
    DISTINCTCOUNT(fact_orders[order_id])
)
```

## What would make this real

1. Prefer DirectQuery against a view that mirrors `base_fact_sql` from the
   registry, rather than hand-porting each formula to DAX — keeps one
   fewer place a definition can drift.
2. A scheduled job diffing the DAX measure text against the registry's
   `formula_sql` (structurally, not byte-for-byte, since DAX and SQL will
   never be identical) as a lightweight drift check, analogous to
   `tests/test_metrics_registry.py`.
3. Row-level security roles if metrics needed to be scoped by
   region/team — not needed here.

Same rationale as the Looker doc: this repo already proves the pattern
twice (Shiny, Slack bot). A third full build wouldn't add signal, so this
stays a contract.
