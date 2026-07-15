"""Chat with a tool in thirty lines — the Sanctum quickstart.

Runs on a scripted Oracle by default (no model needed). Point it at a
real local model with ``--oracle ollama`` (native Ollama daemon) or
``--oracle openai-compat`` plus ``--base-url`` (any /v1/chat/completions
server: llama.cpp's llama-server, Ollama /v1, vLLM, LM Studio).

    python examples/quickstart_ollama.py
    python examples/quickstart_ollama.py --oracle ollama --arcana qwen2.5:7b
    python examples/quickstart_ollama.py --oracle openai-compat \\
        --base-url http://127.0.0.1:8080/v1
"""

import argparse
import asyncio

from sanctum import Tome, spell, summon
from sanctum.oracle import Oracle, OracleResponse, ScriptedOracle, SpellCall


@spell
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())


def build_oracle(kind: str, arcana: str, base_url: str) -> Oracle:
    if kind == "ollama":
        from sanctum.oracle.ollama import OllamaOracle

        return OllamaOracle(arcana=arcana)
    if kind == "openai-compat":
        from sanctum.oracle.openai_compat import OpenAICompatibleOracle

        return OpenAICompatibleOracle(arcana=arcana, base_url=base_url)
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
    parser.add_argument(
        "--oracle",
        choices=["scripted", "ollama", "openai-compat"],
        default="scripted",
    )
    parser.add_argument("--arcana", default="qwen2.5:7b")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    args = parser.parse_args()

    entity = summon(
        build_oracle(args.oracle, args.arcana, args.base_url),
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
