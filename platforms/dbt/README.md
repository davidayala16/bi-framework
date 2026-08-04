# dbt Adapter (contract only — not implemented)

Documentation-only. dbt is a slightly different fit than Looker/Power BI —
it's not a presentation layer, it's the transformation layer that would sit
*underneath* the registry rather than beside it. Worth spelling out because
it's the most likely next real step for this architecture.

## The mapping

| Registry concept | dbt equivalent |
|---|---|
| `base_fact_sql` | a dbt model, e.g. `models/marts/fact_orders.sql`, materialized as a table/view the warehouse builds once instead of every query re-deriving it |
| Each metric's `formula_sql` / `formula_sql_template` | either a downstream dbt model (`models/marts/metrics/net_revenue.sql`) or, if using dbt's Semantic Layer / MetricFlow, a `metrics:` YAML block referencing `fact_orders` |
| `filterable_dimensions` | dimensions exposed on the semantic model for MetricFlow query filtering |
| `verified_by` | a dbt test (`tests/` or a singular test) instead of a pytest function — same governance idea, native to the tool |

Sketch using dbt's MetricFlow semantic layer syntax:

```yaml
semantic_models:
  - name: fact_orders
    model: ref('fact_orders')
    dimensions:
      - name: channel
        type: categorical
      - name: region
        type: categorical
    measures:
      - name: revenue
        agg: sum
        expr: revenue

metrics:
  - name: net_revenue
    type: simple
    type_params:
      measure: revenue
```

## Why this matters more than the other two adapters

If this architecture ever became a real internal platform (the "private
playbook" version), `base_fact_sql` becoming an actual dbt model — built
once, tested with dbt's own test framework, and referenced by every
downstream metric — is the natural next step past a registry file that
each platform re-executes independently. Flagging that here so the
docs don't imply the YAML-registry approach is the end state; it's the
right amount of structure for a demo repo, not necessarily for a
production warehouse with real query volume.
