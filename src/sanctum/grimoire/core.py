"""The Grimoire's pages: Spells, the @spell inscription, and the Tome.

Tool model and registry. A Spell wraps a callable with a JSON schema
(name, description, parameters) an Oracle can reason about. Spells are
declared with the ``@spell`` decorator — schema inferred from type hints
and the docstring — or loaded from an AgentGrimoire-style directory tree
via ``Tome.load_from_directory``. A Tome is the ordered registry of
Spells handed to an Entity.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_origin, get_type_hints

from sanctum.grimoire.errors import SpellExecutionError

_JSON_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass(frozen=True, slots=True)
class Spell:
    """One inscribed tool: a callable and the schema that describes it.

    `parameters` is a JSON Schema object describing the keyword arguments
    of `fn`, which may be sync or async. Instances stay callable —
    invoking the Spell directly calls `fn` unchanged.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)

    def schema(self) -> dict[str, Any]:
        """The JSON schema handed to Oracles: name, description, parameters."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    async def execute(self, arguments: Mapping[str, Any] | None = None) -> Any:
        """Cast the Spell with keyword arguments matching its schema.

        Awaits async callables transparently and returns the raw result.

        Raises:
            SpellExecutionError: If the underlying callable raises; the
                original exception is chained as ``__cause__``.
        """
        try:
            result = self.fn(**dict(arguments or {}))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise SpellExecutionError(
                f"Spell '{self.name}' failed: {type(exc).__name__}: {exc}",
                spell=self.name,
            ) from exc
        return result


def _infer_parameters(fn: Callable[..., Any]) -> dict[str, Any]:
    """Derive a JSON Schema for `fn`'s arguments from its type hints.

    str/int/float/bool/list/dict map to their JSON types (including bare
    generics like ``list[str]``); unhinted or unknown types get an
    unconstrained property. Parameters with defaults are optional and
    carry the default in the schema.
    """
    hints = get_type_hints(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in inspect.signature(fn).parameters.items():
        if name in ("self", "writer"):
            continue
        prop: dict[str, Any] = {}
        hint = hints.get(name)
        if hint in _JSON_TYPES:
            prop["type"] = _JSON_TYPES[hint]
        elif get_origin(hint) in _JSON_TYPES:
            prop["type"] = _JSON_TYPES[get_origin(hint)]
        if parameter.default is not inspect.Parameter.empty:
            prop["default"] = parameter.default
        else:
            required.append(name)
        properties[name] = prop
    return {"type": "object", "properties": properties, "required": required}


def _build_spell(
    fn: Callable[..., Any],
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> Spell:
    """Assemble a Spell from a callable, inferring what is not given."""
    doc = inspect.getdoc(fn)
    return Spell(
        name=name or fn.__name__,
        description=description or (doc.splitlines()[0] if doc else fn.__name__),
        parameters=parameters or _infer_parameters(fn),
        fn=fn,
    )


def spell(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Spell | Callable[[Callable[..., Any]], Spell]:
    """Inscribe a Python function as a Spell.

    Decorator, usable bare or with arguments::

        @spell
        def word_count(text: str) -> int:
            \"\"\"Count the words in a text.\"\"\"
            return len(text.split())

    The Spell's name defaults to the function name, the description to the
    docstring's first line, and `parameters` to a JSON Schema inferred
    from the type hints (defaults become optional properties). The
    decorated object is a Spell but remains directly callable.
    """

    def wrap(target: Callable[..., Any]) -> Spell:
        return _build_spell(target, name=name, description=description)

    return wrap(fn) if fn is not None else wrap


class Tome:
    """The bound collection of Spells an Entity may cast.

    Ordered registry keyed by Spell name (registration order is preserved
    and is the order Oracles see). Build it from Spell instances, register
    incrementally, or load a whole directory tree with
    ``load_from_directory``.
    """

    def __init__(self, spells: Iterable[Spell] = ()) -> None:
        self._spells: dict[str, Spell] = {}
        for entry in spells:
            self.register(entry)

    def register(self, spell: Spell) -> Tome:
        """Inscribe a Spell in the Tome; returns self for chaining.

        Raises:
            ValueError: If a Spell with the same name is already inscribed.
        """
        if spell.name in self._spells:
            raise ValueError(f"Spell '{spell.name}' is already in this Tome.")
        self._spells[spell.name] = spell
        return self

    def get(self, name: str) -> Spell:
        """Return the Spell inscribed under `name`.

        Raises:
            SpellExecutionError: If no such Spell exists — so the ReAct
                loop can surface an unknown-Spell request to the Oracle as
                an error message instead of crashing.
        """
        try:
            return self._spells[name]
        except KeyError:
            raise SpellExecutionError(
                f"Spell '{name}' is not inscribed in this Tome; known "
                f"Spells: {', '.join(self._spells) or '(none)'}.",
                spell=name,
            ) from None

    def schemas(self) -> list[dict[str, Any]]:
        """The JSON schemas of every Spell, in registration order."""
        return [entry.schema() for entry in self._spells.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._spells

    def __iter__(self) -> Iterator[Spell]:
        return iter(self._spells.values())

    def __len__(self) -> int:
        return len(self._spells)

    @classmethod
    def load_from_directory(cls, path: str | Path) -> Tome:
        """Load Spells from an AgentGrimoire-style directory tree.

        Proposed manifest convention for AgentGrimoire
        (github.com/zquintero246/AgentGrimoire): one folder per domain,
        one subfolder per Spell, each holding a ``spell.json`` manifest
        next to its implementation::

            <root>/
              text/                    # domain folders: text/, files/, ...
                word_count/
                  spell.json
                  spell.py
              system/
                shout/
                  spell.json
                  spell.py

        ``spell.json`` fields:

        - ``name`` (required): the Spell's name as exposed to Oracles.
        - ``entrypoint`` (required): ``"<file>.py:<function>"`` relative
          to the Spell's folder; the target may be a plain function or an
          ``@spell``-decorated Spell.
        - ``description`` (optional): falls back to the entrypoint's
          docstring first line.
        - ``parameters`` (optional): JSON Schema of the arguments; falls
          back to the schema inferred from the entrypoint's type hints.

        Raises:
            ValueError: If a manifest is missing required fields or its
                entrypoint cannot be resolved.
        """
        root = Path(path)
        tome = cls()
        for manifest_path in sorted(root.glob("*/*/spell.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for field_name in ("name", "entrypoint"):
                if field_name not in manifest:
                    raise ValueError(
                        f"Spell manifest {manifest_path} is missing the "
                        f"required field '{field_name}'."
                    )
            target = _resolve_entrypoint(manifest_path, manifest["entrypoint"])
            base = target if isinstance(target, Spell) else _build_spell(target)
            tome.register(
                Spell(
                    name=manifest["name"],
                    description=manifest.get("description", base.description),
                    parameters=manifest.get("parameters", base.parameters),
                    fn=base.fn,
                )
            )
        return tome


def _resolve_entrypoint(manifest_path: Path, entrypoint: str) -> Any:
    """Import ``<file>.py:<attribute>`` relative to the manifest's folder."""
    file_name, separator, attribute = entrypoint.partition(":")
    if not separator or not attribute:
        raise ValueError(
            f"Spell manifest {manifest_path} has a malformed entrypoint "
            f"'{entrypoint}'; expected '<file>.py:<function>'."
        )
    module_path = manifest_path.parent / file_name
    if not module_path.is_file():
        raise ValueError(
            f"Spell manifest {manifest_path} points to a missing file "
            f"'{file_name}'."
        )
    spec = importlib.util.spec_from_file_location(
        f"_sanctum_spell_{uuid.uuid4().hex}", module_path
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot import Spell module {module_path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return getattr(module, attribute)
    except AttributeError:
        raise ValueError(
            f"Spell module {module_path} has no attribute '{attribute}' "
            f"(from manifest {manifest_path})."
        ) from None
