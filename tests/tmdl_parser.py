"""A small parser for TMDL (Tabular Model Definition Language) files.

Power BI's project format (PBIP) stores the semantic model as TMDL text
under `<Name>.SemanticModel/definition/`. There's no maintained Python
library for the format (Microsoft's parser is the .NET TOM library), so
tests/test_powerbi_coverage.py reads it with this module instead.

It covers the subset of TMDL the model in platforms/powerbi uses, which is
also what Power BI Desktop writes for an import-mode model:

    /// description line(s), attached to the next object
    table Sales                              object: keyword + name
    measure 'Sales Amount' = SUM(...)        object with a default expression
        formatString: #,##0                  property (`key: value`)
        isHidden                             boolean flag
        annotation registry_id = aov         named child with a value
    measure Margin =                         multi-line expression: the lines
            SUMX(...)                        below, indented deeper than the
        formatString: #,##0                  owner's own properties
    measure Margin = ```                     or fenced with triple backticks
            SUMX(...)
            ```
    ref table 'Smart Calcs'                  reference

Indentation is one tab per level, as Desktop writes it. The parser is
deliberately strict (space indentation, skipped levels, and unterminated
blocks are errors) so a hand-edit that Desktop would reject fails here
first. It does not validate DAX or M: expressions are kept as opaque text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FENCE = "```"
_PROPERTY = re.compile(r"^([A-Za-z_][\w]*)\s*:\s*(.*)$")
_KEYWORD = re.compile(r"^([A-Za-z_][\w]*)(.*)$")
# An unquoted name runs until whitespace or `=`. Dots are allowed so that
# column references such as `Sales.CustomerKey` aren't split.
_UNQUOTED_NAME = re.compile(r"^[^\s=']+")


class TmdlSyntaxError(ValueError):
    def __init__(self, message: str, line_no: int, source: str = "<string>"):
        super().__init__(f"{source}:{line_no}: {message}")
        self.line_no = line_no


@dataclass
class Node:
    """One TMDL line: an object, a property, a flag, or an annotation.

    keyword  - `table`, `measure`, `formatString`, `annotation`, `ref table`…
    name     - the object's name with quoting removed, or None
    value    - text after `:` or `=`; None for flags and bare objects
    """

    keyword: str
    name: str | None = None
    value: str | None = None
    description: str | None = None
    line_no: int = 0
    children: list["Node"] = field(default_factory=list)

    def find(self, keyword: str) -> list["Node"]:
        return [c for c in self.children if c.keyword == keyword]

    def prop(self, keyword: str, default: str | None = None) -> str | None:
        """Value of an unnamed child (`formatString: …`, `source = …`)."""
        for child in self.children:
            if child.keyword == keyword and child.name is None:
                return child.value
        return default

    def has_flag(self, keyword: str) -> bool:
        """True for a bare flag (`isHidden`) or an explicit `isHidden: true`."""
        for child in self.children:
            if child.keyword == keyword and child.name is None:
                return child.value is None or child.value.strip().lower() == "true"
        return False

    @property
    def annotations(self) -> dict[str, str]:
        return {c.name: c.value or "" for c in self.find("annotation")}


def unquote_name(text: str) -> tuple[str, str]:
    """Split a leading TMDL name off `text`; returns (name, remainder).

    Names containing anything other than word characters are wrapped in
    single quotes, with embedded single quotes doubled.
    """
    if text.startswith("'"):
        out = []
        i = 1
        while i < len(text):
            if text[i] == "'":
                if text[i + 1 : i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), text[i + 1 :]
            out.append(text[i])
            i += 1
        raise ValueError("unterminated quoted name")
    match = _UNQUOTED_NAME.match(text)
    if not match:
        raise ValueError("expected a name")
    return match.group(0), text[match.end() :]


def split_column_ref(ref: str) -> tuple[str, str]:
    """`Sales.'Order Date'` -> ("Sales", "Order Date")."""
    table, rest = _split_ref_part(ref.strip())
    if not rest.startswith("."):
        raise ValueError(f"expected table.column, got {ref!r}")
    column, tail = _split_ref_part(rest[1:])
    if tail.strip():
        raise ValueError(f"expected table.column, got {ref!r}")
    return table, column


def _split_ref_part(text: str) -> tuple[str, str]:
    if text.startswith("'"):
        return unquote_name(text)
    head, sep, tail = text.partition(".")
    return head, sep + tail


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip("\t"))


def _dedent(lines: list[str]) -> str:
    """Drop surrounding blank lines and the common leading indentation."""
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    if not lines:
        return ""
    margin = min(_indent_of(line) for line in lines if line.strip())
    return "\n".join(line[margin:] if line.strip() else "" for line in lines)


def parse_tmdl(text: str, source: str = "<string>") -> list[Node]:
    """Parse TMDL text into its top-level nodes."""
    lines = text.lstrip("﻿").splitlines()
    roots: list[Node] = []
    stack: list[tuple[int, Node]] = []
    pending_description: list[str] = []
    i = 0

    def fail(message: str, at: int) -> TmdlSyntaxError:
        return TmdlSyntaxError(message, at + 1, source)

    while i < len(lines):
        raw = lines[i].rstrip()
        content = raw.lstrip("\t")
        if not content.strip():
            i += 1
            continue
        indent = len(raw) - len(content)
        if content[0] == " ":
            raise fail("indentation must be tabs, one per level", i)

        if content.startswith("///"):
            pending_description.append(content[3:].strip())
            i += 1
            continue
        if content.startswith("//"):
            raise fail("`//` comments outside an expression aren't supported here; use `///`", i)

        while stack and stack[-1][0] >= indent:
            stack.pop()
        expected = stack[-1][0] + 1 if stack else 0
        if indent != expected:
            raise fail(f"unexpected indentation (level {indent}, expected {expected})", i)

        node = Node(keyword="", line_no=i + 1)
        prop = _PROPERTY.match(content)
        if prop:
            node.keyword, node.value = prop.group(1), prop.group(2).strip()
            i += 1
        else:
            match = _KEYWORD.match(content)
            if not match:
                raise fail(f"cannot parse {content!r}", i)
            keyword, rest = match.group(1), match.group(2).strip()
            if keyword == "ref":
                kind, _, rest = rest.partition(" ")
                keyword, rest = f"ref {kind}", rest.strip()
            node.keyword = keyword
            if rest and not rest.startswith("="):
                try:
                    node.name, rest = unquote_name(rest)
                except ValueError as exc:
                    raise fail(str(exc), i) from None
                rest = rest.strip()
            if rest.startswith("="):
                # An object's own properties sit one level below it, so its
                # expression body is two levels down; a property has no
                # properties, so its body starts one level down.
                depth = indent + (2 if node.name is not None else 1)
                node.value, i = _read_expression(lines, i, depth, rest[1:].strip(), fail)
            elif rest:
                raise fail(f"unexpected text after name: {rest!r}", i)
            else:
                i += 1

        if pending_description:
            node.description = "\n".join(pending_description).strip()
            pending_description = []
        (stack[-1][1].children if stack else roots).append(node)
        stack.append((indent, node))

    if pending_description:
        raise TmdlSyntaxError("`///` description with no object after it", len(lines), source)
    return roots


def _read_expression(lines, i, depth, first, fail):
    """Read the expression that starts on line `i`; returns (text, next_i).

    `depth` is the minimum indentation of a multi-line expression body.
    """
    if first.startswith(FENCE):
        if first != FENCE:
            raise fail("nothing may follow an opening ``` fence", i)
        body = []
        j = i + 1
        while j < len(lines):
            if lines[j].strip() == FENCE:
                return _dedent(body), j + 1
            body.append(lines[j].rstrip())
            j += 1
        raise fail("unterminated ``` block", i)
    if first:
        return first, i + 1
    body = []
    j = i + 1
    while j < len(lines):
        line = lines[j].rstrip()
        if line.strip() and _indent_of(line) < depth:
            break
        body.append(line)
        j += 1
    text = _dedent(body)
    if not text:
        raise fail("`=` with no expression after it", i)
    return text, j


def parse_tmdl_file(path: Path) -> list[Node]:
    return parse_tmdl(Path(path).read_text(encoding="utf-8"), source=str(path))
