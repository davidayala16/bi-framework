"""Load the synthetic raw tables into a cloud warehouse, so
`dbt build --target <snowflake|databricks|redshift>` has data to build on.

    python data/generate_synthetic_data.py            # if data/synthetic/ is missing
    python scripts/load_synthetic_to_warehouse.py --target snowflake
    dbt build --project-dir platforms/dbt --profiles-dir platforms/dbt --target snowflake

What it does:
  1. Exports data/synthetic/*.csv to explicitly typed Parquet files under
     data/synthetic/parquet/ (gitignored). Types are pinned here rather
     than inferred, so every warehouse gets the same columns DuckDB has.
  2. Recreates the five raw tables in the target's raw schema (`raw` by
     default; BI_FRAMEWORK_RAW_SCHEMA overrides it, and dbt reads the same
     variable) and bulk-loads the Parquet files:
       snowflake   PUT to each table's stage, then COPY INTO
       databricks  PUT to a Unity Catalog volume, then CTAS over read_files()
       redshift    upload to S3 and COPY, if REDSHIFT_S3_BUCKET and
                   REDSHIFT_IAM_ROLE are set; otherwise batched INSERTs
                   (fine at this size: ~9k rows in total)
       duckdb      read_parquet() into another DuckDB file; a credential-free
                   way to exercise the same path (see --duckdb-path)
  3. Checks every loaded table's row count against the export.

Credentials come from the environment variables in .env.example; nothing
is read from or written to the repo. `--dry-run` prints the SQL without
connecting to anything.

This script only moves raw data. It contains no metric logic: metrics are
still defined in metrics/registry.yaml and built by dbt.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import _warehouses as wh  # noqa: E402

SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"
PARQUET_DIR = SYNTHETIC_DIR / "parquet"

# The raw tables, with logical column types. These mirror what DuckDB
# infers from the CSVs in data/generate_synthetic_data.py.
TABLES: dict[str, list[tuple[str, str]]] = {
    "products": [
        ("product_id", "bigint"),
        ("product_name", "string"),
        ("category", "string"),
        ("unit_cost", "double"),
        ("unit_price", "double"),
    ],
    "customers": [
        ("customer_id", "bigint"),
        ("signup_date", "date"),
        ("acquisition_channel", "string"),
        ("region", "string"),
    ],
    "orders": [
        ("order_id", "bigint"),
        ("customer_id", "bigint"),
        ("order_date", "date"),
        ("channel", "string"),
    ],
    "order_items": [
        ("order_item_id", "bigint"),
        ("order_id", "bigint"),
        ("product_id", "bigint"),
        ("quantity", "bigint"),
        ("unit_price", "double"),
    ],
    "marketing_spend": [
        ("month", "string"),  # 'YYYY-MM', deliberately not a date
        ("channel", "string"),
        ("spend", "double"),
    ],
}

TYPE_NAMES = {
    "duckdb": {"bigint": "BIGINT", "double": "DOUBLE", "string": "VARCHAR", "date": "DATE"},
    "snowflake": {"bigint": "BIGINT", "double": "FLOAT", "string": "VARCHAR", "date": "DATE"},
    "databricks": {"bigint": "BIGINT", "double": "DOUBLE", "string": "STRING", "date": "DATE"},
    "redshift": {
        "bigint": "BIGINT",
        "double": "DOUBLE PRECISION",
        "string": "VARCHAR(256)",
        "date": "DATE",
    },
}

INSERT_BATCH_ROWS = 500


def export_parquet() -> dict[str, int]:
    """CSV -> typed Parquet. Returns the row count of each table."""
    missing = [t for t in TABLES if not (SYNTHETIC_DIR / f"{t}.csv").exists()]
    if missing:
        sys.exit(
            f"Missing data/synthetic/{missing[0]}.csv. Run "
            "`python data/generate_synthetic_data.py` first."
        )
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    con = duckdb.connect()
    try:
        for table, columns in TABLES.items():
            select = ", ".join(
                f'CAST("{col}" AS {TYPE_NAMES["duckdb"][kind]}) AS "{col}"' for col, kind in columns
            )
            source = (SYNTHETIC_DIR / f"{table}.csv").as_posix()
            target = (PARQUET_DIR / f"{table}.parquet").as_posix()
            con.execute(
                f"COPY (SELECT {select} FROM read_csv('{source}', header = true, "
                f"all_varchar = true)) TO '{target}' (FORMAT PARQUET)"
            )
            counts[table] = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{target}')"
            ).fetchone()[0]
    finally:
        con.close()
    return counts


def _ddl(target: str, columns: list[tuple[str, str]]) -> str:
    cols = ", ".join(f"{col} {TYPE_NAMES[target][kind]}" for col, kind in columns)
    return f"({cols})"


def plan(target: str, schema: str) -> list[str]:
    """The SQL each target runs, in order. Redshift's data movement (S3
    upload or INSERT batches) isn't plain SQL and is handled in
    `_load_redshift`."""
    statements: list[str] = []
    if target == "snowflake":
        statements.append(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for table, columns in TABLES.items():
            name = f"{schema}.{table}"
            path = (PARQUET_DIR / f"{table}.parquet").as_posix()
            statements += [
                f"CREATE OR REPLACE TABLE {name} {_ddl(target, columns)}",
                f"PUT 'file://{path}' @{schema}.%{table} AUTO_COMPRESS = FALSE OVERWRITE = TRUE",
                f"COPY INTO {name} FROM @{schema}.%{table} "
                "FILE_FORMAT = (TYPE = PARQUET) "
                "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE PURGE = TRUE",
            ]
    elif target == "databricks":
        catalog = wh.databricks_catalog()
        volume = f"/Volumes/{catalog}/{schema}/synthetic_stage"
        statements += [
            f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}",
            f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.synthetic_stage",
        ]
        for table, columns in TABLES.items():
            path = (PARQUET_DIR / f"{table}.parquet").as_posix()
            select = ", ".join(
                f"CAST({col} AS {TYPE_NAMES[target][kind]}) AS {col}" for col, kind in columns
            )
            statements += [
                f"PUT '{path}' INTO '{volume}/{table}.parquet' OVERWRITE",
                f"CREATE OR REPLACE TABLE {catalog}.{schema}.{table} AS "
                f"SELECT {select} FROM read_files('{volume}/{table}.parquet', format => 'parquet')",
            ]
    elif target == "redshift":
        statements.append(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for table, columns in TABLES.items():
            name = f"{schema}.{table}"
            statements += [
                f"DROP TABLE IF EXISTS {name} CASCADE",
                f"CREATE TABLE {name} {_ddl(target, columns)}",
            ]
    elif target == "duckdb":
        statements.append(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for table in TABLES:
            path = (PARQUET_DIR / f"{table}.parquet").as_posix()
            statements.append(
                f"CREATE OR REPLACE TABLE {schema}.{table} AS "
                f"SELECT * FROM read_parquet('{path}')"
            )
    else:
        raise wh.WarehouseConfigError(f"Unknown target {target!r}")
    return statements


def _redshift_s3_settings() -> tuple[str, str, str] | None:
    bucket, role = os.environ.get("REDSHIFT_S3_BUCKET"), os.environ.get("REDSHIFT_IAM_ROLE")
    if not (bucket and role):
        return None
    prefix = os.environ.get("REDSHIFT_S3_PREFIX", "bi-framework/synthetic").strip("/")
    return bucket, prefix, role


def _load_redshift(con, schema: str, dry_run: bool) -> None:
    """Fill the (already created) Redshift tables."""
    s3 = _redshift_s3_settings()
    cur = None if dry_run else con.cursor()
    for table, columns in TABLES.items():
        name = f"{schema}.{table}"
        path = PARQUET_DIR / f"{table}.parquet"
        if s3:
            bucket, prefix, role = s3
            key = f"{prefix}/{table}.parquet"
            copy = (
                f"COPY {name} FROM 's3://{bucket}/{key}' "
                f"IAM_ROLE '{role}' FORMAT AS PARQUET"
            )
            print(f"  upload {path.name} -> s3://{bucket}/{key}")
            print(f"  {copy}")
            if not dry_run:
                import boto3

                boto3.client("s3").upload_file(str(path), bucket, key)
                cur.execute(copy)
            continue

        local = duckdb.connect()
        try:
            rows = local.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()
        finally:
            local.close()
        row_sql = "(" + ", ".join(["%s"] * len(columns)) + ")"
        print(
            f"  INSERT INTO {name} VALUES ... "
            f"({len(rows)} rows, {INSERT_BATCH_ROWS} per statement)"
        )
        if dry_run:
            continue
        for start in range(0, len(rows), INSERT_BATCH_ROWS):
            batch = rows[start : start + INSERT_BATCH_ROWS]
            # Values are bound as parameters, never formatted into the SQL.
            cur.execute(
                f"INSERT INTO {name} VALUES " + ", ".join([row_sql] * len(batch)),
                [value for row in batch for value in row],
            )
    if cur is not None:
        cur.close()


def _qualified(target: str, schema: str, table: str) -> str:
    if target == "databricks":
        return f"{wh.databricks_catalog()}.{schema}.{table}"
    return f"{schema}.{table}"


def load(target: str, schema: str, dry_run: bool = False, duckdb_path: str | None = None) -> None:
    counts = export_parquet()
    print(f"Exported {len(counts)} tables to {PARQUET_DIR.relative_to(REPO_ROOT)}/ as Parquet")

    statements = plan(target, schema)
    if dry_run:
        print(f"-- dry run: SQL for target {target!r}, schema {schema!r}")
        for statement in statements:
            print(f"  {statement};")
        if target == "redshift":
            _load_redshift(None, schema, dry_run=True)
        return

    con = wh.connect(target, duckdb_path=duckdb_path)
    try:
        cur = con.cursor()
        for statement in statements:
            print(f"  {statement.split(' FROM ')[0][:100]}")
            cur.execute(statement)
        cur.close()
        if target == "redshift":
            _load_redshift(con, schema, dry_run=False)

        for table, expected in counts.items():
            loaded = wh.fetch_df(
                con, f"SELECT COUNT(*) AS n FROM {_qualified(target, schema, table)}"
            )["n"].iloc[0]
            if int(loaded) != expected:
                sys.exit(f"{table}: loaded {loaded} rows, expected {expected}")
            print(f"  ok  {schema}.{table}: {expected} rows")
    finally:
        con.close()
    if target == "duckdb":
        print(
            f"Loaded. Next: BI_FRAMEWORK_WAREHOUSE={duckdb_path} BI_FRAMEWORK_RAW_SCHEMA={schema} "
            "dbt build --project-dir platforms/dbt --profiles-dir platforms/dbt"
        )
    else:
        print(
            "Loaded. Next: dbt build --project-dir platforms/dbt "
            f"--profiles-dir platforms/dbt --target {target}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", required=True, choices=["duckdb", *wh.CLOUD_TARGETS])
    parser.add_argument(
        "--schema",
        help="raw schema to load into (default: BI_FRAMEWORK_RAW_SCHEMA, else `raw`)",
    )
    parser.add_argument(
        "--duckdb-path",
        help="with --target duckdb: the DuckDB file to load into (required)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the SQL, connect to nothing")
    args = parser.parse_args(argv)

    if args.target == "duckdb" and not (args.duckdb_path or args.dry_run):
        parser.error("--target duckdb needs --duckdb-path (a file other than data/warehouse.duckdb)")
    try:
        if args.schema:
            schema = wh.identifier(args.schema, "--schema")
        else:
            # `raw` even for the DuckDB smoke target: the point of that
            # target is to exercise the cloud layout locally.
            schema = wh.raw_schema("cloud" if args.target == "duckdb" else args.target)
        load(args.target, schema, dry_run=args.dry_run, duckdb_path=args.duckdb_path)
    except wh.WarehouseConfigError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
