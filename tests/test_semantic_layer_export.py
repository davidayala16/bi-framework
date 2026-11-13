"""The exported semantic layer definitions must stay wired to the registry.

scripts/export_semantic_layer.py generates a Snowflake semantic view and
Databricks Unity Catalog metric views from metrics/registry.yaml plus the
`meta.semantic` mappings in the dbt project. There's no Snowflake or
Databricks account behind CI, so these tests can't create the views. They
check what can be checked without one:

  1. Coverage: every registry metric appears exactly once in the Snowflake
     semantic view and exactly once across the Databricks metric views,
     named after its registry id, and nothing else is exported as a metric.
  2. Freshness: the committed files are exactly what the generator
     produces now, so a registry change can't leave them stale.
  3. Value parity: every exported metric expression, run on DuckDB over the
     dbt mart it targets, equals resolve_metric() — unfiltered, and under
     every registry filter the mart can express as a dimension.
  4. The definitions read only the dbt-built `analytics` schema.

Like the dbt parity tests, the value checks need `dbt build` to have run.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest
import yaml

from metrics.resolver import distinct_values, load_registry, resolve_metric
from scripts import export_semantic_layer as export
from tests.test_dbt_parity import DBT_SCHEMA, _normalized, dbt_built  # noqa: F401

SNOWFLAKE_FILE = export.OUT_DIR / "snowflake" / f"{export.SNOWFLAKE_VIEW}.semantic_view.sql"
DATABRICKS_DIR = export.OUT_DIR / "databricks"

TABLES, METRICS = export.load_semantic_model()
REGISTRY = {m["id"]: m for m in load_registry()["metrics"]}


def _snowflake_metric_names() -> list[str]:
    ddl = SNOWFLAKE_FILE.read_text()
    block = ddl.split("  METRICS (\n", 1)[1].rsplit("\n  )\n", 1)[0]
    return re.findall(r"^    \w+\.(\w+) AS ", block, flags=re.MULTILINE)


def _databricks_specs() -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text())
        for path in sorted(DATABRICKS_DIR.glob("*.metric_view.yaml"))
    }


def test_generated_files_are_up_to_date():
    for path, text in export.render_all().items():
        assert path.exists(), f"{path.name} missing; run scripts/export_semantic_layer.py"
        assert path.read_text() == text, (
            f"{path.name} is stale; run python scripts/export_semantic_layer.py"
        )


def test_snowflake_semantic_view_covers_every_registry_metric():
    names = _snowflake_metric_names()
    assert sorted(names) == sorted(REGISTRY), (
        "Snowflake semantic view metrics != registry metrics"
    )


def test_databricks_metric_views_cover_every_registry_metric():
    names = [m["name"] for spec in _databricks_specs().values() for m in spec["measures"]]
    assert sorted(names) == sorted(REGISTRY), (
        "Databricks metric view measures != registry metrics"
    )


def test_databricks_ddl_embeds_each_yaml_verbatim():
    ddl = (DATABRICKS_DIR / "create_metric_views.sql").read_text()
    yaml_files = sorted(DATABRICKS_DIR.glob("*.metric_view.yaml"))
    assert ddl.count("WITH METRICS\nLANGUAGE YAML\nAS $$") == len(yaml_files)
    for path in yaml_files:
        assert path.read_text().rstrip("\n") in ddl, f"{path.name} not embedded in the DDL"


def test_exports_read_only_the_dbt_analytics_schema():
    snowflake_tables = re.findall(r"^    \w+ AS ([\w.]+)$", SNOWFLAKE_FILE.read_text(), re.MULTILINE)
    assert snowflake_tables and all(t.startswith(f"{DBT_SCHEMA}.") for t in snowflake_tables)
    for name, spec in _databricks_specs().items():
        assert spec["source"].split(".")[-2] == DBT_SCHEMA, f"{name} reads {spec['source']}"


def test_exported_metadata_comes_from_the_registry():
    ddl = SNOWFLAKE_FILE.read_text()
    for metric in METRICS:
        entry = REGISTRY[metric.id]
        assert metric.name == entry["name"] and metric.owner == entry["owner"]
        assert f"[registry:{metric.id}; owner: {entry['owner']}; unit: {entry['unit']}]" in ddl


def _semantic_result(con, metric: export.Metric, where: str = "", params: list | None = None):
    """Run the exported expression the way a semantic layer would: one
    aggregate over the mart, grouped by the metric's dimensions."""
    registry_columns = list(resolve_metric(metric.id, con=con).columns)
    value_column = next(c for c in registry_columns if c not in metric.group_by)
    select = [f"{column} AS {alias}" for alias, column in metric.group_by.items()]
    select.append(f"{metric.expr} AS {value_column}")
    sql = f"SELECT {', '.join(select)} FROM {DBT_SCHEMA}.{metric.table}"
    if where:
        sql += f" WHERE {where}"
    if metric.group_by:
        sql += " GROUP BY " + ", ".join(metric.group_by.values())
    return con.execute(sql, params or []).df()[registry_columns]


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.id)
def test_exported_expression_matches_registry(dbt_built, metric):
    expected = resolve_metric(metric.id, con=dbt_built)
    actual = _semantic_result(dbt_built, metric)
    pd.testing.assert_frame_equal(_normalized(actual), _normalized(expected), check_dtype=False)


def _filter_cases():
    for metric in METRICS:
        for dimension in REGISTRY[metric.id]["filterable_dimensions"]:
            if dimension in TABLES[metric.table].dimensions:
                yield pytest.param(metric, dimension, id=f"{metric.id}-by-{dimension}")


@pytest.mark.parametrize("metric,dimension", list(_filter_cases()))
def test_exported_expression_matches_registry_when_filtered(dbt_built, metric, dimension):
    """Slicing an exported metric by a dimension must give the same number
    as the registry's parameterized filter on that dimension."""
    for value in distinct_values(dimension, con=dbt_built):
        expected = resolve_metric(metric.id, filters={dimension: value}, con=dbt_built)
        actual = _semantic_result(dbt_built, metric, where=f"{dimension} = ?", params=[value])
        pd.testing.assert_frame_equal(
            actual, expected, check_dtype=False, obj=f"{metric.id} [{dimension}={value}]"
        )
