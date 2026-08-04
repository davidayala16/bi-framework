"""The one place that turns a registry entry + optional filters into a
DataFrame. Every platform (Shiny, Slack bot, future adapters) imports this
instead of writing its own SQL — that's the whole point of the registry
being the source of truth.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "metrics" / "registry.yaml"
WAREHOUSE_PATH = REPO_ROOT / "data" / "warehouse.duckdb"

ALLOWED_FILTER_COLUMNS = {"channel", "region", "category"}


class UnknownMetricError(ValueError):
    pass


class UnsupportedFilterError(ValueError):
    pass


def load_registry() -> dict:
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f)


def list_metrics(registry: dict | None = None) -> list[dict]:
    registry = registry or load_registry()
    return registry["metrics"]


def get_connection(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not WAREHOUSE_PATH.exists():
        raise FileNotFoundError(
            "data/warehouse.duckdb not found. Run "
            "`python data/generate_synthetic_data.py` first."
        )
    return duckdb.connect(str(WAREHOUSE_PATH), read_only=read_only)


def resolve_metric(
    metric_id: str,
    filters: dict[str, str] | None = None,
    registry: dict | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> pd.DataFrame:
    """Run a registry metric, optionally filtered, and return the result.

    Filters are always bound as query parameters (never string-interpolated
    into SQL) and validated against both an allow-list of columns and the
    metric's own declared filterable_dimensions.
    """
    registry = registry or load_registry()
    by_id = {m["id"]: m for m in registry["metrics"]}
    if metric_id not in by_id:
        raise UnknownMetricError(f"Unknown metric id: {metric_id!r}")
    metric = by_id[metric_id]

    owns_connection = con is None
    con = con or get_connection()
    try:
        if not metric["filterable_dimensions"]:
            if filters:
                raise UnsupportedFilterError(
                    f"{metric_id} does not support filters "
                    f"(filterable_dimensions is empty)"
                )
            return con.execute(metric["formula_sql"]).df()

        filters = filters or {}
        bad_columns = set(filters) - ALLOWED_FILTER_COLUMNS
        if bad_columns:
            raise UnsupportedFilterError(f"Unsupported filter columns: {bad_columns}")
        unsupported_for_metric = set(filters) - set(metric["filterable_dimensions"])
        if unsupported_for_metric:
            raise UnsupportedFilterError(
                f"{metric_id} does not support filtering on "
                f"{unsupported_for_metric}; supported: {metric['filterable_dimensions']}"
            )

        if filters:
            where = " AND ".join(f"{col} = ?" for col in filters)
            params = list(filters.values())
        else:
            where, params = "1=1", []

        sql = metric["formula_sql_template"].format(
            base_fact_sql=registry["base_fact_sql"], where=where
        )
        return con.execute(sql, params).df()
    finally:
        if owns_connection:
            con.close()


def distinct_values(column: str, con: duckdb.DuckDBPyConnection | None = None) -> list[str]:
    """Known values for a filterable dimension, used to populate dropdowns
    (Shiny) and validate typed input (Slack bot mock) instead of trusting
    free text straight into a query.
    """
    if column not in ALLOWED_FILTER_COLUMNS:
        raise UnsupportedFilterError(f"Unsupported filter column: {column}")
    table = {"channel": "orders", "region": "customers", "category": "products"}[column]
    owns_connection = con is None
    con = con or get_connection()
    try:
        rows = con.execute(f"SELECT DISTINCT {column} FROM {table} ORDER BY 1").fetchall()
        return [r[0] for r in rows]
    finally:
        if owns_connection:
            con.close()
