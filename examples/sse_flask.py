"""Bridge Sanctum's astream to Server-Sent Events with Flask.

Flask is a dependency of this example only — the sanctum core stays
dependency-free.

    pip install flask sanctum-engine
    python examples/sse_flask.py
    curl -N "http://127.0.0.1:5000/invoke?question=what%20stirs"

Flask's request handlers are synchronous, while ``Rite.astream`` is an
async generator. The bridge runs the Invocation's event loop in a worker
thread and hands each Omen to the response generator through a
thread-safe queue, formatting it as an SSE frame
(``event: <OmenType>\\ndata: <json>\\n\\n``).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import queue
import threading
from collections.abc import Iterator
from typing import Any

from flask import Flask, Response, request

from sanctum import END, Rite, Ritual
from sanctum.omens import Omen

app = Flask(__name__)


def build_rite() -> Rite:
    """A small demonstration Ritual with a token-streaming Sigil."""

    async def ponder(aether: dict[str, Any], writer) -> dict[str, Any]:
        # Stands in for an Oracle: emits tokens as they are produced.
        for word in ("the", "aether", "stirs", "in", "answer"):
            await writer(word)
            await asyncio.sleep(0.2)
        return {"answer": "the aether stirs in answer"}

    def conclude(aether: dict[str, Any]) -> dict[str, Any]:
        return {"conclusion": f"{aether['question']} -> {aether['answer']}"}

    ritual = Ritual()
    ritual.add_sigil("ponder", ponder)
    ritual.add_sigil("conclude", conclude)
    ritual.set_entry_point("ponder")
    ritual.add_edge("ponder", "conclude")
    ritual.add_edge("conclude", END)
    return ritual.compile()


RITE = build_rite()


def sse_frames(rite: Rite, input: dict[str, Any]) -> Iterator[str]:
    """Yield the Invocation's Omens as SSE frames, live.

    Runs ``rite.astream`` on its own event loop in a daemon thread; Omens
    cross into Flask's synchronous world through a thread-safe queue. A
    None sentinel marks the end of the stream.
    """
    bridge: queue.Queue[Omen | None] = queue.Queue()

    def drive() -> None:
        async def pump() -> None:
            async for omen in rite.astream(input, mode={"updates", "tokens"}):
                bridge.put(omen)

        try:
            asyncio.run(pump())
        finally:
            bridge.put(None)

    threading.Thread(target=drive, daemon=True).start()
    while (omen := bridge.get()) is not None:
        payload = json.dumps(dataclasses.asdict(omen), default=str)
        yield f"event: {type(omen).__name__}\ndata: {payload}\n\n"


@app.route("/invoke")
def invoke() -> Response:
    question = request.args.get("question", "what stirs in the aether?")
    return Response(
        sse_frames(RITE, {"question": question}),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # threaded=True lets several SSE streams run at once.
    app.run(debug=True, threaded=True)
