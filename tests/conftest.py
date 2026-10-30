import sys
from pathlib import Path

import duckdb
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

# Make `metrics.resolver` importable from tests no matter how pytest is
# invoked (`pytest tests/` in CI doesn't put the repo root on sys.path).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
