"""Chat with a tool in thirty lines — the Sanctum quickstart.

Runs on a scripted Oracle by default (no model needed); pass
``--oracle ollama`` to consult a local Ollama server instead.

    python examples/quickstart_ollama.py
    python examples/quickstart_ollama.py --oracle ollama --arcana qwen2.5:7b
"""

import argparse
import asyncio

from sanctum import Tome, spell, summon
from sanctum.oracle import Oracle, OracleResponse, ScriptedOracle, SpellCall


@spell
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())


def build_oracle(kind: str, arcana: str) -> Oracle:
    if kind == "ollama":
        from sanctum.oracle.ollama import OllamaOracle

        return OllamaOracle(arcana=arcana)
    return ScriptedOracle(
        [
            OracleResponse(
                text="",
                spell_calls=[
                    SpellCall(spell="word_count", arguments={"text": "fiat lux"})
                ],
            ),
            OracleResponse(text="'fiat lux' has two words."),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", choices=["scripted", "ollama"], default="scripted")
    parser.add_argument("--arcana", default="qwen2.5:7b")
    args = parser.parse_args()

    entity = summon(
        build_oracle(args.oracle, args.arcana),
        Tome([word_count]),
        role="You are a scribe. Use your Spells when counting.",
        spell_calling="auto",  # prompted fallback if the model lacks tools
    )
    result = asyncio.run(
        entity.ainvoke(
            {"messages": [{"role": "user", "content": "How many words in 'fiat lux'?"}]}
        )
    )
    for message in result["messages"]:
        print(f"[{message['role']:>9}] {message['content']}")


if __name__ == "__main__":
    main()
