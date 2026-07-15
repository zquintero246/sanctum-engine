"""A ritual that pauses for human approval and resumes where it left off.

The `review` Sigil calls interrupt() until a human verdict lands in the
Aether; the Codex seals the pause so resumption — seconds or days later —
continues exactly where the ritual stopped. Scripted by default;
``--oracle ollama`` drafts with a local model. ``--approve`` skips the
interactive prompt (useful in CI).

    python examples/human_in_the_loop/main.py --approve
    python examples/human_in_the_loop/main.py --oracle ollama
"""

import argparse
import asyncio
from typing import Any

from sanctum import END, Interrupt, Ritual, interrupt
from sanctum.codex import MemoryCodex
from sanctum.oracle import Oracle, ScriptedOracle

Aether = dict[str, Any]

TOPIC = "why rituals beat DAGs for agent loops"


def build_oracle(kind: str, arcana: str) -> Oracle:
    if kind == "ollama":
        from sanctum.oracle.ollama import OllamaOracle

        return OllamaOracle(arcana=arcana)
    return ScriptedOracle(
        ["Cycles let an agent think, act, observe, and think again."]
    )


def build_ritual(oracle: Oracle) -> Ritual:
    async def draft(aether: Aether) -> Aether:
        response = await oracle.generate(
            [
                {"role": "system", "content": "Draft one sentence on the topic."},
                {"role": "user", "content": aether["topic"]},
            ]
        )
        return {"draft": response.text}

    def review(aether: Aether) -> Aether:
        if not aether.get("approved"):
            interrupt("awaiting human approval of the draft")
        return {"reviewed": True}

    ritual = Ritual()
    ritual.add_sigil("draft", draft)
    ritual.add_sigil("review", review)
    ritual.add_sigil("publish", lambda aether: {"published": aether["draft"]})
    ritual.set_entry_point("draft")
    ritual.add_edge("draft", "review")
    ritual.add_edge("review", "publish")
    ritual.add_edge("publish", END)
    return ritual


async def run(oracle: Oracle, auto_approve: bool) -> None:
    codex = MemoryCodex()
    rite = build_ritual(oracle).compile(codex=codex)

    try:
        await rite.ainvoke({"topic": TOPIC, "approved": False}, invocation_id="post-1")
    except Interrupt as pause:
        seal = await codex.get("post-1")
        assert seal is not None
        print(f"paused at '{pause.sigil}': {pause.reason}")
        print(f"draft under review: {seal.aether['draft']!r}")

    if auto_approve:
        verdict = True
        print("(--approve) verdict: approved")
    else:
        verdict = input("approve? [y/N] ").strip().lower().startswith("y")
    if not verdict:
        print("rejected — the Seal keeps the draft for another day.")
        return

    result = await rite.ainvoke(invocation_id="post-1", updates={"approved": True})
    print(f"published: {result['published']!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", choices=["scripted", "ollama"], default="scripted")
    parser.add_argument("--arcana", default="qwen2.5:7b")
    parser.add_argument("--approve", action="store_true", help="skip the prompt")
    args = parser.parse_args()
    asyncio.run(run(build_oracle(args.oracle, args.arcana), args.approve))


if __name__ == "__main__":
    main()
