"""Parity tests: the dbt layer must agree with the registry.

metrics/registry.yaml stays the definition of record. platforms/dbt builds
the same metrics as warehouse tables, and these tests fail if the two ever
disagree, so a dbt model can't quietly drift from the definition analysts,
dashboards, and AI agents resolve through metrics.resolver.

What's checked:
  1. Coverage: every registry metric has a dbt model (linked by
     `meta.registry_id` in platforms/dbt/models/metrics/_metrics.yml), and
     every dbt metric model points at a real registry metric.
  2. Fact parity: dbt's fct_order_items is row-for-row identical to the
     registry's base_fact_sql, so filtered metrics and LookML measures built
     on it slice exactly the rows the resolver does.
  3. Metric parity: each dbt metric table equals resolve_metric() output.

Requires `dbt build` to have run (see platforms/dbt/README.md). Locally the
value checks skip if the dbt tables don't exist yet; in CI, REQUIRE_DBT=1
turns that skip into a failure.

Cross-warehouse parity (optional, never run in CI)
--------------------------------------------------
The same dbt project also builds on Snowflake, Databricks, and Redshift.
Set DBT_PARITY_TARGET to one of those (plus that warehouse's credentials,
see .env.example) after loading the synthetic data and running
`dbt build --target <name>`, and the `test_cloud_*` tests below compare
what dbt built *there* against the registry.

The registry's formula SQL is DuckDB dialect, so it is never sent to the
cloud warehouse. The expected values are always the resolver's results on
the local DuckDB warehouse; both sides are built from the same seeded
synthetic data, so they have to match. Without DBT_PARITY_TARGET these
tests skip, which is what keeps CI credential-free.
"""

from __future__ import annotations

import decimal
import os
from pathlib import Path

import pandas as pd
import pytest
import yaml

from metrics.resolver import load_registry, resolve_metric
from scripts import _warehouses

REPO_ROOT = Path(__file__).resolve().parents[1]
DBT_METRICS_YML = REPO_ROOT / "platforms" / "dbt" / "models" / "metrics" / "_metrics.yml"
DBT_SCHEMA = "analytics"


def _dbt_metric_models() -> dict[str, str]:
    """registry_id -> dbt model name, from the dbt project's own metadata."""
    spec = yaml.safe_load(DBT_METRICS_YML.read_text())
    return {m["meta"]["registry_id"]: m["name"] for m in spec["models"]}


@pytest.fixture(scope="module")
def dbt_built(warehouse):
    exists = warehouse.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = 'fct_order_items'",
        [DBT_SCHEMA],
    ).fetchone()[0]
    if not exists:
        message = (
            "dbt models not built. Run: dbt build --project-dir platforms/dbt "
            "--profiles-dir platforms/dbt"
        )
        if os.environ.get("REQUIRE_DBT") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return warehouse


