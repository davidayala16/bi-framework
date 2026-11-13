"""Export the dbt tables the Power BI semantic model imports, as CSV.

Power BI Desktop has no built-in DuckDB connector, so the model imports
CSVs instead of querying the warehouse. This script is the only thing that
writes those CSVs, and it reads only from the `analytics` schema dbt
builds. Power BI therefore sees exactly the tables dbt tested and the
parity tests checked against the registry, the same rule LookML follows.

Run after `dbt build`, from the repo root:

    python platforms/powerbi/export_dbt_tables.py

Then set the model's DataFolder parameter to the folder it prints.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from metrics.resolver import WAREHOUSE_PATH  # noqa: E402

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "data"

# Power BI table name -> (dbt relation it is exported from, sort key).
# Sorting makes the CSVs byte-stable across runs.
EXPORTS = {
    "fct_order_items": ("analytics.fct_order_items", "order_item_id"),
    "dim_customers": ("analytics.dim_customers", "customer_id"),
    "marketing_spend": ("analytics.stg_marketing_spend", "spend_month, channel"),
}


def export(out_dir: Path = DEFAULT_OUT_DIR, warehouse: Path = WAREHOUSE_PATH) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    with duckdb.connect(str(warehouse), read_only=True) as con:
        for table, (relation, order_by) in EXPORTS.items():
            path = out_dir / f"{table}.csv"
            # Relation names and paths come from the constants above, never from
            # user input. COPY can't take a bound parameter for either.
            con.execute(
                f"COPY (SELECT * FROM {relation} ORDER BY {order_by}) "
                f"TO '{path.as_posix()}' (HEADER, DELIMITER ',')"
            )
            written[table] = path
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    try:
        written = export(args.out_dir.resolve())
    except duckdb.CatalogException as exc:
        sys.exit(
            f"{exc}\n\nThe dbt tables aren't built yet. Run:\n"
            "  dbt build --project-dir platforms/dbt --profiles-dir platforms/dbt"
        )
    for table, path in written.items():
        print(f"wrote {path}")
    print(f"\nSet the Power BI DataFolder parameter to:\n  {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
