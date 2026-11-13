# Power BI Layer (working PBIP project, TMDL semantic model)

A Power BI Project (`.pbip`) that exposes every registry metric as a DAX
measure, built on the dbt marts in `platforms/dbt`. The semantic model is
stored as TMDL text instead of a binary `.pbix`, so each measure can be
diffed in a pull request and checked in CI the same way the LookML layer
is (see [Tests](#tests)).

<!-- TODO(screenshot): open BIFramework.pbip in Power BI Desktop, confirm it
     loads and refreshes, add a visual or two, and save a screenshot to
     docs/assets/powerbi_model.png. Then uncomment the image below and
     delete the "Status" note.

![Power BI semantic model](../../docs/assets/powerbi_model.png)
-->

> **Status:** the project files were written by hand against Microsoft's
> sample PBIP project and published JSON schemas, and CI verifies their
> structure. They have not been opened in Power BI Desktop yet. See
> [What CI can't check](#what-ci-cant-check).

## Files

| Path | Contents |
|---|---|
| `BIFramework.pbip` | The file you open in Power BI Desktop; points at the report folder |
| `BIFramework.SemanticModel/definition/tables/fct_order_items.tmdl` | Order-item fact: Net Revenue, Average Order Value, Repeat Purchase Rate; sliceable by channel, region, category |
| `…/tables/fct_orders.tmdl`, `dim_customers.tmdl` | Order-grain and customer-grain marts, for slicing and drill-down |
| `…/tables/metric_cac_by_channel.tmdl`, `metric_ltv_90d.tmdl`, `metric_churn_rate_90d.tmdl`, `metric_acquisition_funnel.tmdl` | dbt's precomputed cohort metrics, one measure each |
| `…/definition/relationships.tmdl` | `fct_order_items` → `fct_orders` → `dim_customers` |
| `…/definition/expressions.tmdl` | The `WarehousePath` parameter |
| `…/definition/model.tmdl`, `database.tmdl` | Model settings and the table list |
| `BIFramework.Report/` | A minimal report (one empty page) bound to the model, in the PBIR format |
| `export_csv.py` | CSV export of the same tables, for machines without the ODBC driver |

## The mapping

| Registry field | Power BI equivalent |
|---|---|
| `id` | `annotation registry_id = <id>` on the measure |
| `name` | the measure's name |
| `description` | the measure's description (`///` in TMDL; the field-list tooltip in Desktop) |
| `unit` | `formatString` (see below) |
| `category` | `displayFolder` |
| `owner` | `annotation registry_owner = <owner>` |
| `filterable_dimensions` | non-empty: a DAX measure on `fct_order_items` that responds to slicers. Empty: a measure over a disconnected dbt metric table that slicers can't reach |
| `formula_sql` / `formula_sql_template` | DAX for the three filterable metrics; dbt's `metric_*` table for the four cohort metrics |

| Registry metric | Measure | Lives on | Implementation |
|---|---|---|---|
| `net_revenue` | Net Revenue | `fct_order_items` | DAX: sum of line revenue |
| `aov` | Average Order Value | `fct_order_items` | DAX: Net Revenue over distinct orders |
| `repeat_purchase_rate` | Repeat Purchase Rate | `fct_order_items` | DAX: orders counted per customer inside the filter context |
| `cac_by_channel` | Customer Acquisition Cost by Channel | `metric_cac_by_channel` | reads dbt |
| `ltv_90d` | 90-Day Customer Lifetime Value | `metric_ltv_90d` | reads dbt |
| `churn_rate_90d` | 90-Day Churn Rate | `metric_churn_rate_90d` | reads dbt |
| `acquisition_funnel` | Acquisition Funnel by Channel | `metric_acquisition_funnel` | reads dbt |

The registry has no format-string field, so `formatString` is derived from
`unit`: `USD` → `\$#,0.00`, `percent` → `0.0\%`, `count` → `#,0`. Percent
metrics stay on the registry's 0–100 scale (78.7, not 0.787), which is why
the percent sign is escaped: DAX's bare `%` would multiply by 100 again.

## Why TMDL

A `.pbix` is a binary archive: a changed measure shows up in a pull request
as "binary file differs". With PBIP, the model is a folder of TMDL files,
one per table, and a measure is a few lines of text:

```
	/// Net revenue divided by the number of distinct orders. Computed at the order grain, …
	measure 'Average Order Value' =
			DIVIDE([Net Revenue], DISTINCTCOUNT(fct_order_items[order_id]))
		formatString: \$#,0.00
		displayFolder: Revenue

		annotation registry_id = aov
```

That makes two things possible that weren't with `.pbix`:

- **Diffable.** A reviewer sees exactly which measure changed and how.
- **Testable.** CI parses the files and fails the build if a measure loses
  its link to the registry.

## Design choices worth calling out

**Power BI reads dbt, never raw tables.** Every table's query is a plain
column list from `analytics.<table>`. Joins and business logic stay in dbt,
where they're tested, and a test enforces it.

**Cohort metrics read dbt's answer instead of re-deriving it.** The
registry marks `cac_by_channel`, `ltv_90d`, `churn_rate_90d`, and
`acquisition_funnel` as not filterable: their logic depends on first-order
dates and a dataset-wide as-of date, which a slicer on order rows would
quietly break. Re-implementing them in DAX would create a second definition
that CI can't evaluate. Instead each one is a measure over its
`metric_*` table, which `tests/test_dbt_parity.py` already pins to the
registry. Those tables have no relationships on purpose, so no slicer can
reach them and Power BI shows the number the resolver returns.

**CAC has no total.** `Customer Acquisition Cost by Channel` is blank
unless exactly one channel is in context. It's a ratio at channel grain,
and the dbt table doesn't carry its inputs, so there is no correct way to
combine channels. Put `metric_cac_by_channel[channel]` on the axis.

**Repeat purchase rate is decided after filtering.** A customer with two
orders overall but one on `paid_social` is a one-time buyer when sliced to
`paid_social`. The measure counts orders per customer inside the current
filter context, matching the registry's filterable formula.

**The filterable measures are the one place logic is restated.** Net
Revenue, AOV, and Repeat Purchase Rate have to be DAX to respond to
slicers. They're kept to what `fct_order_items` already provides; anything
more involved belongs in dbt.

**No implicit measures.** Every column is `summarizeBy: none` and the model
sets `discourageImplicitMeasures`, so a number reaches a visual through a
governed measure, not by dragging a column and letting Power BI sum it.

## Tests

`tests/test_powerbi_coverage.py` runs in CI on every pull request that
touches `platforms/powerbi/**`:

1. Every registry metric has exactly one measure annotated with its
   `registry_id`; no annotation points at a metric that doesn't exist; no
   two measures claim the same metric.
2. Each measure's name, description, owner, display folder, and format
   string match its registry entry.
3. Non-filterable metrics read only their `metric_<id>` table, and those
   tables have no relationships.
4. The model reads only the `analytics` schema. Each table's query is run
   against the DuckDB warehouse and must return exactly the columns and
   types the TMDL declares.
5. Every TMDL file parses, `model.tmdl` lists every table, relationships
   join existing key columns, and DAX references only tables, columns, and
   measures that exist.

There's no maintained Python library for TMDL (Microsoft's parser is the
.NET TOM library), so the tests use a small parser in
`tests/tmdl_parser.py`, with its own unit tests in
`tests/test_tmdl_parser.py`.

### What CI can't check

Power BI Desktop is Windows-only and there is no DAX engine in CI, so:

- **DAX is not evaluated.** The tests prove each measure is wired to the
  right registry entry and the right columns, not that it returns the
  registry's number. For the four cohort metrics the number comes straight
  from a dbt table that *is* value-checked. For the three DAX measures,
  compare against `resolve_metric()` by hand after opening the project
  (unfiltered: Net Revenue, AOV, Repeat Purchase Rate; then again sliced to
  one channel).
- **Loading in Desktop is not exercised.** The JSON files validate against
  Microsoft's published schemas and the TMDL follows Microsoft's sample
  project, but only Desktop can confirm it opens and refreshes.

## Opening it in Power BI Desktop

Requires Windows and a recent Power BI Desktop. If Desktop doesn't offer
to open `.pbip` files, enable **File → Options and settings → Options →
Preview features → Power BI Project (.pbip) save option** and restart.

1. Build the warehouse (from the repo root):

   ```bash
   python data/generate_synthetic_data.py
   ```

   ```bash
   dbt build --project-dir platforms/dbt --profiles-dir platforms/dbt
   ```

2. Install the [DuckDB ODBC driver](https://duckdb.org/docs/stable/clients/odbc/windows)
   for Windows: download the release zip from
   [duckdb/duckdb-odbc](https://github.com/duckdb/duckdb-odbc/releases),
   extract it, and run `odbc_install.exe`. It registers a driver named
   `DuckDB Driver`, which is the name the model's connection string uses.
   Use a driver at least as new as the `duckdb` Python package that built
   the warehouse, or it won't be able to read the file.

3. Open `platforms/powerbi/BIFramework.pbip`.

4. Point the model at your clone: **Transform data → Edit parameters**, and
   set `WarehousePath` to the absolute path of `data\warehouse.duckdb`.

5. Refresh. Desktop will ask two things the first time:
   - credentials for the ODBC source: choose **Default or Custom** and
     leave the fields empty;
   - permission to run a native database query, once per table: the
     queries are the `select … from analytics.<table>` statements in the
     TMDL files.

The model connects with `access_mode=read_only`, so a refresh never
modifies the warehouse.

**Alternative connector.** MotherDuck's
[DuckDB Power Query connector](https://github.com/motherduckdb/duckdb-power-query-connector)
wraps the same ODBC driver and adds a "DuckDB" entry to Get Data
(`DuckDB.Contents`). It's a custom connector, so it needs the `.mez` file
in `Documents\Power BI Desktop\Custom Connectors` and Desktop's data
extension security lowered to allow uncertified connectors. The model here
uses plain `Odbc.Query` so that only the driver is required.

### Without ODBC

If you can't install the driver, export the same tables to CSV:

```bash
python platforms/powerbi/export_csv.py
```

That writes `platforms/powerbi/export/<table>.csv` (git-ignored). Then, for
each table, open **Transform data → Advanced Editor** and replace the
`Source` step, keeping the `Typed` step but pointing it at `Promoted`:

```powerquery
let
    Source = Csv.Document(
        File.Contents("C:\path\to\bi-framework\platforms\powerbi\export\fct_orders.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, { /* unchanged */ })
in
    Typed
```

Don't commit that change: the coverage tests expect every table to read
`analytics.<table>` from the warehouse.

## Working with the files

- Saving from Desktop rewrites the TMDL. Expect a first-save diff: Desktop
  adds its own annotations (for example `PBIDesktopVersion`) and may
  reorder properties. Review it like any other change; the tests tell you
  if a registry link was lost.
- Explanations live in `///` descriptions (which Desktop shows as tooltips
  and writes back on save) and in `--` comments inside DAX. Free-standing
  `//` comments aren't used, and the parser rejects them.
- Indentation is tabs, one per level, as Desktop writes it.
- `.pbi/localSettings.json` and `.pbi/cache.abf` are per-user and
  git-ignored. The cache holds imported data, so it must not be committed.

## Changing a metric

1. Change it in `metrics/registry.yaml` and its dbt model first (see the
   root `CLAUDE.md`).
2. If its name, description, unit, owner, or category changed, update the
   measure to match; the tests name the measure that drifted.
3. If it's one of the three DAX measures and the formula changed, update
   the DAX and re-check it against `resolve_metric()` in Desktop.
4. For a new metric, add a measure with `annotation registry_id`. If the
   metric isn't filterable, add a table for its `metric_<id>` dbt model
   (and a `ref table` line in `model.tmdl`) and read from that.
