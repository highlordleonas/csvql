"""SQL editor text helpers for the CSVQL menu TUI."""

Location = tuple[int, int]


def selected_or_current_sql(
    text: str,
    *,
    cursor_location: Location,
    selected_text: str,
) -> str:
    """Return selected SQL, or the current semicolon-delimited statement."""

    selected_sql = selected_text.strip()
    if selected_sql:
        return selected_sql
    return current_statement_at_offset(text, _offset_for_location(text, cursor_location))


def current_statement_at_offset(text: str, cursor_offset: int) -> str:
    """Return the statement around a text offset, ignoring semicolons inside SQL literals."""

    bounded_offset = max(0, min(cursor_offset, len(text)))
    segments = _statement_segments(text)
    current_segment_index = len(segments) - 1
    for index, (_, end_offset) in enumerate(segments):
        if bounded_offset <= end_offset:
            current_segment_index = index
            break

    statement = _segment_text(text, segments[current_segment_index])
    if statement:
        return statement

    for index in range(current_segment_index - 1, -1, -1):
        statement = _segment_text(text, segments[index])
        if statement:
            return statement

    return ""


def _statement_segments(text: str) -> tuple[tuple[int, int], ...]:
    segments: list[tuple[int, int]] = []
    statement_start = 0
    for separator_offset in _statement_separator_offsets(text):
        segments.append((statement_start, separator_offset))
        statement_start = separator_offset + 1
    segments.append((statement_start, len(text)))
    return tuple(segments)


def _segment_text(text: str, segment: tuple[int, int]) -> str:
    start_offset, end_offset = segment
    return text[start_offset:end_offset].strip()


def _offset_for_location(text: str, location: Location) -> int:
    row, column = location
    lines = text.splitlines(keepends=True)
    if not lines:
        return 0
    if row <= 0:
        return max(0, min(column, _line_body_length(lines[0])))
    if row >= len(lines):
        return len(text)

    offset = sum(len(line) for line in lines[:row])
    return offset + max(0, min(column, _line_body_length(lines[row])))


def _line_body_length(line: str) -> int:
    return len(line.rstrip("\r\n"))


def _statement_separator_offsets(text: str) -> tuple[int, ...]:
    separators: list[int] = []
    index = 0
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False

    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""

        if in_line_comment:
            if character == "\n":
                in_line_comment = False
            index += 1
            continue

        if in_block_comment:
            if character == "*" and next_character == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if in_single_quote:
            if character == "'" and next_character == "'":
                index += 2
                continue
            if character == "'":
                in_single_quote = False
            index += 1
            continue

        if in_double_quote:
            if character == '"' and next_character == '"':
                index += 2
                continue
            if character == '"':
                in_double_quote = False
            index += 1
            continue

        if character == "-" and next_character == "-":
            in_line_comment = True
            index += 2
            continue
        if character == "/" and next_character == "*":
            in_block_comment = True
            index += 2
            continue
        if character == "'":
            in_single_quote = True
            index += 1
            continue
        if character == '"':
            in_double_quote = True
            index += 1
            continue
        if character == ";":
            separators.append(index)
        index += 1

    return tuple(separators)
