from pathlib import Path

import duckdb
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = REPO_ROOT / "data" / "warehouse.duckdb"
REGISTRY_PATH = REPO_ROOT / "metrics" / "registry.yaml"


@pytest.fixture(scope="session")
def warehouse():
    if not WAREHOUSE_PATH.exists():
        pytest.exit(
            "data/warehouse.duckdb not found. Run "
            "`python data/generate_synthetic_data.py` first.",
            returncode=1,
        )
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    yield con
    con.close()


@pytest.fixture(scope="session")
def registry():
    with open(REGISTRY_PATH) as f:
        data = yaml.safe_load(f)
    out = {m["id"]: m for m in data["metrics"]}
    out["__base_fact_sql__"] = data["base_fact_sql"]
    return out
