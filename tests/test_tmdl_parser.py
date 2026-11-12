"""Unit tests for tests/tmdl_parser.py.

The Power BI coverage tests are only as trustworthy as the parser under
them, so the TMDL constructs the model relies on are pinned here against
small inline documents. Indentation in the fixtures is real tabs, as TMDL
requires.
"""

from __future__ import annotations

import pytest

from tmdl_parser import TmdlSyntaxError, parse_tmdl, split_column_ref, unquote_name

TABLE = """\
/// Order facts.
/// Built by dbt.
table 'Order Items'
\tlineageTag: 3e6a7a50-87b3-5345-9ad6-6623978ad19c

\t/// Total revenue.
\tmeasure 'Net Revenue' = SUM('Order Items'[revenue])
\t\tformatString: \\$#,0.00
\t\tdisplayFolder: Revenue

\t\tannotation registry_id = net_revenue

\t\tannotation PBI_FormatHint = {"isCustom":true}

\tmeasure 'Average Order Value' =
\t\t\t-- order grain: a comment with a colon
\t\t\tDIVIDE(
\t\t\t    [Net Revenue],
\t\t\t    DISTINCTCOUNT('Order Items'[order_id])
\t\t\t)
\t\tformatString: \\$#,0.00

\t\tannotation registry_id = aov

\tmeasure Margin = ```
\t\t\tSUMX(
\t\t\t    'Order Items',
\t\t\t    [revenue]
\t\t\t)

\t\t\t```
\t\tformatString: #,0

\tcolumn revenue
\t\tdataType: double
\t\tisHidden
\t\tsummarizeBy: none
\t\tsourceColumn: revenue

\tcolumn order_id
\t\tdataType: int64
\t\tisKey: true
\t\tisAvailableInMdx: false

\tpartition 'Order Items' = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t    Source = Odbc.Query("Driver=x", "select revenue from analytics.t")
\t\t\t\tin
\t\t\t\t    Source

\tannotation PBI_ResultType = Table
"""


@pytest.fixture(scope="module")
def table():
    (node,) = parse_tmdl(TABLE)
    return node


def test_object_name_and_multiline_description(table):
    assert (table.keyword, table.name) == ("table", "Order Items")
    assert table.description == "Order facts.\nBuilt by dbt."
    assert table.prop("lineageTag") == "3e6a7a50-87b3-5345-9ad6-6623978ad19c"
    assert table.annotations == {"PBI_ResultType": "Table"}


def test_single_line_measure(table):
    measure = table.find("measure")[0]
    assert measure.name == "Net Revenue"
    assert measure.value == "SUM('Order Items'[revenue])"
    assert measure.description == "Total revenue."
    assert measure.prop("formatString") == "\\$#,0.00"
    assert measure.prop("displayFolder") == "Revenue"
    assert measure.annotations == {
        "registry_id": "net_revenue",
        "PBI_FormatHint": '{"isCustom":true}',
    }


def test_multiline_expression_stops_at_the_owners_properties(table):
    measure = table.find("measure")[1]
    assert measure.value == (
        "-- order grain: a comment with a colon\n"
        "DIVIDE(\n"
        "    [Net Revenue],\n"
        "    DISTINCTCOUNT('Order Items'[order_id])\n"
        ")"
    )
    assert measure.prop("formatString") == "\\$#,0.00"
    assert measure.annotations == {"registry_id": "aov"}
    assert measure.description is None


def test_backtick_fenced_expression(table):
    measure = table.find("measure")[2]
    assert measure.name == "Margin"
    assert measure.value == "SUMX(\n    'Order Items',\n    [revenue]\n)"
    assert measure.prop("formatString") == "#,0"


def test_flags_and_explicit_booleans(table):
    revenue, order_id = table.find("column")
    assert revenue.has_flag("isHidden")
    assert not revenue.has_flag("isKey")
    assert order_id.has_flag("isKey")
    assert not order_id.has_flag("isAvailableInMdx")
    assert revenue.prop("dataType") == "double"


def test_partition_with_multiline_property_expression(table):
    (partition,) = table.find("partition")
    assert (partition.name, partition.value) == ("Order Items", "m")
    assert partition.prop("mode") == "import"
    assert partition.prop("source") == (
        "let\n"
        '    Source = Odbc.Query("Driver=x", "select revenue from analytics.t")\n'
        "in\n"
        "    Source"
    )


