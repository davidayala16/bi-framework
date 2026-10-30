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
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
import yaml

from metrics.resolver import load_registry, resolve_metric

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
