"""Two entities scout in parallel; a third distills what they brought back.

Demonstrates the engine's multi-agent primitives: static fan-out (both
scouts run concurrently in one superstep), the `append` reducer gathering
their findings deterministically, and fan-in into a synthesizer. Scripted
by default; ``--oracle ollama`` consults a local model instead.

    python examples/research_ritual/main.py
    python examples/research_ritual/main.py --oracle ollama --arcana qwen2.5:7b
"""

import argparse
import asyncio
from typing import Any

from sanctum import END, AetherSchema, Conduit, Ritual
from sanctum.aether import append
from sanctum.oracle import Oracle, ScriptedOracle

Aether = dict[str, Any]

QUESTION = "Why do local-first systems keep working offline?"


def build_oracles(kind: str, arcana: str) -> dict[str, Oracle]:
    if kind == "ollama":
        from sanctum.oracle.ollama import OllamaOracle

        names = ("alpha", "beta", "synth")
        return {name: OllamaOracle(arcana=arcana) for name in names}
    return {
        "alpha": ScriptedOracle(
            ["Local-first systems keep authoritative data on the device."]
        ),
        "beta": ScriptedOracle(
            ["Synchronization is an optimization, not a requirement."]
        ),
        "synth": ScriptedOracle(
            [
                "Offline resilience follows from two properties: data lives "
                "locally, and the network only accelerates what already works."
            ]
        ),
    }


def build_ritual(oracles: dict[str, Oracle]) -> Ritual:
    def scout(name: str, angle: str):
        async def sigil(aether: Aether) -> Aether:
            response = await oracles[name].generate(
                [
                    {"role": "system", "content": f"Answer in one sentence, {angle}."},
                    {"role": "user", "content": aether["question"]},
                ]
            )
            return {"findings": [f"[{name}] {response.text}"]}

        return sigil

    async def synthesize(aether: Aether) -> Aether:
        response = await oracles["synth"].generate(
            [
                {"role": "system", "content": "Distill the findings into one answer."},
                {"role": "user", "content": "\n".join(aether["findings"])},
            ]
        )
        return {"synthesis": response.text}

    ritual = Ritual(
        AetherSchema(
            {
                "question": Conduit(),
                "findings": Conduit(reducer=append),
                "synthesis": Conduit(),
            }
        )
    )
    ritual.add_sigil("scout_alpha", scout("alpha", "from a data-ownership angle"))
    ritual.add_sigil("scout_beta", scout("beta", "from a networking angle"))
    ritual.add_sigil("synthesize", synthesize)
    ritual.set_entry_point("scout_alpha")
    ritual.set_entry_point("scout_beta")  # fan-out: both scouts, one superstep
    ritual.add_edge("scout_alpha", "synthesize")
    ritual.add_edge("scout_beta", "synthesize")  # fan-in: runs once
    ritual.add_edge("synthesize", END)
    return ritual


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", choices=["scripted", "ollama"], default="scripted")
    parser.add_argument("--arcana", default="qwen2.5:7b")
    args = parser.parse_args()

    rite = build_ritual(build_oracles(args.oracle, args.arcana)).compile()
    result = asyncio.run(rite.ainvoke({"question": QUESTION, "findings": []}))

    print(f"question : {QUESTION}")
    for finding in result["findings"]:
        print(f"finding  : {finding}")
    print(f"synthesis: {result['synthesis']}")


if __name__ == "__main__":
    main()
