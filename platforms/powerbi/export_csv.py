"""Fallback for machines without the DuckDB ODBC driver: export the dbt
tables the Power BI model reads to CSV, one file per table.

    python platforms/powerbi/export_csv.py

Writes platforms/powerbi/export/<table>.csv (git-ignored). The table list
comes from the model's own TMDL files, so there's nothing to keep in sync.
See "Without ODBC" in platforms/powerbi/README.md for the M to swap in.
"""

from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
WAREHOUSE = HERE.parents[1] / "data" / "warehouse.duckdb"
TABLES = sorted(p.stem for p in (HERE / "BIFramework.SemanticModel" / "definition" / "tables").glob("*.tmdl"))


def main() -> None:
    out = HERE / "export"
    out.mkdir(exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    for table in TABLES:
        con.table(f"analytics.{table}").write_csv(str(out / f"{table}.csv"), header=True)
        print(f"wrote {out / f'{table}.csv'}")


if __name__ == "__main__":
    main()
