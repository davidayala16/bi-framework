"""Credential-free checks on the warehouse-portability plumbing.

CI only ever runs DuckDB, so it can't prove the dbt project builds on
Snowflake, Databricks, or Redshift; that's what the opt-in `test_cloud_*`
tests in test_dbt_parity.py are for. What CI *can* hold in place is
everything around those runs:

  1. platforms/dbt/profiles.yml keeps DuckDB as the default target and
     reads every cloud credential from env_var(), so no secret can be
     committed there.
  2. The dbt models contain no DuckDB-only date arithmetic.
  3. The load script plans a load of every raw table for every target, and
     its export -> load path reproduces the raw tables exactly (exercised
     against a throwaway DuckDB file standing in for a cloud warehouse).
  4. The result normalisation the cloud parity tests rely on treats the
     value shapes cloud drivers return (upper-case columns, Decimal,
     datetime.date) as equal to DuckDB's.
"""

from __future__ import annotations

import datetime
import decimal
import re
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

from scripts import _warehouses
from scripts import load_synthetic_to_warehouse as loader
from tests.test_dbt_parity import _assert_cloud_matches

REPO_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = REPO_ROOT / "platforms" / "dbt"
PROFILES = DBT_DIR / "profiles.yml"

CREDENTIAL_KEYS = {
    "account", "user", "password", "private_key_path", "private_key_passphrase",
    "role", "warehouse", "database", "host", "http_path", "token", "dbname",
}


def _outputs() -> dict:
    return yaml.safe_load(PROFILES.read_text())["bi_framework"]["outputs"]


def test_duckdb_is_the_default_target():
    profile = yaml.safe_load(PROFILES.read_text())["bi_framework"]
    assert profile["outputs"][profile["target"]]["type"] == "duckdb"


@pytest.mark.parametrize("target", _warehouses.CLOUD_TARGETS)
def test_cloud_profile_reads_every_credential_from_env(target):
    output = _outputs()[target]
    assert output["type"] == target
    assert output["schema"] == _warehouses.ANALYTICS_SCHEMA
    for key in CREDENTIAL_KEYS & set(output):
        assert "env_var(" in str(output[key]), (
            f"profiles.yml {target}.{key} must come from env_var(), "
            f"not a literal value"
        )


@pytest.mark.parametrize("target", _warehouses.CLOUD_TARGETS)
def test_profile_and_python_agree_on_env_var_names(target):
    """dbt, the load script, and the cloud parity tests must read the same
    variables, or they would silently point at different warehouses."""
    in_profile = set(re.findall(r"env_var\('([A-Z_]+)'", str(_outputs()[target])))
    assert set(_warehouses.REQUIRED_ENV[target]) <= in_profile


def test_models_have_no_duckdb_only_date_math():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for folder in ("models", "tests", "macros")
        for path in (DBT_DIR / folder).rglob("*.sql")
        if re.search(r"\binterval\s+\d+\s+day\b|\bdate_diff\s*\(|\bqualify\b|::", path.read_text(), re.I)
    ]
    assert not offenders, f"DuckDB-specific SQL in dbt project: {offenders}"


@pytest.mark.parametrize("target", _warehouses.CLOUD_TARGETS)
def test_load_plan_covers_every_raw_table(target):
    sources = yaml.safe_load((DBT_DIR / "models" / "staging" / "_sources.yml").read_text())
    dbt_raw_tables = {t["name"] for t in sources["sources"][0]["tables"]}
    assert set(loader.TABLES) == dbt_raw_tables
    sql = "\n".join(loader.plan(target, "raw"))
    for table in dbt_raw_tables:
        assert re.search(rf"\braw\.{table}\b", sql), f"{target} plan never creates raw.{table}"


def test_export_and_load_reproduce_the_raw_tables(tmp_path, warehouse):
    """Export -> Parquet -> load, into a throwaway DuckDB file. The same
    code path the cloud targets use, minus the cloud."""
    target_db = tmp_path / "standin.duckdb"
    loader.load("duckdb", "raw", duckdb_path=str(target_db))
    con = duckdb.connect(str(target_db), read_only=True)
    try:
        for table, columns in loader.TABLES.items():
            order = ", ".join(str(i + 1) for i in range(len(columns)))
            loaded = con.execute(f"SELECT * FROM raw.{table} ORDER BY {order}").df()
            original = warehouse.execute(f"SELECT * FROM {table} ORDER BY {order}").df()
            pd.testing.assert_frame_equal(loaded, original, check_dtype=False)
            assert [c for c, _ in columns] == list(original.columns)
    finally:
        con.close()


def test_cloud_comparison_ignores_driver_value_shapes():
    duckdb_side = pd.DataFrame(
        {
            "order_date": pd.to_datetime(["2024-01-05", "2024-02-01"]),
            "channel": ["email", "direct"],
            "quantity": [1, 2],
            "revenue": [10.5, 20.25],
        }
    )
    cloud_side = pd.DataFrame(
        {
            "ORDER_DATE": [datetime.date(2024, 2, 1), datetime.date(2024, 1, 5)],
            "CHANNEL": ["direct", "email"],
            "QUANTITY": [decimal.Decimal(2), decimal.Decimal(1)],
            "REVENUE": [decimal.Decimal("20.25"), 10.5 + 1e-12],
        }
    )
    _assert_cloud_matches(cloud_side, duckdb_side, "driver shapes")

    wrong = cloud_side.copy()
    wrong.loc[0, "REVENUE"] = decimal.Decimal("20.26")
    with pytest.raises(AssertionError):
        _assert_cloud_matches(wrong, duckdb_side, "driver shapes")
