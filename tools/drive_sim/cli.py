from __future__ import annotations

import argparse
from pathlib import Path

from .board_data import load_board_data, supported_board_revs
from .render import render_report
from .scenarios import run_board_scenarios, run_demo_scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description="Run virtual robot drive simulator scenarios")
    parser.add_argument("--demo", action="store_true", help="run generic built-in demo scenarios instead of board-derived scenarios")
    parser.add_argument("--board-rev", type=int, default=2, choices=supported_board_revs(), help="BOARD_REV to load from components/board_config/include/board_config.h")
    parser.add_argument("--out", default="artifacts/drive-sim/latest.html", help="HTML report output path")
    parser.add_argument("--dt", type=float, default=0.02, help="simulation timestep in seconds")
    args = parser.parse_args()

    board = None
    if args.demo:
        results = run_demo_scenarios(dt_s=args.dt)
    else:
        board = load_board_data(args.board_rev)
        results = run_board_scenarios(board, dt_s=args.dt)
    output = render_report(results, Path(args.out))
    passed = sum(1 for result in results if result.passed)
    total = len(results)
    print(f"drive-sim: {passed}/{total} scenarios passed")
    if board is not None:
        print(f"board: {board.summary}")
    print(f"report: {output}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
