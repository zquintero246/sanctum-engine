"""Grimoire — the book of Spells the entities may cast.

Tools and tool registries. A Spell is a callable with a JSON schema,
declared with the `@spell` decorator (schema inferred from type hints and
docstring). A Tome is a registry of Spells and can be loaded by convention
from a directory layout compatible with AgentGrimoire
(`Tome.load_from_directory`). `summon` binds an Oracle to a Tome and seals
the canonical ReAct loop as a ready-to-invoke Rite.
"""

from sanctum.grimoire.core import Spell, Tome, spell
from sanctum.grimoire.errors import SpellCallParseError, SpellExecutionError
from sanctum.grimoire.repair import RepairOutcome, repair_spell_call
from sanctum.grimoire.summon import summon

__all__ = [
    "RepairOutcome",
    "Spell",
    "SpellCallParseError",
    "SpellExecutionError",
    "Tome",
    "repair_spell_call",
    "spell",
    "summon",
]
