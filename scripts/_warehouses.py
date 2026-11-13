"""Connections to the optional cloud warehouses, shared by
scripts/load_synthetic_to_warehouse.py and the cross-warehouse parity tests.

Every credential comes from the same environment variables
platforms/dbt/profiles.yml reads (see .env.example), so the load script,
dbt, and the tests always talk to the same place. Drivers are imported
lazily: nothing here is needed for the default DuckDB path, and each cloud
driver is installed by its own platforms/dbt/requirements-<target>.txt.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

CLOUD_TARGETS = ("snowflake", "databricks", "redshift")
ANALYTICS_SCHEMA = "analytics"

REQUIRED_ENV = {
    "snowflake": [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_ROLE",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
    ],
    "databricks": ["DATABRICKS_HOST", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN"],
    "redshift": [
        "REDSHIFT_HOST",
        "REDSHIFT_USER",
        "REDSHIFT_PASSWORD",
        "REDSHIFT_DATABASE",
    ],
}

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class WarehouseConfigError(RuntimeError):
    pass


def identifier(value: str, what: str) -> str:
    """Schema/catalog names end up in DDL, where they can't be bound as
    parameters, so they're restricted to plain identifiers instead."""
    if not _IDENTIFIER.match(value):
        raise WarehouseConfigError(f"{what} must be a plain identifier, got {value!r}")
    return value


def raw_schema(target: str) -> str:
    """Same default as the dbt source: `main` on DuckDB, `raw` elsewhere."""
    default = "main" if target == "duckdb" else "raw"
    return identifier(os.environ.get("BI_FRAMEWORK_RAW_SCHEMA", default), "BI_FRAMEWORK_RAW_SCHEMA")


def databricks_catalog() -> str:
    return identifier(os.environ.get("DATABRICKS_CATALOG", "workspace"), "DATABRICKS_CATALOG")


def missing_env(target: str) -> list[str]:
    missing = [name for name in REQUIRED_ENV[target] if not os.environ.get(name)]
    if target == "snowflake" and not (
        os.environ.get("SNOWFLAKE_PASSWORD") or os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    ):
        missing.append("SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH")
    return missing


def _require_env(target: str) -> None:
    missing = missing_env(target)
    if missing:
        raise WarehouseConfigError(
            f"{target}: missing environment variables: {', '.join(missing)}. "
            "See .env.example."
        )


def connect(target: str, duckdb_path: str | None = None):
    """Open a DB-API connection to `target`.

    `duckdb` is accepted too (pointing at BI_FRAMEWORK_WAREHOUSE or
    `duckdb_path`) so the whole cross-warehouse path can be exercised
    locally, without credentials, against a second DuckDB file.
    """
    if target == "duckdb":
        import duckdb

        path = duckdb_path or os.environ.get(
            "BI_FRAMEWORK_WAREHOUSE", str(REPO_ROOT / "data" / "warehouse.duckdb")
        )
        return duckdb.connect(path)

    if target not in CLOUD_TARGETS:
        raise WarehouseConfigError(
            f"Unknown target {target!r}; expected one of duckdb, {', '.join(CLOUD_TARGETS)}"
        )
    _require_env(target)
    env = os.environ

    if target == "snowflake":
        import snowflake.connector

        auth: dict = {}
        if env.get("SNOWFLAKE_PRIVATE_KEY_PATH"):
            auth["private_key_file"] = env["SNOWFLAKE_PRIVATE_KEY_PATH"]
            if env.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
                auth["private_key_file_pwd"] = env["SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"]
        else:
            auth["password"] = env["SNOWFLAKE_PASSWORD"]
        return snowflake.connector.connect(
            account=env["SNOWFLAKE_ACCOUNT"],
            user=env["SNOWFLAKE_USER"],
            role=env["SNOWFLAKE_ROLE"],
            warehouse=env["SNOWFLAKE_WAREHOUSE"],
            database=env["SNOWFLAKE_DATABASE"],
            **auth,
        )

    if target == "databricks":
        from databricks import sql as databricks_sql

        return databricks_sql.connect(
            server_hostname=env["DATABRICKS_HOST"].removeprefix("https://").rstrip("/"),
            http_path=env["DATABRICKS_HTTP_PATH"],
            access_token=env["DATABRICKS_TOKEN"],
            catalog=databricks_catalog(),
            # Lets `PUT` upload the exported Parquet files to a volume.
            staging_allowed_local_path=str(REPO_ROOT / "data"),
        )

    import redshift_connector

    con = redshift_connector.connect(
        host=env["REDSHIFT_HOST"],
        port=int(env.get("REDSHIFT_PORT", "5439")),
        database=env["REDSHIFT_DATABASE"],
        user=env["REDSHIFT_USER"],
        password=env["REDSHIFT_PASSWORD"],
    )
    con.autocommit = True
    return con


def fetch_df(con, sql: str) -> pd.DataFrame:
    """Run a query and return a DataFrame with lower-cased column names
    (Snowflake reports unquoted identifiers in upper case)."""
    cur = con.cursor()
    try:
        cur.execute(sql)
        columns = [d[0].lower() for d in cur.description]
        rows = [tuple(r) for r in cur.fetchall()]
    finally:
        cur.close()
    return pd.DataFrame(rows, columns=columns)
