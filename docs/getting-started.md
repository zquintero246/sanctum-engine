# Getting started

*Draw the circle, bind the Sigils, perform the Rite — five minutes from
install to a local model casting tools.*

## Install

```sh
pip install sanctum-engine                  # core: zero dependencies
pip install "sanctum-engine[openai-compat]" # + httpx, for local model servers
```

## Your first Ritual (no model needed)

A **Ritual** is a graph builder; **Sigils** are nodes — plain callables
that receive the full state (the **Aether**) and return a partial delta.
`compile()` validates the graph and returns an executable **Rite**:

```python
from sanctum import END, Ritual

ritual = Ritual()
ritual.add_sigil("cleanse", lambda aether: {"text": aether["text"].strip()})
ritual.add_sigil("transmute", lambda aether: {"text": aether["text"].upper()})
ritual.set_entry_point("cleanse")
ritual.add_edge("cleanse", "transmute")
ritual.add_edge("transmute", END)

rite = ritual.compile()
print(rite.invoke({"text": "  fiat lux  "}))
# {'text': 'FIAT LUX'}
```

## An agent on Ollama, with a tool

Install [Ollama](https://ollama.com), pull a model
(`ollama pull qwen2.5:7b`), and summon an Entity — an Oracle bound to a
Tome of Spells, sealed into the canonical ReAct loop:

```python
import asyncio
from sanctum import Tome, spell, summon
from sanctum.oracle.ollama import OllamaOracle

@spell
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())

entity = summon(
    OllamaOracle(arcana="qwen2.5:7b"),
    Tome([word_count]),
    role="You are a scribe. Use your Spells when counting.",
)
result = asyncio.run(entity.ainvoke({"messages": [
    {"role": "user", "content": "How many words in 'fiat lux'?"},
]}))
print(result["messages"][-1]["content"])
```

If your model has no native tool support, pass
`spell_calling="prompted"` (or `"auto"`) to `summon` — see
[Robust tool-calling](guides/robust-tool-calling.md).

## Where to go next

- The [examples gallery](https://github.com/zquintero246/sanctum-engine/tree/main/examples)
  runs entirely on scripted oracles by default — no model required.
- [Concepts](concepts/ritual.md) explain each piece of the vocabulary.
- [Guides](guides/human-in-the-loop.md) cover pausing for humans,
  time-travel, tool-calling with small models, and tracing.
