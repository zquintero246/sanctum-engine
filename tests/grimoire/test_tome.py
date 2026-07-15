"""Tests for Spell schema inference and Tome loading.

Covers the @spell decorator's JSON-schema inference from type hints and
docstrings, load_from_directory over an AgentGrimoire-style fixture, and
manifest validation errors.
"""

import json
from pathlib import Path

import pytest

from sanctum.grimoire import SpellExecutionError, Tome, spell

FIXTURES = Path(__file__).parent / "fixtures" / "agentgrimoire"


def test_spell_decorator_infers_schema_from_type_hints() -> None:
    @spell
    def transcribe(text: str, times: int = 1, precise: bool = False) -> str:
        """Repeat a text a number of times."""
        return " ".join([text] * times)

    schema = transcribe.schema()
    assert schema["name"] == "transcribe"
    assert schema["description"] == "Repeat a text a number of times."
    parameters = schema["parameters"]
    assert parameters["type"] == "object"
    assert parameters["properties"]["text"] == {"type": "string"}
    assert parameters["properties"]["times"] == {"type": "integer", "default": 1}
    assert parameters["properties"]["precise"] == {
        "type": "boolean",
        "default": False,
    }
    assert parameters["required"] == ["text"]
    # The decorated object remains directly callable.
    assert transcribe("lux", times=2) == "lux lux"


async def test_load_from_directory_reads_agentgrimoire_layout() -> None:
    tome = Tome.load_from_directory(FIXTURES)

    assert sorted(entry.name for entry in tome) == ["shout", "word_count"]

    word_count = tome.get("word_count")
    assert word_count.description == "Count the words in a text."
    assert word_count.parameters["required"] == ["text"]
    assert await word_count.execute({"text": "lux aeterna"}) == 2

    # shout's manifest has no `parameters`: inferred from the type hints
    # of its @spell-decorated entrypoint.
    shout = tome.get("shout")
    assert shout.parameters["properties"]["text"] == {"type": "string"}
    assert await shout.execute({"text": "fiat"}) == "FIAT!"


def test_tome_get_unknown_spell_raises_spell_execution_error() -> None:
    tome = Tome()
    with pytest.raises(SpellExecutionError, match="'phantom'"):
        tome.get("phantom")


async def test_spell_execute_wraps_failures() -> None:
    @spell
    def doomed(text: str) -> str:
        """Always fails."""
        raise ValueError("the stars are wrong")

    with pytest.raises(SpellExecutionError) as excinfo:
        await doomed.execute({"text": "x"})
    assert excinfo.value.spell == "doomed"
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_generic_hints_map_to_json_types() -> None:
    @spell
    def gather(items: list[str], weights: dict[str, int] | None = None) -> list:
        """Gather items with optional weights."""
        return items

    properties = gather.parameters["properties"]
    assert properties["items"]["type"] == "array"
    # A union hint has no single JSON type: the property stays open.
    assert "type" not in properties["weights"]
    assert gather.parameters["required"] == ["items"]


def test_register_duplicate_spell_raises() -> None:
    @spell
    def once(text: str) -> str:
        """Only once."""
        return text

    tome = Tome([once])
    with pytest.raises(ValueError, match="already"):
        tome.register(once)


def test_loader_rejects_manifest_missing_required_field(tmp_path: Path) -> None:
    spell_dir = tmp_path / "domain" / "broken"
    spell_dir.mkdir(parents=True)
    (spell_dir / "spell.json").write_text(json.dumps({"name": "broken"}))
    with pytest.raises(ValueError, match="entrypoint"):
        Tome.load_from_directory(tmp_path)


def test_loader_rejects_malformed_entrypoint(tmp_path: Path) -> None:
    spell_dir = tmp_path / "domain" / "broken"
    spell_dir.mkdir(parents=True)
    (spell_dir / "spell.json").write_text(
        json.dumps({"name": "broken", "entrypoint": "spell.py"})
    )
    with pytest.raises(ValueError, match="malformed"):
        Tome.load_from_directory(tmp_path)


def test_loader_rejects_missing_entrypoint_attribute(tmp_path: Path) -> None:
    spell_dir = tmp_path / "domain" / "broken"
    spell_dir.mkdir(parents=True)
    (spell_dir / "spell.json").write_text(
        json.dumps({"name": "broken", "entrypoint": "spell.py:missing"})
    )
    (spell_dir / "spell.py").write_text("present = True\n")
    with pytest.raises(ValueError, match="no attribute 'missing'"):
        Tome.load_from_directory(tmp_path)
