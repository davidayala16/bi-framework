# Power BI Layer (PBIP project)

A Power BI Project (`.pbip`) with a two-page dashboard over every registry
metric, built on the dbt marts in `platforms/dbt`. It's saved in Power BI's
text formats, TMDL for the semantic model and PBIR for the report, so every
measure and visual is a reviewable diff and CI can check it.

Like the LookML layer, it can't call `metrics.resolver`. DAX runs inside
Power BI's engine, which doesn't run in CI, so `tests/test_powerbi_coverage.py`
checks the structural guarantees that keep the measures tied to the
registry (see [Tests](#tests)).

## Open it

Power BI Desktop runs on Windows only.

```bash
# from the repo root, after the steps in the main README
dbt build --project-dir platforms/dbt --profiles-dir platforms/dbt
python platforms/powerbi/export_dbt_tables.py
```

1. Open `platforms/powerbi/BIFramework.pbip` in Power BI Desktop.
2. Go to **Transform data → Edit parameters** and set **DataFolder** to
   the folder the export script printed.
3. Click **Refresh**.

The report is saved in PBIR and the model in TMDL. Recent Desktop releases
open both by default. On an older release, turn on the preview features
for the PBIR report format and TMDL in **Options → Preview features**.

## The dashboard

| Page | Contents |
|---|---|
| **Revenue (filterable)** | Channel, region, and category slicers; cards for Net Revenue, Average Order Value, Repeat Purchase Rate, and Orders; Net Revenue by month and by category |
| **Cohorts (full window)** | Cards for 90-Day LTV, 90-Day Churn Rate, Customers, and Marketing Spend; CAC by channel; the acquisition funnel as a 100% stacked bar (outcome by acquisition channel) |

Colors come from `platforms/palette.py` (custom theme plus per-point
colors on the CAC and funnel charts), so a channel or outcome is the same
color here as in Shiny and the Slack bot.

## Files

| Path | Contents |
|---|---|
| `BIFramework.pbip` | Project file Power BI Desktop opens |
| `BIFramework.SemanticModel/definition/tables/*.tmdl` | Three import tables, one per dbt export, with the DAX measures |
| `BIFramework.SemanticModel/definition/expressions.tmdl` | The `DataFolder` parameter |
| `BIFramework.Report/definition/` | PBIR report: pages, visuals, theme reference |
| `BIFramework.Report/StaticResources/RegisteredResources/bi_framework_theme.json` | Theme built from the shared palette |
| `export_dbt_tables.py` | Writes the CSVs the model imports, from dbt's `analytics` schema only |

`data/` (the CSVs), `.pbi/localSettings.json`, and `.pbi/cache.abf` are
gitignored.

## Design choices worth calling out

**Power BI reads dbt exports, never raw tables.** Power BI Desktop has no
built-in DuckDB connector, so the model imports CSVs. Only
`export_dbt_tables.py` writes them, and it reads only `analytics.*`. The
model sees exactly the tables dbt tested and the parity tests checked
against the registry. On a warehouse Power BI can connect to, swap the
`Csv.Document` partitions for that connector over the same dbt tables.

**Every governed measure is annotated with its registry id.** Each DAX
measure that implements a registry metric carries
`annotation registry_id = <metric_id>`. Its name is the registry name and
its description is the registry description verbatim, which Power BI shows
as the field-list tooltip.

**Slicers can't reach cohort metrics.** The registry gives LTV, churn,
CAC, and the funnel `filterable_dimensions: []`. In the model, the tables
holding those measures (`dim_customers`, `marketing_spend`) have no
relationships at all, so no slicer filter can reach them. They also sit on
their own page with no slicers. Net revenue, AOV, and repeat purchase rate
live on `fct_order_items`, and the slicers filter only that table, on only
the registry's `ALLOWED_FILTER_COLUMNS`.

**Repeat purchase rate is decided per customer after slicing.** The
measure counts each customer's distinct orders within the current filter
context. A customer with two orders overall but one on `paid_social` is
a one-time buyer when sliced to `paid_social`, the same semantics as the
registry's filterable formula and the LookML `repeat_purchase` view.

**CAC keeps its inputs separate.** `Marketing Spend` and
`Acquired Customers` are aggregated independently, with acquired customers
matched to spend by channel through `TREATAS`, and only then divided. Spend
is never fanned out across customer rows, the same fix applied to the
registry formula.

**AOV is computed at order grain.** It's Net Revenue divided by distinct
orders, so multi-item orders aren't double counted.

## Tests

`tests/test_powerbi_coverage.py` runs in CI:

1. Every registry metric has exactly one measure annotated
   `registry_id = <metric_id>`, and no annotation points at a metric that
   doesn't exist.
2. Each annotated measure's name and description match the registry
   (`acquisition_funnel`'s measure is named `Customers`, as in LookML).
3. Each table imports only its own CSV from `DataFolder`, and the export
   script reads only from `analytics.*`.
4. Slicers use only `channel`/`region`/`category`, only on
   `fct_order_items`, and no relationship touches a cohort metric's table.
5. Every column and measure a report visual references exists in the
   model, as the right kind of object.
6. The exported CSV headers match the model's `sourceColumn`s, so a dbt
   schema change fails CI instead of breaking a refresh.

Separately, at build time:

- Every PBIR and project JSON file was validated against Microsoft's
  published schemas (`microsoft/json-schemas` on GitHub). CI doesn't
  repeat this check, since it would need network access.
- Each DAX measure's logic was hand-translated to the equivalent query
  over the exported CSVs and matched `resolve_metric()`. The checks covered
  net revenue, AOV, and repeat purchase rate unfiltered and under channel,
  region, category, and combined filters (for example, 40.9% repeat rate
  for `paid_social`), plus LTV, churn, CAC per channel, and the funnel.

What hasn't been checked: opening the project in Power BI Desktop. The
TMDL and PBIR were written by hand to the documented formats, not saved
from Desktop, so the first open is the real test. Desktop may rewrite some
files on first save.
