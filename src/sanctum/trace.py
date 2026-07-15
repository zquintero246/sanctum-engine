"""Consulting the recorded signs from the command line.

Minimal CLI over the trace tools (stdlib argparse only)::

    python -m sanctum.trace render <file.sanctum-trace.json>

renders the trace into a self-contained HTML viewer next to it and prints
the output path.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from sanctum.omens import render_trace


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m sanctum.trace``."""
    parser = argparse.ArgumentParser(
        prog="python -m sanctum.trace",
        description="Tools for .sanctum-trace.json files.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    render = subcommands.add_parser(
        "render",
        help="render a trace into a self-contained HTML viewer",
    )
    render.add_argument("trace", help="path to a .sanctum-trace.json file")
    render.add_argument(
        "-o", "--output", default=None, help="output HTML path (default: alongside)"
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "render":
        print(render_trace(arguments.trace, arguments.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
