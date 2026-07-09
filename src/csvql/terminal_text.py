"""Safe rendering of untrusted values for terminal-facing output."""


def sanitize_terminal_text(text: str) -> str:
    """Encode terminal control characters so displayed values cannot control the terminal."""

    return "".join(
        f"\\x{ord(character):02x}"
        if ord(character) <= 0x1F or 0x7F <= ord(character) <= 0x9F
        else character
        for character in text
    )
