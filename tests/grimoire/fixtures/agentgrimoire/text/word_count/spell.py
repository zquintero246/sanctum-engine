"""word_count — a plain-function Spell (schema comes from the manifest)."""


def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())