def _normalized(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(list(df.columns)).reset_index(drop=True)


def test_every_registry_metric_has_a_dbt_model():
    registry_ids = {m["id"] for m in load_registry()["metrics"]}
    dbt_ids = set(_dbt_metric_models())
    assert registry_ids - dbt_ids == set(), "registry metrics with no dbt model"
    assert dbt_ids - registry_ids == set(), "dbt metric models with no registry entry"


def test_fct_order_items_matches_base_fact_sql(dbt_built):
    registry = load_registry()
    expected = dbt_built.execute(
        f"SELECT * FROM ({registry['base_fact_sql']}) ORDER BY order_item_id"
    ).df()
    actual = dbt_built.execute(
        f"SELECT * FROM {DBT_SCHEMA}.fct_order_items ORDER BY order_item_id"
    ).df()
    pd.testing.assert_frame_equal(
        actual[expected.columns], expected, check_dtype=False
    )


@pytest.mark.parametrize("metric_id", sorted(_dbt_metric_models()))
def test_dbt_metric_matches_registry(dbt_built, metric_id):
    model = _dbt_metric_models()[metric_id]
    expected = resolve_metric(metric_id, con=dbt_built)
    actual = dbt_built.execute(f"SELECT * FROM {DBT_SCHEMA}.{model}").df()
    assert list(actual.columns) == list(expected.columns), (
        f"{model} columns {list(actual.columns)} != registry output "
        f"{list(expected.columns)}"
    )
    pd.testing.assert_frame_equal(
        _normalized(actual), _normalized(expected), check_dtype=False
    )


# --- Cross-warehouse parity: opt-in, skipped unless DBT_PARITY_TARGET is set ---

# Float sums can differ in the last bits between engines (summation order),
# so cloud results are compared to DuckDB's within this absolute tolerance
# rather than bit-for-bit. Every metric is rounded to at most 2 decimals, so
# anything that is actually a different number is far outside it.
CLOUD_ABS_TOLERANCE = 1e-6


@pytest.fixture(scope="module")
def cloud_dbt():
    """A connection to the warehouse named by DBT_PARITY_TARGET, once its
    dbt models are confirmed to exist. Skips when the variable is unset;
    a set-but-broken configuration is an error, not a skip."""
    target = os.environ.get("DBT_PARITY_TARGET", "").strip().lower()
    if not target:
        pytest.skip(
            "DBT_PARITY_TARGET not set; cross-warehouse parity is opt-in "
            "(see platforms/dbt/README.md)"
        )
    try:
        con = _warehouses.connect(target)
    except _warehouses.WarehouseConfigError as exc:
        pytest.fail(str(exc))
    try:
        _warehouses.fetch_df(con, f"SELECT 1 AS ok FROM {_cloud_table(target, 'fct_order_items')} WHERE 1 = 0")
    except Exception as exc:  # driver-specific "table not found" errors
        con.close()
        pytest.fail(
            f"{target}: {DBT_SCHEMA}.fct_order_items not readable ({exc}). Run "
            f"scripts/load_synthetic_to_warehouse.py --target {target}, then "
            f"dbt build --target {target}."
        )
    yield target, con
    con.close()


def _cloud_table(target: str, table: str) -> str:
    if target == "databricks":
        return f"{_warehouses.databricks_catalog()}.{DBT_SCHEMA}.{table}"
    return f"{DBT_SCHEMA}.{table}"


def _portable(df: pd.DataFrame) -> pd.DataFrame:
    """Reduce a result to warehouse-neutral values: lower-case column names,
    dates as ISO strings, every number as float (drivers hand back Decimal,
    int, or numpy types for the same value)."""
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        if pd.api.types.is_bool_dtype(series) or (
            len(non_null) and all(isinstance(v, bool) for v in non_null)
        ):
            out[col.lower()] = series.astype(object)
        elif pd.api.types.is_datetime64_any_dtype(series):
            out[col.lower()] = series.dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_numeric_dtype(series):
            out[col.lower()] = series.astype(float)
        elif len(non_null) and all(hasattr(v, "isoformat") for v in non_null):
            out[col.lower()] = series.map(lambda v: v.isoformat()[:10] if v is not None else None)
        elif len(non_null) and all(
            isinstance(v, (int, float, decimal.Decimal)) for v in non_null
        ):
            out[col.lower()] = series.astype(float)
        else:
            out[col.lower()] = series.astype(object)
    return out


def _assert_cloud_matches(actual: pd.DataFrame, expected: pd.DataFrame, what: str):
    actual, expected = _portable(actual), _portable(expected)
    assert list(actual.columns) == list(expected.columns), (
        f"{what} columns {list(actual.columns)} != registry output {list(expected.columns)}"
    )
    pd.testing.assert_frame_equal(
        _normalized(actual),
        _normalized(expected),
        check_dtype=False,
        check_exact=False,
        rtol=0,
        atol=CLOUD_ABS_TOLERANCE,
        obj=what,
    )


def test_cloud_fct_order_items_matches_base_fact_sql(cloud_dbt, warehouse):
    target, con = cloud_dbt
    expected = warehouse.execute(load_registry()["base_fact_sql"]).df()
    actual = _warehouses.fetch_df(con, f"SELECT * FROM {_cloud_table(target, 'fct_order_items')}")
    _assert_cloud_matches(
        actual[[c for c in expected.columns if c in actual.columns]],
        expected,
        f"{target} fct_order_items",
    )


@pytest.mark.parametrize("metric_id", sorted(_dbt_metric_models()))
def test_cloud_dbt_metric_matches_registry(cloud_dbt, warehouse, metric_id):
    target, con = cloud_dbt
    model = _dbt_metric_models()[metric_id]
    expected = resolve_metric(metric_id, con=warehouse)
    actual = _warehouses.fetch_df(con, f"SELECT * FROM {_cloud_table(target, model)}")
    _assert_cloud_matches(actual, expected, f"{target} {model}")
