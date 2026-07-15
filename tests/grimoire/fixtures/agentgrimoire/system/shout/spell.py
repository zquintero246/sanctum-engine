"""shout — an @spell-decorated Spell (parameters inferred from hints)."""

from sanctum.grimoire import spell


@spell
def shout(text: str) -> str:
    """Uppercase a text and add an exclamation mark."""
    return text.upper() + "!"
