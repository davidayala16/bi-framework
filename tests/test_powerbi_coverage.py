"""Coverage tests: the Power BI project must stay wired to the registry.

There's no Power BI engine behind this demo (Desktop is Windows-only), so
these tests can't evaluate DAX. Like tests/test_lookml_coverage.py, they
check the structural guarantees that stop the Power BI layer from drifting
into a second, ungoverned set of metric definitions:

  1. Every registry metric has exactly one DAX measure annotated
     `registry_id = <metric_id>`, named after the registry entry and
     described with the registry's own description.
  2. The model imports only the CSVs export_dbt_tables.py writes, and that
     script reads only dbt's `analytics` schema, never raw tables.
  3. Filters match the registry: slicers use only ALLOWED_FILTER_COLUMNS,
     only on the order-item fact, and no relationship lets a filter reach a
     cohort metric's table (those metrics declare filterable_dimensions: []).
  4. Every field a report visual uses exists in the semantic model, as the
     right kind of object (column vs. measure).
  5. The exported CSV headers match the columns the model declares, so a
     dbt schema change can't silently break the Power BI refresh.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest

from metrics.resolver import ALLOWED_FILTER_COLUMNS, load_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
POWERBI = REPO_ROOT / "platforms" / "powerbi"
MODEL_DIR = POWERBI / "BIFramework.SemanticModel" / "definition"
REPORT_DIR = POWERBI / "BIFramework.Report" / "definition"
TABLE_FILES = sorted((MODEL_DIR / "tables").glob("*.tmdl"))

# acquisition_funnel is a count grouped by two columns, so its measure is
# named for what it counts ("Customers"), the same exception LookML makes.
NAME_EXCEPTIONS = {"acquisition_funnel": "Customers"}


def _unquote(name: str) -> str:
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def _parse_tables() -> dict[str, dict]:
    """Minimal TMDL reader: tables, their columns, and their measures.

    Only reads what these tests check. Object declarations sit at one tab of
    indentation inside a table, properties and annotations at two, and `///`
    lines directly above an object are its description.
    """
    tables = {}
    for path in TABLE_FILES:
        lines = path.read_text().splitlines()
        table_name = None
        table = {"columns": set(), "measures": {}, "partition_m": "", "file": path.name}
        current = None
        doc: list[str] = []
        in_partition = False
        for line in lines:
            if m := re.match(r"^table (.+)$", line):
                table_name = _unquote(m.group(1).strip())
                continue
            if m := re.match(r"^\t/// ?(.*)$", line):
                doc.append(m.group(1))
                continue
            if m := re.match(r"^\tmeasure ('(?:[^']|'')+'|[\w]+)\s*=", line):
                current = {"description": " ".join(doc), "annotations": {}}
                table["measures"][_unquote(m.group(1))] = current
                in_partition = False
            elif m := re.match(r"^\tcolumn ('(?:[^']|'')+'|[\w]+)", line):
                table["columns"].add(_unquote(m.group(1)))
                current = None
                in_partition = False
            elif re.match(r"^\tpartition ", line):
                current = None
                in_partition = True
            elif re.match(r"^\t\S", line):
                current = None
                in_partition = False
            elif current is not None and (
                m := re.match(r"^\t\tannotation (\w+) = (.+)$", line)
            ):
                current["annotations"][m.group(1)] = m.group(2).strip()
            elif in_partition:
                table["partition_m"] += line + "\n"
            if not line.startswith("\t///"):
                doc = []
        assert table_name, f"{path} declares no table"
        tables[table_name] = table
    return tables


TABLES = _parse_tables()


def _governed_measures() -> dict[str, tuple[str, str, dict]]:
    """registry_id -> (table, measure name, measure)."""
    out: dict[str, list] = {}
    for table_name, table in TABLES.items():
        for name, measure in table["measures"].items():
            if rid := measure["annotations"].get("registry_id"):
                out.setdefault(rid, []).append((table_name, name, measure))
    duplicated = {rid for rid, hits in out.items() if len(hits) > 1}
    assert not duplicated, f"registry metrics annotated on more than one measure: {duplicated}"
    return {rid: hits[0] for rid, hits in out.items()}


def _visuals() -> list[tuple[Path, dict]]:
    return [
        (path, json.loads(path.read_text()))
        for path in sorted(REPORT_DIR.glob("pages/*/visuals/*/visual.json"))
    ]


def _field_refs(node):
    """Yield (kind, entity, property) for every Column/Measure reference."""
    if isinstance(node, dict):
        for kind in ("Column", "Measure"):
            ref = node.get(kind)
            if isinstance(ref, dict) and "Property" in ref:
                entity = ref["Expression"]["SourceRef"]["Entity"]
                yield kind, entity, ref["Property"]
        for value in node.values():
            yield from _field_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _field_refs(value)


def test_powerbi_project_files_exist():
    assert (POWERBI / "BIFramework.pbip").exists()
    assert TABLE_FILES, "no TMDL tables under platforms/powerbi"
    assert _visuals(), "no report visuals under platforms/powerbi"


def test_every_registry_metric_has_one_annotated_measure():
    registry_ids = {m["id"] for m in load_registry()["metrics"]}
    governed = set(_governed_measures())
    assert not registry_ids - governed, (
        f"registry metrics with no Power BI measure: {registry_ids - governed}"
    )
    assert not governed - registry_ids, (
        f"Power BI measures annotated with unknown metrics: {governed - registry_ids}"
    )


def test_annotated_measures_match_registry_name_and_description():
    governed = _governed_measures()
    for metric in load_registry()["metrics"]:
        _, name, measure = governed[metric["id"]]
        assert name == NAME_EXCEPTIONS.get(metric["id"], metric["name"]), (
            f"Power BI measure for {metric['id']} is named {name!r}, "
            f"registry name is {metric['name']!r}"
        )
        assert measure["description"] == " ".join(metric["description"].split()), (
            f"Power BI description for {metric['id']} differs from the registry's"
        )


def test_model_imports_only_dbt_exports():
    from platforms.powerbi.export_dbt_tables import EXPORTS

    for relation, _ in EXPORTS.values():
        assert relation.startswith("analytics."), (
            f"export reads {relation!r}; Power BI must only see dbt's analytics schema"
        )
    assert set(TABLES) == set(EXPORTS), "model tables and exported tables differ"
    for table_name, table in TABLES.items():
        sources = re.findall(r"File\.Contents\(([^)]*)\)", table["partition_m"])
        assert sources == [f'DataFolder & "\\{table_name}.csv"'], (
            f"{table_name} must import only its own export from DataFolder, got {sources}"
        )
        for forbidden in ("Sql.Database", "Odbc.", "Web.Contents", "Value.NativeQuery"):
            assert forbidden not in table["partition_m"], (
                f"{table_name} queries a source directly ({forbidden}); export it from dbt instead"
            )


def test_slicers_respect_registry_filter_columns():
    filterable_home = {
        table for rid, (table, _, _) in _governed_measures().items()
        if next(m for m in load_registry()["metrics"] if m["id"] == rid)["filterable_dimensions"]
    }
    assert filterable_home == {"fct_order_items"}
    slicers = [(p, v) for p, v in _visuals() if v["visual"]["visualType"] == "slicer"]
    assert slicers, "expected channel/region/category slicers"
    for path, visual in slicers:
        for kind, entity, prop in _field_refs(visual["visual"]["query"]):
            assert prop in ALLOWED_FILTER_COLUMNS, (
                f"{path.parent.name} slices on {prop!r}; only {sorted(ALLOWED_FILTER_COLUMNS)} are allowed"
            )
            assert entity in filterable_home, (
                f"{path.parent.name} slices {entity}, which holds cohort metrics"
            )


def test_no_relationships_reach_cohort_tables():
    # A relationship from the fact table would let slicers filter cohort
    # metrics, which the registry declares unfilterable.
    rel_file = MODEL_DIR / "relationships.tmdl"
    text = rel_file.read_text() if rel_file.exists() else ""
    cohort_tables = {
        table for rid, (table, _, _) in _governed_measures().items()
        if not next(m for m in load_registry()["metrics"] if m["id"] == rid)["filterable_dimensions"]
    }
    for table in cohort_tables:
        assert not re.search(rf"\b{table}\.", text), (
            f"relationships.tmdl relates {table}; cohort metrics must stay unfilterable"
        )


def test_report_fields_exist_in_model():
    for path, visual in _visuals():
        for kind, entity, prop in _field_refs(visual):
            where = f"{path.relative_to(REPORT_DIR)}"
            assert entity in TABLES, f"{where} references unknown table {entity!r}"
            pool = TABLES[entity]["columns" if kind == "Column" else "measures"]
            assert prop in pool, f"{where} references unknown {kind.lower()} {entity}[{prop}]"


def test_report_pages_are_listed():
    pages = {p.name for p in (REPORT_DIR / "pages").iterdir() if p.is_dir()}
    meta = json.loads((REPORT_DIR / "pages" / "pages.json").read_text())
    assert set(meta["pageOrder"]) == pages
    assert meta["activePageName"] in pages


def test_exported_csv_headers_match_model(tmp_path, warehouse):
    from platforms.powerbi.export_dbt_tables import export

    exists = warehouse.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'analytics' AND table_name = 'fct_order_items'"
    ).fetchone()[0]
    if not exists:
        message = (
            "dbt models not built. Run: dbt build --project-dir platforms/dbt "
            "--profiles-dir platforms/dbt"
        )
        if os.environ.get("REQUIRE_DBT") == "1":
            pytest.fail(message)
        pytest.skip(message)

    for table_name, path in export(tmp_path).items():
        with path.open() as handle:
            header = next(csv.reader(handle))
        source_columns = re.findall(
            r"^\t\tsourceColumn: (\S+)$", (MODEL_DIR / "tables" / f"{table_name}.tmdl").read_text(),
            flags=re.MULTILINE,
        )
        assert header == source_columns, (
            f"{table_name}.csv columns {header} != model columns {source_columns}"
        )
