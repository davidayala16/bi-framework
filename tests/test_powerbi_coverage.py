"""Coverage tests: the Power BI semantic model must stay wired to the registry.

platforms/powerbi is a Power BI Project (PBIP) whose semantic model is
stored as TMDL text, so its measures can be read and checked here the same
way tests/test_lookml_coverage.py checks LookML. CI has no Power BI engine
(Desktop is Windows-only), so these tests don't evaluate DAX. They check
the structural guarantees that keep the model from drifting into a second,
ungoverned set of metric definitions:

  1. Every registry metric has exactly one measure annotated
     `registry_id = <metric_id>`, and no annotation points at a metric that
     doesn't exist.
  2. Each tagged measure's name, description, owner, and format string
     match its registry entry.
  3. Metrics the registry marks as not filterable read their precomputed
     dbt metric table, and that table has no relationships, so no slicer
     can change a number the registry says is fixed.
  4. The model reads only from the dbt-built `analytics` schema, every
     partition query runs against the warehouse, and it returns exactly the
     columns the TMDL declares.
  5. The project is internally consistent: every file parses, references
     between files resolve, and DAX refers only to tables, columns, and
     measures that exist.

Needs `dbt build` for (4)'s warehouse checks; like the dbt parity tests,
those skip locally if dbt hasn't run and fail in CI (REQUIRE_DBT=1).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from metrics.resolver import load_registry
from tmdl_parser import Node, parse_tmdl_file, split_column_ref

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = REPO_ROOT / "platforms" / "powerbi"
PBIP_FILE = PROJECT_DIR / "BIFramework.pbip"
MODEL_DIR = PROJECT_DIR / "BIFramework.SemanticModel"
DEFINITION_DIR = MODEL_DIR / "definition"
TABLE_FILES = sorted((DEFINITION_DIR / "tables").glob("*.tmdl"))

DBT_SCHEMA = "analytics"
RAW_TABLES = {"customers", "orders", "order_items", "products", "marketing_spend"}

# The registry has no format-string field; a measure's format is derived
# from the metric's `unit`. Percent metrics are stored on a 0-100 scale
# (the registry returns 78.7, not 0.787), so the percent sign is a literal
# rather than DAX's `%`, which would multiply by 100 again.
FORMAT_BY_UNIT = {"USD": r"\$#,0.00", "percent": r"0.0\%", "count": "#,0"}

# The native query inside each partition's M expression:
#   Odbc.Query("<connection string>" & WarehousePath & "...", "<sql>")
PARTITION_SQL = re.compile(r'Odbc\.Query\(\s*"[^"]*"\s*&\s*WarehousePath\s*&\s*"[^"]*"\s*,\s*"([^"]+)"\s*\)')
DAX_COLUMN_REF = re.compile(r"(?:'([^']+)'|\b([A-Za-z_]\w*))\[([^\]]+)\]")
DAX_MEASURE_REF = re.compile(r"(?<![\w'\]])\[([^\]@][^\]]*)\]")


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())


def _strip_dax_comments_and_strings(dax: str) -> str:
    dax = re.sub(r"(--|//)[^\n]*", "", dax)
    return re.sub(r'"(?:[^"]|"")*"', '""', dax)


@pytest.fixture(scope="module")
def tables() -> dict[str, Node]:
    out = {}
    for path in TABLE_FILES:
        (table,) = parse_tmdl_file(path)
        assert table.keyword == "table", f"{path.name} must define exactly one table"
        assert table.name == path.stem, f"{path.name} defines table {table.name!r}"
        out[table.name] = table
    return out


@pytest.fixture(scope="module")
def measures(tables) -> list[tuple[str, Node]]:
    """(table name, measure node) for every measure in the model."""
    return [(name, m) for name, table in tables.items() for m in table.find("measure")]


@pytest.fixture(scope="module")
def tagged(measures) -> dict[str, tuple[str, Node]]:
    """registry_id -> (table name, measure node)."""
    return {
        m.annotations["registry_id"]: (table, m)
        for table, m in measures
        if "registry_id" in m.annotations
    }


@pytest.fixture(scope="module")
def registry() -> dict[str, dict]:
    return {m["id"]: m for m in load_registry()["metrics"]}


@pytest.fixture(scope="module")
def relationships() -> list[tuple[tuple[str, str], tuple[str, str]]]:
    return [
        (split_column_ref(r.prop("fromColumn")), split_column_ref(r.prop("toColumn")))
        for r in parse_tmdl_file(DEFINITION_DIR / "relationships.tmdl")
        if r.keyword == "relationship"
    ]


def _partition_sql(table: Node) -> str:
    (partition,) = table.find("partition")
    assert partition.value == "m" and partition.prop("mode") == "import", (
        f"{table.name}: expected a single import-mode M partition"
    )
    match = PARTITION_SQL.search(partition.prop("source") or "")
    assert match, f"{table.name}: partition source isn't an Odbc.Query against WarehousePath"
    return match.group(1)


# --- 1. coverage -----------------------------------------------------------


def test_every_registry_metric_has_one_tagged_measure(measures, registry):
    ids = [m.annotations["registry_id"] for _, m in measures if "registry_id" in m.annotations]
    missing = set(registry) - set(ids)
    unknown = set(ids) - set(registry)
    duplicated = {i for i in ids if ids.count(i) > 1}
    assert not missing, f"registry metrics with no Power BI measure: {missing}"
    assert not unknown, f"measures annotated with unknown registry ids: {unknown}"
    assert not duplicated, f"registry metrics claimed by more than one measure: {duplicated}"


def test_measure_names_are_unique_across_the_model(measures):
    names = [m.name for _, m in measures]
    assert len(names) == len(set(names)), "Power BI requires measure names to be unique model-wide"


# --- 2. metadata matches the registry --------------------------------------


def test_tagged_measure_names_match_registry(tagged, registry):
    for metric_id, (_, measure) in tagged.items():
        assert measure.name == registry[metric_id]["name"], (
            f"measure for {metric_id} is named {measure.name!r}, "
            f"registry name is {registry[metric_id]['name']!r}"
        )


def test_tagged_measure_descriptions_match_registry(tagged, registry):
    for metric_id, (_, measure) in tagged.items():
        assert _one_line(measure.description) == _one_line(registry[metric_id]["description"]), (
            f"description of the {metric_id} measure has drifted from the registry"
        )


def test_tagged_measure_owner_and_folder_match_registry(tagged, registry):
    for metric_id, (_, measure) in tagged.items():
        assert measure.annotations.get("registry_owner") == registry[metric_id]["owner"]
        assert measure.prop("displayFolder") == registry[metric_id]["category"]


def test_tagged_measure_format_strings_follow_registry_unit(tagged, registry):
    for metric_id, (_, measure) in tagged.items():
        unit = registry[metric_id]["unit"]
        assert unit in FORMAT_BY_UNIT, f"no Power BI format string defined for unit {unit!r}"
        assert measure.prop("formatString") == FORMAT_BY_UNIT[unit], (
            f"{metric_id} has unit {unit!r} but format string {measure.prop('formatString')!r}"
        )


# --- 3. non-filterable metrics read dbt's precomputed tables ---------------


def test_non_filterable_metrics_read_their_dbt_metric_table(tagged, registry, tables):
    for metric_id, metric in registry.items():
        if metric["filterable_dimensions"]:
            continue
        home, measure = tagged[metric_id]
        expected = f"metric_{metric_id}"
        assert home == expected, f"{metric_id} measure should live on {expected}, not {home}"
        referenced = {
            quoted or bare
            for quoted, bare, _ in DAX_COLUMN_REF.findall(
                _strip_dax_comments_and_strings(measure.value)
            )
        }
        assert referenced == {expected}, (
            f"{metric_id} is not filterable in the registry, so its measure must read only "
            f"the precomputed {expected} table; it references {referenced}"
        )
        assert f"{DBT_SCHEMA}.{expected}" in _partition_sql(tables[expected])


def test_metric_tables_have_no_relationships(relationships, tables):
    related = {table for ends in relationships for table, _ in ends}
    reachable = {t for t in related if t.startswith("metric_")}
    assert not reachable, (
        f"{reachable} joined into the model: slicers would filter a metric the registry "
        "defines as not filterable"
    )
    assert any(t.startswith("metric_") for t in tables)


def test_filterable_metrics_are_measured_on_the_order_item_fact(tagged, registry, tables):
    fact = tables["fct_order_items"]
    columns = {c.name for c in fact.find("column")}
    for metric_id, metric in registry.items():
        if not metric["filterable_dimensions"]:
            continue
        assert tagged[metric_id][0] == "fct_order_items"
        missing = set(metric["filterable_dimensions"]) - columns
        assert not missing, f"fct_order_items has no column to slice {metric_id} by: {missing}"


# --- 4. the model reads dbt, and its queries run ---------------------------


def test_model_reads_only_from_dbt_analytics_schema(tables):
    for name, table in tables.items():
        sql = _partition_sql(table)
        sources = re.findall(r"\b(?:from|join)\s+([\w.]+)", sql, flags=re.IGNORECASE)
        assert sources == [f"{DBT_SCHEMA}.{name}"], (
            f"{name} should read exactly {DBT_SCHEMA}.{name}; its query reads {sources}"
        )
        assert name not in RAW_TABLES


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


# TMDL column dataType -> DuckDB types that load into it without conversion.
DUCKDB_TYPES = {
    "int64": {"BIGINT", "INTEGER"},
    "double": {"DOUBLE"},
    "string": {"VARCHAR"},
    "dateTime": {"DATE", "TIMESTAMP"},
    "boolean": {"BOOLEAN"},
}


def test_partition_queries_run_and_match_declared_columns(tables, dbt_built):
    for name, table in tables.items():
        result = dbt_built.execute(_partition_sql(table))
        actual = {column[0]: str(column[1]) for column in result.description}
        declared = {c.prop("sourceColumn"): c for c in table.find("column")}
        assert set(actual) == set(declared), (
            f"{name}: query returns {sorted(actual)}, TMDL declares {sorted(declared)}"
        )
        for column_name, column in declared.items():
            assert column.name == column_name, f"{name}.{column.name} renames its source column"
            data_type = column.prop("dataType")
            assert actual[column_name] in DUCKDB_TYPES[data_type], (
                f"{name}.{column_name} is declared {data_type} but dbt builds {actual[column_name]}"
            )
        typed = set(re.findall(r'\{"(\w+)",', table.find("partition")[0].prop("source")))
        assert typed == set(declared), f"{name}: Table.TransformColumnTypes doesn't cover every column"


# --- 5. the project is internally consistent -------------------------------


def test_project_files_exist_and_reference_each_other():
    assert TABLE_FILES, "no TMDL tables found under platforms/powerbi/"
    pbip = json.loads(PBIP_FILE.read_text())
    report_dir = PROJECT_DIR / pbip["artifacts"][0]["report"]["path"]
    pbir = json.loads((report_dir / "definition.pbir").read_text())
    model_dir = (report_dir / pbir["datasetReference"]["byPath"]["path"]).resolve()
    assert model_dir == MODEL_DIR.resolve(), "report doesn't point at the semantic model"
    assert json.loads((MODEL_DIR / "definition.pbism").read_text())["version"]
    for required in ("database.tmdl", "model.tmdl"):
        assert (DEFINITION_DIR / required).exists()

    pages = json.loads((report_dir / "definition" / "pages" / "pages.json").read_text())
    for page in pages["pageOrder"]:
        page_json = json.loads((report_dir / "definition" / "pages" / page / "page.json").read_text())
        assert page_json["name"] == page
    for path in report_dir.rglob("*.json"):
        assert json.loads(path.read_text()).get("$schema", "").startswith(
            "https://developer.microsoft.com/json-schemas/fabric/item/report/"
        ), f"{path.name} doesn't declare a Microsoft report schema"


def test_every_tmdl_file_parses():
    files = sorted(DEFINITION_DIR.rglob("*.tmdl"))
    assert len(files) > len(TABLE_FILES)
    for path in files:
        assert parse_tmdl_file(path), f"{path.name} is empty"


def test_model_refs_match_table_files(tables):
    nodes = parse_tmdl_file(DEFINITION_DIR / "model.tmdl")
    assert nodes[0].keyword == "model"
    refs = [n.name for n in nodes if n.keyword == "ref table"]
    assert sorted(refs) == sorted(tables), "model.tmdl `ref table` list is out of sync with tables/"


def test_relationships_join_existing_columns_of_matching_type(relationships, tables):
    assert relationships, "no relationships defined between the marts"
    for (from_table, from_column), (to_table, to_column) in relationships:
        source = {c.name: c for c in tables[from_table].find("column")}[from_column]
        target = {c.name: c for c in tables[to_table].find("column")}[to_column]
        assert source.prop("dataType") == target.prop("dataType")
        assert target.has_flag("isKey"), f"{to_table}.{to_column} is the one side and should be the key"


def test_columns_are_fully_declared_and_not_implicitly_summarized(tables):
    for name, table in tables.items():
        assert table.prop("lineageTag"), f"{name} has no lineageTag"
        for column in table.find("column"):
            assert column.prop("dataType") in DUCKDB_TYPES, f"{name}.{column.name}"
            # Numbers must reach a visual through a governed measure, never
            # through Power BI's implicit "sum this column".
            assert column.prop("summarizeBy") == "none", f"{name}.{column.name}"


def test_dax_references_resolve(measures, tables):
    columns = {(t, c.name) for t, table in tables.items() for c in table.find("column")}
    measure_names = {m.name for _, m in measures}
    for _, measure in measures:
        dax = _strip_dax_comments_and_strings(measure.value)
        for quoted, bare, column in DAX_COLUMN_REF.findall(dax):
            assert (quoted or bare, column) in columns, (
                f"measure {measure.name!r} references missing column {quoted or bare}[{column}]"
            )
        for name in DAX_MEASURE_REF.findall(dax):
            assert name in measure_names, (
                f"measure {measure.name!r} references missing measure [{name}]"
            )


def test_warehouse_path_is_a_parameter_not_a_hardcoded_connection(tables):
    (parameter,) = [
        n for n in parse_tmdl_file(DEFINITION_DIR / "expressions.tmdl") if n.keyword == "expression"
    ]
    assert parameter.name == "WarehousePath"
    assert "IsParameterQuery=true" in parameter.value
    for table in tables.values():
        assert "WarehousePath" in table.find("partition")[0].prop("source")
