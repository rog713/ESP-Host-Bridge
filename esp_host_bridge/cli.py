from __future__ import annotations

import argparse
import sys
from typing import Optional

from .agent import agent_arg_parser, run_agent
from .webui import run_webui, webui_arg_parser


def parse_mode_and_args(argv: list[str]) -> tuple[str, argparse.Namespace]:
    if len(argv) <= 1:
        return "webui", webui_arg_parser().parse_args([])

    mode = argv[1].lower()
    if mode == "agent":
        return "agent", agent_arg_parser().parse_args(argv[2:])
    if mode == "webui":
        return "webui", webui_arg_parser().parse_args(argv[2:])

    if any(a.startswith("--") for a in argv[1:]):
        return "agent", agent_arg_parser().parse_args(argv[1:])

    raise SystemExit("Usage: esp-host-bridge [webui|agent] [options]")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    mode, args = parse_mode_and_args(argv)
    if mode == "agent":
        return run_agent(args)
    return run_webui(args)


__all__ = ["main", "parse_mode_and_args"]
