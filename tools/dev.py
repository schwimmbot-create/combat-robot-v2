#!/usr/bin/env python
"""Cross-platform developer wrapper for combat-robot-v2.

Use this instead of hard-coding `.venv/bin/...` or `.venv\\Scripts\\...` in
shell snippets. It works from Linux, macOS, and Windows as long as Python is
available.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ENV = "esp32-c3-devkitc-02"
DEV_ENV = "esp32-c3-devkitc-02-dev"
DEFAULT_BAUD = 115200
PACKAGES = ("platformio", "pytest", "bleak")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_os(os_name: str | None = None) -> str:
    name = (os_name or os.name).lower()
    system = platform.system().lower() if os_name is None else name
    if name in {"nt", "windows", "win32"} or system.startswith("windows"):
        return "windows"
    if name in {"darwin", "mac", "macos"} or system == "darwin":
        return "darwin"
    return "linux"


def default_port(os_name: str | None = None) -> str:
    os_name = normalize_os(os_name)
    if os_name == "windows":
        return "COM6"
    if os_name == "darwin":
        return "/dev/cu.usbmodem1101"
    return "/dev/ttyACM0"


def venv_executable(root: Path, name: str, os_name: str | None = None) -> Path:
    os_name = normalize_os(os_name)
    exe = name
    if os_name == "windows" and not exe.endswith(".exe"):
        exe += ".exe"
    bin_dir = "Scripts" if os_name == "windows" else "bin"
    return root / ".venv" / bin_dir / exe


def venv_python(root: Path, os_name: str | None = None) -> Path:
    return venv_executable(root, "python", os_name)


def get_env(default: str = DEFAULT_ENV) -> str:
    return os.environ.get("ENV") or default


def get_port(os_name: str | None = None) -> str:
    return os.environ.get("PORT") or default_port(os_name)


def find_tool(root: Path, name: str, os_name: str | None = None) -> str | None:
    """Find a tool, preferring the project-local venv but allowing host installs."""
    os_name = normalize_os(os_name)
    local = venv_executable(root, name, os_name)
    if local.exists():
        return str(local)

    candidates = [name]
    if name == "platformio":
        candidates.append("pio")
        if os_name == "windows":
            userprofile = os.environ.get("USERPROFILE")
            if userprofile:
                candidates.append(str(Path(userprofile) / ".platformio" / "penv" / "Scripts" / "platformio.exe"))

    for candidate in candidates:
        if os.path.sep in candidate or (os.path.altsep and os.path.altsep in candidate):
            if Path(candidate).exists():
                return candidate
            continue
        found = shutil.which(candidate)
        if found:
            return found
    return None


def platformio_args(
    action: str,
    pio: Path | str,
    *,
    env: str = DEFAULT_ENV,
    port: str | None = None,
    baud: int = DEFAULT_BAUD,
) -> list[str]:
    pio = str(pio)
    if action == "build":
        return [pio, "run", "-e", env]
    if action == "flash":
        if not port:
            raise ValueError("flash requires a serial port")
        return [pio, "run", "-e", env, "-t", "upload", "--upload-port", port]
    if action == "monitor":
        if not port:
            raise ValueError("monitor requires a serial port")
        return [
            pio, "device", "monitor", "-p", port, "-b", str(baud),
            "--rts", "0", "--dtr", "0", "--no-reconnect",
        ]
    if action == "clean":
        return [pio, "run", "-e", env, "-t", "clean"]
    raise ValueError(f"unknown PlatformIO action: {action}")


def run(cmd: list[str], *, cwd: Path, dry_run: bool = False) -> int:
    printable = " ".join(cmd)
    print(printable)
    if dry_run:
        return 0
    return subprocess.call(cmd, cwd=str(cwd))


def require_tool(root: Path, name: str) -> str:
    tool = find_tool(root, name)
    if tool:
        return tool
    print(
        f"error: {name} not found. Run `python tools/dev.py setup` first, "
        f"or install {name} on PATH.",
        file=sys.stderr,
    )
    raise SystemExit(127)


def cmd_setup(args: argparse.Namespace) -> int:
    root = project_root()
    os_name = normalize_os()
    py = venv_python(root, os_name)
    uv = shutil.which("uv")

    if not (root / ".venv").exists():
        if uv:
            rc = run([uv, "venv", str(root / ".venv"), "--python", args.python], cwd=root, dry_run=args.dry_run)
        else:
            rc = run([sys.executable, "-m", "venv", str(root / ".venv")], cwd=root, dry_run=args.dry_run)
        if rc != 0:
            return rc

    if uv:
        return run([uv, "pip", "install", "--python", str(py), *PACKAGES], cwd=root, dry_run=args.dry_run)
    rc = run([str(py), "-m", "pip", "install", "--upgrade", "pip"], cwd=root, dry_run=args.dry_run)
    if rc != 0:
        return rc
    return run([str(py), "-m", "pip", "install", *PACKAGES], cwd=root, dry_run=args.dry_run)


def cmd_test(args: argparse.Namespace) -> int:
    root = project_root()
    pytest = find_tool(root, "pytest")
    cmd = [pytest, "tests/", "-q"] if pytest else [sys.executable, "-m", "pytest", "tests/", "-q"]
    return run(cmd + args.pytest_args, cwd=root, dry_run=args.dry_run)


def cmd_build(args: argparse.Namespace) -> int:
    root = project_root()
    pio = require_tool(root, "platformio")
    return run(platformio_args("build", pio, env=args.env), cwd=root, dry_run=args.dry_run)


def cmd_flash(args: argparse.Namespace) -> int:
    root = project_root()
    pio = require_tool(root, "platformio")
    return run(platformio_args("flash", pio, env=args.env, port=args.port), cwd=root, dry_run=args.dry_run)


def cmd_monitor(args: argparse.Namespace) -> int:
    root = project_root()
    pio = require_tool(root, "platformio")
    return run(platformio_args("monitor", pio, port=args.port, baud=args.baud), cwd=root, dry_run=args.dry_run)


def cmd_clean(args: argparse.Namespace) -> int:
    root = project_root()
    pio = require_tool(root, "platformio")
    return run(platformio_args("clean", pio, env=args.env), cwd=root, dry_run=args.dry_run)


def cmd_bench_scan(args: argparse.Namespace) -> int:
    root = project_root()
    py = str(venv_python(root)) if venv_python(root).exists() else sys.executable
    return run([py, str(root / "tools" / "pc_ble_bench.py"), "scan", *args.extra], cwd=root, dry_run=args.dry_run)


def cmd_bench_write(args: argparse.Namespace) -> int:
    root = project_root()
    mac = args.mac or os.environ.get("BENCH_MAC")
    if not mac:
        print("error: BENCH_MAC or --mac is required", file=sys.stderr)
        return 2
    py = str(venv_python(root)) if venv_python(root).exists() else sys.executable
    return run([py, str(root / "tools" / "pc_ble_bench.py"), "write", mac, "--standard-frame", "--response", *args.extra], cwd=root, dry_run=args.dry_run)


def cmd_info(args: argparse.Namespace) -> int:
    root = project_root()
    os_name = normalize_os()
    rows = {
        "root": root,
        "os": os_name,
        "default_env": get_env(),
        "default_port": get_port(os_name),
        "python": venv_python(root, os_name),
        "platformio": find_tool(root, "platformio", os_name) or "<not found>",
        "pytest": find_tool(root, "pytest", os_name) or "<not found>",
    }
    for key, value in rows.items():
        print(f"{key}: {value}")
    return 0


def add_common_io_flags(parser: argparse.ArgumentParser, *, include_env: bool = True, include_port: bool = False) -> None:
    if include_env:
        parser.add_argument("--env", default=get_env(), help=f"PlatformIO env (default: ENV or {DEFAULT_ENV})")
    if include_port:
        parser.add_argument("--port", default=get_port(), help="Serial port (default: PORT or OS default)")
    parser.add_argument("--dry-run", action="store_true", help="Print command without executing")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-platform build/test/flash wrapper for combat-robot-v2")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="Create .venv and install platformio/pytest/bleak")
    p.add_argument("--python", default=sys.executable, help="Python executable/version for uv venv")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("test", help="Run host-side tests")
    p.add_argument("pytest_args", nargs=argparse.REMAINDER)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("build", help="Build firmware")
    add_common_io_flags(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("flash", help="Build and flash firmware")
    add_common_io_flags(p, include_port=True)
    p.set_defaults(func=cmd_flash)

    p = sub.add_parser("monitor", help="Serial monitor with RTS/DTR held low")
    add_common_io_flags(p, include_env=False, include_port=True)
    p.add_argument("--baud", type=int, default=int(os.environ.get("BAUD", DEFAULT_BAUD)))
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("clean", help="Clean PlatformIO build cache")
    add_common_io_flags(p)
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("bench-scan", help="Scan BLE devices")
    p.add_argument("extra", nargs=argparse.REMAINDER)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_bench_scan)

    p = sub.add_parser("bench-write", help="Write neutral synthetic HID frame via BLE bench")
    p.add_argument("--mac")
    p.add_argument("extra", nargs=argparse.REMAINDER)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_bench_write)

    p = sub.add_parser("info", help="Print detected tool paths/defaults")
    p.set_defaults(func=cmd_info)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