def test_model_file_refs_bare_objects_and_top_level_annotations():
    nodes = parse_tmdl(
        "model Model\n"
        "\tculture: en-US\n"
        "\tdiscourageImplicitMeasures\n"
        "\tdataAccessOptions\n"
        "\t\tlegacyRedirects\n"
        "\n"
        'annotation PBI_QueryOrder = ["a","b"]\n'
        "\n"
        "ref table fct_orders\n"
        "ref table 'Smart Calcs'\n"
    )
    model = nodes[0]
    assert (model.keyword, model.name) == ("model", "Model")
    assert model.has_flag("discourageImplicitMeasures")
    assert model.find("dataAccessOptions")[0].has_flag("legacyRedirects")
    assert nodes[1].name == "PBI_QueryOrder" and nodes[1].value == '["a","b"]'
    assert [n.name for n in nodes if n.keyword == "ref table"] == ["fct_orders", "Smart Calcs"]


def test_unnamed_database_object():
    (database,) = parse_tmdl("database\n\tcompatibilityLevel: 1601\n")
    assert database.name is None and database.prop("compatibilityLevel") == "1601"


def test_relationships():
    first, second = parse_tmdl(
        "relationship 61777601-74c8-5c21-8115-e299f3c58b0b\n"
        "\tfromColumn: Sales.'Order Date'\n"
        "\ttoColumn: Calendar.Date\n"
        "\n"
        "relationship other\n"
        "\tisActive: false\n"
        "\tfromColumn: Sales.CustomerKey\n"
        "\ttoColumn: Customer.CustomerKey\n"
    )
    assert first.name == "61777601-74c8-5c21-8115-e299f3c58b0b"
    assert split_column_ref(first.prop("fromColumn")) == ("Sales", "Order Date")
    assert split_column_ref(first.prop("toColumn")) == ("Calendar", "Date")
    assert not second.has_flag("isActive")


def test_expression_with_m_metadata_and_description():
    (expression,) = parse_tmdl(
        "/// Path to the warehouse.\n"
        'expression WarehousePath = "C:\\data\\w.duckdb" meta [IsParameterQuery=true, Type="Text"]\n'
        "\tlineageTag: abc\n"
    )
    assert expression.name == "WarehousePath"
    assert expression.value == '"C:\\data\\w.duckdb" meta [IsParameterQuery=true, Type="Text"]'
    assert expression.description == "Path to the warehouse."


def test_quoted_names():
    assert unquote_name("'It''s here' = 1") == ("It's here", " = 1")
    assert unquote_name("plain = 1") == ("plain", " = 1")
    (measure,) = parse_tmdl("table t\n\tmeasure '# Customers (it''s)' = 1\n")[0].find("measure")
    assert measure.name == "# Customers (it's)"
    assert split_column_ref("'My Table'.'My Column'") == ("My Table", "My Column")
    with pytest.raises(ValueError):
        split_column_ref("no_dot")


def test_byte_order_mark_and_crlf_are_tolerated():
    (node,) = parse_tmdl("\ufefftable t\r\n\tlineageTag: x\r\n")
    assert node.name == "t" and node.prop("lineageTag") == "x"


@pytest.mark.parametrize(
    "text, message",
    [
        ("table t\n    lineageTag: x\n", "indentation must be tabs"),
        ("table t\n\t\tlineageTag: x\n", "unexpected indentation"),
        ("\ttable t\n", "unexpected indentation"),
        ("table t\n\tmeasure m = ```\n\t\t\t1\n", "unterminated"),
        ("table t\n\tmeasure m =\n\tcolumn c\n", "no expression"),
        ("table t\n\tmeasure 'm = 1\n", "unterminated quoted name"),
        ("table t extra\n", "unexpected text"),
        ("// not a TMDL comment\ntable t\n", "comments"),
        ("table t\n/// dangling\n", "no object after it"),
    ],
)
def test_malformed_tmdl_is_rejected(text, message):
    with pytest.raises(TmdlSyntaxError, match=message):
        parse_tmdl(text)


def test_errors_report_file_and_line():
    with pytest.raises(TmdlSyntaxError) as excinfo:
        parse_tmdl("table t\n\tlineageTag: x\n\t\t\tbad: y\n", source="model.tmdl")
    assert str(excinfo.value).startswith("model.tmdl:3:")
