"""Timeouts, retries with backoff, and a fallback Sigil in one pipeline.

Three failure modes, one run: `unstable_fetch` fails twice and is retried
until it succeeds; `slow_augur` sleeps past its timeout and is diverted to
`swift_augur` via on_error (reading the failure from the reserved
``__errors__`` Conduit); `chronicler` consults the Oracle to summarize.
Watch the SigilRetried Omens stream by. Scripted by default;
``--oracle ollama`` summarizes with a local model.

    python examples/resilient_pipeline/main.py
    python examples/resilient_pipeline/main.py --oracle ollama
"""

import argparse
import asyncio
from typing import Any

from sanctum import END, Ritual, SigilPolicy
from sanctum.omens import RiteManifested, SigilRetried
from sanctum.oracle import Oracle, ScriptedOracle

Aether = dict[str, Any]


def build_oracle(kind: str, arcana: str) -> Oracle:
    if kind == "ollama":
        from sanctum.oracle.ollama import OllamaOracle

        return OllamaOracle(arcana=arcana)
    return ScriptedOracle(
        ["The omens were read despite two misfires and one silence."]
    )


def build_ritual(oracle: Oracle) -> Ritual:
    attempts = {"count": 0}

    def unstable_fetch(aether: Aether) -> Aether:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError(f"misfire #{attempts['count']}")
        return {"fetched": "the raw omens"}

    async def slow_augur(aether: Aether) -> Aether:
        await asyncio.sleep(5)  # never finishes within its 0.3s timeout
        return {"reading": "unreachable"}

    def swift_augur(aether: Aether) -> Aether:
        failure = aether["__errors__"][-1]
        return {"reading": f"fallback reading (after {failure['type']})"}

    async def chronicler(aether: Aether) -> Aether:
        report = f"{aether['fetched']}; {aether['reading']}"
        response = await oracle.generate(
            [
                {"role": "system", "content": "Summarize the run in one sentence."},
                {"role": "user", "content": report},
            ]
        )
        return {"chronicle": response.text}

    ritual = Ritual()
    ritual.add_sigil(
        "unstable_fetch",
        unstable_fetch,
        policy=SigilPolicy(retries=3, backoff=lambda attempt: 0.05),
    )
    ritual.add_sigil(
        "slow_augur",
        slow_augur,
        policy=SigilPolicy(timeout=0.3, on_error="swift_augur"),
    )
    ritual.add_sigil("swift_augur", swift_augur)
    ritual.add_sigil("chronicler", chronicler)
    ritual.set_entry_point("unstable_fetch")
    ritual.add_edge("unstable_fetch", "slow_augur")
    ritual.add_edge("slow_augur", "chronicler")
    ritual.add_edge("swift_augur", "chronicler")
    ritual.add_edge("chronicler", END)
    return ritual


async def run(oracle: Oracle) -> None:
    rite = build_ritual(oracle).compile()
    async for omen in rite.astream({}, mode="omens"):
        if isinstance(omen, SigilRetried):
            print(f"retry {omen.attempt} of '{omen.sigil}': {omen.cause}")
        elif isinstance(omen, RiteManifested):
            aether = omen.aether
            print(f"errors   : {aether['__errors__']}")
            print(f"reading  : {aether['reading']}")
            print(f"chronicle: {aether['chronicle']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", choices=["scripted", "ollama"], default="scripted")
    parser.add_argument("--arcana", default="qwen2.5:7b")
    args = parser.parse_args()
    asyncio.run(run(build_oracle(args.oracle, args.arcana)))


if __name__ == "__main__":
    main()
