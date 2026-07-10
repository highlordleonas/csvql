import pytest
from rich.text import Text

from csvql import terminal_text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("\x1b]0;spoof\x07", r"\x1b]0;spoof\x07"),
        ("\x1b[31mred\x1b[0m", r"\x1b[31mred\x1b[0m"),
        ("\x00\x1f\x7f\x85\x9b", r"\x00\x1f\x7f\x85\x9b"),
        (None, ""),
    ],
)
def test_terminal_safe_text_encodes_terminal_controls(
    value: object,
    expected: str,
) -> None:
    terminal_safe_text = getattr(terminal_text, "terminal_safe_text", None)

    assert terminal_safe_text is not None
    assert terminal_safe_text(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "[red]styled[/red]",
        "[link=https://example.invalid]linked[/link]",
        "[[escaped]]",
        "[red]malformed",
    ],
)
def test_literal_terminal_text_preserves_markup_as_unstyled_text(value: str) -> None:
    literal_terminal_text = getattr(terminal_text, "literal_terminal_text", None)

    assert literal_terminal_text is not None
    rendered = literal_terminal_text(value)
    assert isinstance(rendered, Text)
    assert rendered.plain == value
    assert rendered.spans == []
