"""Coverage tests: the LookML layer must stay wired to the registry.

There's no Looker instance behind this demo, so these tests can't run a
Looker query. They check the structural guarantees that keep LookML from
drifting into a second, ungoverned set of metric definitions:

  1. Every registry metric has exactly one LookML measure tagged
     `registry:<metric_id>`, and no tag points at a metric that doesn't exist.
  2. Each tagged measure's label matches the registry's metric name, so
     "Net Revenue" in Looker is the same thing as "Net Revenue" everywhere else.
  3. LookML reads only from the dbt-built `analytics` schema, never from raw
     tables, so Looker inherits dbt's tests and the registry parity checks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from metrics.resolver import load_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
LOOKML_FILES = sorted((REPO_ROOT / "platforms" / "looker").rglob("*.lkml"))
RAW_TABLES = {"customers", "orders", "order_items", "products", "marketing_spend"}

TAG_PATTERN = re.compile(r'"registry:([a-z0-9_]+)"')


def _lookml_text() -> str:
    return "\n".join(path.read_text() for path in LOOKML_FILES)


def test_lookml_files_exist():
    assert LOOKML_FILES, "no LookML files found under platforms/looker/"


def test_every_registry_metric_has_one_tagged_measure():
    registry_ids = [m["id"] for m in load_registry()["metrics"]]
    tags = TAG_PATTERN.findall(_lookml_text())
    missing = set(registry_ids) - set(tags)
    unknown = set(tags) - set(registry_ids)
    duplicated = {t for t in tags if tags.count(t) > 1}
    assert not missing, f"registry metrics with no LookML measure: {missing}"
    assert not unknown, f"LookML tags pointing at unknown metrics: {unknown}"
    assert not duplicated, f"registry metrics tagged on more than one measure: {duplicated}"


def test_lookml_reads_only_from_dbt_analytics_schema():
    text = _lookml_text()
    for table in re.findall(r"sql_table_name:\s*([\w.]+)", text):
        assert table.startswith("analytics."), f"view reads from non-dbt table {table!r}"
    for table in re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", text, flags=re.IGNORECASE):
        bare = table.split(".")[-1]
        assert not (bare in RAW_TABLES and not table.startswith("analytics.")), (
            f"LookML SQL reads raw table {table!r}; build it in dbt and read analytics.* instead"
        )


def test_tagged_measure_labels_match_registry_names():
    lkml = pytest.importorskip("lkml", reason="pip install -r platforms/looker/requirements.txt")
    names = {m["id"]: m["name"] for m in load_registry()["metrics"]}
    labels = {}
    for path in LOOKML_FILES:
        parsed = lkml.load(path.read_text())
        for view in parsed.get("views", []):
            for measure in view.get("measures", []):
                for tag in measure.get("tags", []):
                    if tag.startswith("registry:"):
                        labels[tag.split(":", 1)[1]] = measure.get("label")
    # acquisition_funnel is a count grouped by two dimensions, so its measure
    # is labeled by what it counts ("Customers") rather than the funnel name.
    expected = {k: v for k, v in names.items() if k != "acquisition_funnel"}
    for metric_id, name in expected.items():
        assert labels.get(metric_id) == name, (
            f"LookML label for {metric_id} is {labels.get(metric_id)!r}, registry name is {name!r}"
        )
