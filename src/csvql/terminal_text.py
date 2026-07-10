"""Safe rendering of untrusted values for terminal-facing output."""

from rich.text import Text


def sanitize_terminal_text(text: str) -> str:
    """Encode terminal control characters so displayed values cannot control the terminal."""

    return "".join(
        f"\\x{ord(character):02x}"
        if ord(character) <= 0x1F or 0x7F <= ord(character) <= 0x9F
        else character
        for character in text
    )


def terminal_safe_text(value: object) -> str:
    """Return display text with terminal controls encoded visibly."""

    return sanitize_terminal_text("" if value is None else str(value))


def literal_terminal_text(value: object) -> Text:
    """Return control-safe Rich text that cannot be parsed as markup."""

    return Text(terminal_safe_text(value))
