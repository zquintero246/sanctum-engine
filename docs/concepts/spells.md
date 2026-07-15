# Spells & Tomes

*A Spell is one thing the entity knows how to do; the Tome is the book
that binds them.*

Technically: a **Spell** is a tool — a callable plus the JSON schema
(name, description, parameters) an Oracle reasons about. The `@spell`
decorator infers the schema from type hints and the docstring:

```python
from sanctum import Tome, spell

@spell
def word_count(text: str, precise: bool = False) -> int:
    """Count the words in a text."""
    return len(text.split())

tome = Tome([word_count])
tome.schemas()   # what the Oracle sees
```

Defaults become optional properties; `str/int/float/bool/list/dict` (and
their generics) map to JSON types. The decorated object stays directly
callable; `await spell_obj.execute(arguments)` casts it with failures
wrapped in `SpellExecutionError` (carrying `.spell` and the original as
`__cause__`).

A **Tome** is the ordered registry handed to an Entity. Requesting an
unknown Spell raises `SpellExecutionError` too — deliberately, so the
ReAct loop turns it into a correction message instead of a crash.

## Loading from a directory (AgentGrimoire convention)

`Tome.load_from_directory(path)` reads a folder-per-Spell tree:

```
grimoire/
  text/
    word_count/
      spell.json      # {"name", "entrypoint": "spell.py:word_count",
      spell.py        #  optional "description"/"parameters"}
```

Manifest fields missing fall back to what the entrypoint's hints and
docstring infer; the entrypoint may be a plain function or already
`@spell`-decorated. The full convention is documented on
`Tome.load_from_directory` and proposed for the
[AgentGrimoire](https://github.com/zquintero246/AgentGrimoire) ecosystem.

`summon(oracle, tome, role)` binds it all into the canonical ReAct loop —
built entirely on the public primitives.
