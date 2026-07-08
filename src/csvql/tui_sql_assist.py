"""Deterministic SQL assistance helpers for the CSVQL TUI."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from csvql.tui_state import TUISource, TUISourceColumn
from csvql.tui_workflows import render_duckdb_identifier

ColumnKind = Literal["numeric", "date_trend", "time_only", "text", "unknown"]
CompletionItemKind = Literal["source", "column", "keyword", "snippet"]

_RESERVED_GENERATED_IDENTIFIERS = {
    "all",
    "and",
    "as",
    "by",
    "case",
    "cast",
    "create",
    "delete",
    "from",
    "group",
    "insert",
    "join",
    "limit",
    "not",
    "null",
    "or",
    "order",
    "select",
    "table",
    "update",
    "where",
    "with",
}

_KEYWORD_SNIPPETS = (
    ("select_from", "SELECT ... FROM ...", "SELECT *\nFROM "),
    ("where", "WHERE", "WHERE "),
    ("group_by", "GROUP BY", "GROUP BY "),
    ("order_by", "ORDER BY", "ORDER BY "),
    ("count", "COUNT(*)", "COUNT(*)"),
)

_TOKEN_PREFIX_PATTERN = re.compile(r'[A-Za-z0-9_."]')
_NUMERIC_TYPES = {
    "INTEGER",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "DECIMAL",
    "NUMERIC",
}
_TEXT_TYPES = {"VARCHAR", "TEXT", "STRING"}
_KEYWORDS = ("SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "JOIN", "COUNT(*)")


@dataclass(frozen=True, slots=True)
class SQLAssistColumn:
    """One source column and its deterministic assistance classification."""

    name: str
    duckdb_type: str
    kind: ColumnKind


@dataclass(frozen=True, slots=True)
class SQLAssistSource:
    """One TUI source plus any loaded column metadata."""

    name: str
    columns: tuple[SQLAssistColumn, ...]


@dataclass(frozen=True, slots=True)
class SQLTemplateOption:
    """One SQL template that may be inserted into the editor."""

    key: str
    label: str
    detail: str
    sql: str
    requires_columns: bool


@dataclass(frozen=True, slots=True)
class SQLCompletionItem:
    """One completion palette entry."""

    key: str
    label: str
    detail: str
    insert_text: str
    item_kind: CompletionItemKind


@dataclass(frozen=True, slots=True)
class CompletionEdit:
    """One text replacement operation in the SQL editor."""

    start_index: int
    end_index: int
    replacement: str


def classify_duckdb_type(duckdb_type: str) -> ColumnKind:
    """Map a DuckDB type string onto the bounded assistance kind set."""

    type_head = re.split(r"[\s(]", duckdb_type.strip().upper(), maxsplit=1)[0]
    if type_head in _NUMERIC_TYPES:
        return "numeric"
    if type_head in {"DATE", "TIMESTAMP"}:
        return "date_trend"
    if type_head == "TIME":
        return "time_only"
    if type_head in _TEXT_TYPES:
        return "text"
    return "unknown"


def safe_generated_identifier(stem: str, *, reserved_prefix: str) -> str:
    """Return a safe unquoted generated identifier."""

    identifier = _sanitize_identifier_stem(stem)
    if not identifier:
        identifier = f"{reserved_prefix}value"
    if identifier[0].isdigit():
        identifier = f"{reserved_prefix}{identifier}"
    if identifier in _RESERVED_GENERATED_IDENTIFIERS:
        identifier = f"{reserved_prefix}{identifier}"
    return identifier


def make_range_aliases(source_names: Sequence[str]) -> dict[str, str]:
    """Generate deterministic SQL range aliases keyed by source name."""

    aliases: dict[str, str] = {}
    used_aliases: set[str] = set()
    for source_name in source_names:
        sanitized = _sanitize_identifier_stem(source_name)
        parts = [part for part in sanitized.split("_") if part]
        if not parts:
            candidate = "t"
        elif len(parts) == 1 and sanitized in _RESERVED_GENERATED_IDENTIFIERS:
            candidate = safe_generated_identifier(sanitized, reserved_prefix="t_")
        elif len(parts) == 1:
            candidate = parts[0][0]
        else:
            candidate = "".join(part[0] for part in parts)
        aliases[source_name] = _unique_generated_identifier(
            safe_generated_identifier(candidate, reserved_prefix="t_"),
            used_aliases,
        )
    return aliases


def make_output_alias(prefix: str, column_name: str, used_aliases: set[str]) -> str:
    """Generate one deterministic output alias and record it as used."""

    column_identifier = safe_generated_identifier(column_name, reserved_prefix="col_")
    prefix_identifier = safe_generated_identifier(prefix, reserved_prefix="col_")
    return _unique_generated_identifier(
        safe_generated_identifier(
            f"{prefix_identifier}_{column_identifier}",
            reserved_prefix="col_",
        ),
        used_aliases,
    )


def build_assist_sources(
    sources: Sequence[TUISource],
    columns_by_source: Mapping[str, Sequence[TUISourceColumn]],
) -> tuple[SQLAssistSource, ...]:
    """Build typed assistance sources from TUI state inputs."""

    return tuple(
        SQLAssistSource(
            name=source.name,
            columns=tuple(
                SQLAssistColumn(
                    name=column.name,
                    duckdb_type=column.duckdb_type,
                    kind=classify_duckdb_type(column.duckdb_type),
                )
                for column in _columns_for_source(columns_by_source, source.name)
            ),
        )
        for source in sources
    )


def build_template_options(
    sources: Sequence[SQLAssistSource],
    selected_source_name: str,
) -> tuple[SQLTemplateOption, ...]:
    """Build deterministic template options for the selected source."""

    selected_source = next(source for source in sources if source.name == selected_source_name)
    selected_name = render_duckdb_identifier(selected_source.name)
    options = [
        SQLTemplateOption(
            key="preview",
            label="Preview rows",
            detail="Show the first 10 rows.",
            sql=f"SELECT *\nFROM {selected_name}\nLIMIT 10;",
            requires_columns=False,
        ),
        SQLTemplateOption(
            key="row_count",
            label="Row count",
            detail="Count all rows.",
            sql=f"SELECT COUNT(*) AS row_count\nFROM {selected_name};",
            requires_columns=False,
        ),
    ]
    if not selected_source.columns:
        return tuple(options)

    range_alias = make_range_aliases((selected_source.name,))[selected_source.name]
    qualified_source = f"{selected_name} AS {range_alias}"
    used_aliases: set[str] = set()

    first_numeric = _first_column_of_kind(selected_source.columns, "numeric")
    if first_numeric is not None:
        non_null_alias = make_output_alias("non_null", first_numeric.name, used_aliases)
        min_alias = make_output_alias("min", first_numeric.name, used_aliases)
        avg_alias = make_output_alias("avg", first_numeric.name, used_aliases)
        max_alias = make_output_alias("max", first_numeric.name, used_aliases)
        sum_alias = make_output_alias("sum", first_numeric.name, used_aliases)
        numeric_name = _qualified_range_column(range_alias, first_numeric.name)
        options.append(
            SQLTemplateOption(
                key="numeric_summary",
                label="Numeric summary",
                detail=f"Summarize {first_numeric.name}.",
                sql=(
                    "SELECT\n"
                    "  COUNT(*) AS rows,\n"
                    f"  COUNT({numeric_name}) AS {non_null_alias},\n"
                    f"  MIN({numeric_name}) AS {min_alias},\n"
                    f"  AVG({numeric_name}) AS {avg_alias},\n"
                    f"  MAX({numeric_name}) AS {max_alias},\n"
                    f"  SUM({numeric_name}) AS {sum_alias}\n"
                    f"FROM {qualified_source};"
                ),
                requires_columns=True,
            )
        )

    first_text = _first_column_of_kind(selected_source.columns, "text")
    if first_text is not None:
        text_name = _qualified_range_column(range_alias, first_text.name)
        options.append(
            SQLTemplateOption(
                key="text_grouping",
                label="Group by category",
                detail=f"Count rows by {first_text.name}.",
                sql=(
                    "SELECT\n"
                    f"  {text_name},\n"
                    "  COUNT(*) AS rows\n"
                    f"FROM {qualified_source}\n"
                    f"GROUP BY {text_name}\n"
                    "ORDER BY rows DESC\n"
                    "LIMIT 20;"
                ),
                requires_columns=True,
            )
        )

    first_date = _first_column_of_kind(selected_source.columns, "date_trend")
    if first_date is not None:
        date_name = _qualified_range_column(range_alias, first_date.name)
        options.append(
            SQLTemplateOption(
                key="date_trend",
                label="Date/month trend",
                detail=f"Trend rows by {first_date.name}.",
                sql=(
                    "SELECT\n"
                    f"  date_trunc('month', {date_name}) AS month,\n"
                    "  COUNT(*) AS rows\n"
                    f"FROM {qualified_source}\n"
                    "GROUP BY month\n"
                    "ORDER BY month;"
                ),
                requires_columns=True,
            )
        )

    first_column = selected_source.columns[0]
    non_null_alias = make_output_alias("non_null", first_column.name, used_aliases)
    null_alias = make_output_alias("null", first_column.name, used_aliases)
    first_name = _qualified_range_column(range_alias, first_column.name)
    options.append(
        SQLTemplateOption(
            key="missingness",
            label="Missingness profile",
            detail=f"Profile nulls for {first_column.name}.",
            sql=(
                "SELECT\n"
                "  COUNT(*) AS rows,\n"
                f"  COUNT({first_name}) AS {non_null_alias},\n"
                f"  COUNT(*) - COUNT({first_name}) AS {null_alias}\n"
                f"FROM {qualified_source};"
            ),
            requires_columns=True,
        )
    )

    join_options = _join_template_options(sources, selected_source)
    options.extend(join_options)
    return tuple(options)


def build_completion_items(
    sources: Sequence[SQLAssistSource],
    *,
    text: str,
    cursor_index: int,
) -> tuple[SQLCompletionItem, ...]:
    """Build completion items from current SQL text and loaded metadata."""

    token_start, token_prefix = _token_prefix(text, cursor_index)
    del token_start
    qualifier, member_prefix = _split_qualifier(token_prefix)
    if qualifier is not None:
        qualified_source = _source_for_qualifier(sources, qualifier)
        if qualified_source is None:
            return ()
        return tuple(
            item
            for item in _column_completion_items(
                qualified_source.columns,
                source_name=qualified_source.name,
                force_qualified=True,
            )
            if _matches_prefix(item, member_prefix)
        )

    items: list[SQLCompletionItem] = []
    for source in sources:
        rendered_name = render_duckdb_identifier(source.name)
        items.append(
            SQLCompletionItem(
                key=f"source:{source.name}",
                label=source.name,
                detail="Source alias/table name",
                insert_text=rendered_name,
                item_kind="source",
            )
        )

    multiple_sources = len(sources) > 1
    for source in sources:
        items.extend(
            _column_completion_items(
                source.columns,
                source_name=source.name,
                force_qualified=multiple_sources,
            )
        )

    for keyword in _KEYWORDS:
        items.append(
            SQLCompletionItem(
                key=f"keyword:{keyword}",
                label=keyword,
                detail="SQL keyword",
                insert_text=keyword,
                item_kind="keyword",
            )
        )

    for key, label, insert_text in _KEYWORD_SNIPPETS:
        items.append(
            SQLCompletionItem(
                key=f"snippet:{key}",
                label=label,
                detail="SQL snippet",
                insert_text=insert_text,
                item_kind="snippet",
            )
        )

    return tuple(item for item in items if _matches_prefix(item, token_prefix))


def completion_edit(
    text: str,
    selection_start: int,
    selection_end: int,
    item: SQLCompletionItem,
) -> CompletionEdit:
    """Build the editor replacement span for a selected completion item."""

    if selection_start != selection_end:
        return CompletionEdit(
            start_index=selection_start,
            end_index=selection_end,
            replacement=item.insert_text,
        )

    token_start, _prefix = _token_prefix(text, selection_end)
    return CompletionEdit(
        start_index=token_start,
        end_index=selection_end,
        replacement=item.insert_text,
    )


def _sanitize_identifier_stem(stem: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]+", "_", stem.strip().lower()).strip("_")
    return sanitized


def _unique_generated_identifier(base: str, used_aliases: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used_aliases:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_aliases.add(candidate)
    return candidate


def _columns_for_source(
    columns_by_source: Mapping[str, Sequence[TUISourceColumn]],
    source_name: str,
) -> Sequence[TUISourceColumn]:
    if source_name in columns_by_source:
        return columns_by_source[source_name]
    folded_name = source_name.casefold()
    for key, columns in columns_by_source.items():
        if key.casefold() == folded_name:
            return columns
    return ()


def _first_column_of_kind(
    columns: Sequence[SQLAssistColumn],
    kind: ColumnKind,
) -> SQLAssistColumn | None:
    return next((column for column in columns if column.kind == kind), None)


def _qualified_range_column(range_alias: str, column_name: str) -> str:
    return f"{range_alias}.{render_duckdb_identifier(column_name)}"


def _join_template_options(
    sources: Sequence[SQLAssistSource],
    selected_source: SQLAssistSource,
) -> tuple[SQLTemplateOption, ...]:
    selected_column_names = {column.name for column in selected_source.columns}
    if not selected_column_names:
        return ()

    aliases = make_range_aliases(tuple(source.name for source in sources))
    left_alias = aliases[selected_source.name]
    left_name = render_duckdb_identifier(selected_source.name)
    options: list[SQLTemplateOption] = []
    used_keys: set[str] = set()
    for other_source in sources:
        if other_source.name == selected_source.name or not other_source.columns:
            continue
        other_column_names = {item.name for item in other_source.columns}
        shared_column = next(
            (
                column.name
                for column in selected_source.columns
                if column.name in other_column_names
            ),
            None,
        )
        if shared_column is None:
            continue
        right_alias = aliases[other_source.name]
        right_name = render_duckdb_identifier(other_source.name)
        rendered_column = render_duckdb_identifier(shared_column)
        base_key = f"join_{safe_generated_identifier(shared_column, reserved_prefix='col_')}"
        option_key = base_key
        if option_key in used_keys:
            option_key = (
                f"{base_key}_{safe_generated_identifier(other_source.name, reserved_prefix='t_')}"
            )
        if option_key in used_keys:
            dedupe_base = option_key
            suffix = 2
            while option_key in used_keys:
                option_key = f"{dedupe_base}_{suffix}"
                suffix += 1
        used_keys.add(option_key)
        options.append(
            SQLTemplateOption(
                key=option_key,
                label=f"Join on {shared_column}",
                detail=f"Join {selected_source.name} to {other_source.name}.",
                sql=(
                    "SELECT *\n"
                    f"FROM {left_name} AS {left_alias}\n"
                    f"JOIN {right_name} AS {right_alias}\n"
                    f"  ON {left_alias}.{rendered_column} = {right_alias}.{rendered_column}\n"
                    "LIMIT 50;"
                ),
                requires_columns=True,
            )
        )
    return tuple(options)


def _split_qualifier(token_prefix: str) -> tuple[str | None, str]:
    if "." not in token_prefix:
        return None, token_prefix
    qualifier, member_prefix = token_prefix.rsplit(".", maxsplit=1)
    return qualifier, member_prefix


def _source_for_qualifier(
    sources: Sequence[SQLAssistSource],
    qualifier: str,
) -> SQLAssistSource | None:
    for source in sources:
        if qualifier in {source.name, render_duckdb_identifier(source.name)}:
            return source
    return None


def _column_completion_items(
    columns: Sequence[SQLAssistColumn],
    *,
    source_name: str,
    force_qualified: bool,
) -> list[SQLCompletionItem]:
    items: list[SQLCompletionItem] = []
    rendered_source = render_duckdb_identifier(source_name)
    for column in columns:
        rendered_column = render_duckdb_identifier(column.name)
        insert_text = f"{rendered_source}.{rendered_column}" if force_qualified else column.name
        items.append(
            SQLCompletionItem(
                key=f"column:{source_name}:{column.name}",
                label=column.name,
                detail=f"{source_name} {column.duckdb_type}",
                insert_text=insert_text,
                item_kind="column",
            )
        )
    return items


def _matches_prefix(item: SQLCompletionItem, token_prefix: str) -> bool:
    if not token_prefix:
        return True
    normalized_prefix = token_prefix.casefold()
    candidates = {
        item.label.casefold(),
        item.insert_text.casefold(),
        item.insert_text.replace('"', "").casefold(),
    }
    return any(candidate.startswith(normalized_prefix) for candidate in candidates)


def _token_prefix(text: str, cursor_index: int) -> tuple[int, str]:
    start_index = cursor_index
    while start_index > 0 and _TOKEN_PREFIX_PATTERN.fullmatch(text[start_index - 1]):
        start_index -= 1
    return start_index, text[start_index:cursor_index]
