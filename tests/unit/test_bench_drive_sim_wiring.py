from __future__ import annotations

from pathlib import Path

BENCH = Path("tools/bench_e2e.py")


def test_bench_e2e_exposes_drive_sim_flags_and_runner():
    src = BENCH.read_text()
    assert "--drive-sim" in src
    assert "--drive-sim-only" in src
    assert "--drive-sim-out" in src
    assert "def run_drive_sim_tests" in src
    assert "simulate_status_samples" in src
    assert "render_report(results, out_path)" in src


def test_bench_drive_sim_uses_fast_status_sampling():
    src = BENCH.read_text()
    assert "def robot_status(robot: SerialCli, seconds: float = 1.0)" in src
    assert "robot_status(robot, seconds=0.15)" in src
