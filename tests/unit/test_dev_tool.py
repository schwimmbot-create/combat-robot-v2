"""Cross-platform dev wrapper tests.

The project must build/flash from Windows, Linux, and macOS without editing
Makefile paths by hand. These tests pin the path/command construction layer so
`tools/dev.py` can be used directly anywhere Python runs.
"""
from pathlib import Path
import importlib.util

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_TOOL = PROJECT_ROOT / "tools" / "dev.py"


def load_dev():
    spec = importlib.util.spec_from_file_location("dev_tool", DEV_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_venv_executable_paths_are_os_specific():
    dev = load_dev()
    root = Path("/repo")

    assert dev.venv_executable(root, "platformio", "windows") == root / ".venv" / "Scripts" / "platformio.exe"
    assert dev.venv_executable(root, "pytest", "windows") == root / ".venv" / "Scripts" / "pytest.exe"
    assert dev.venv_executable(root, "platformio", "linux") == root / ".venv" / "bin" / "platformio"
    assert dev.venv_executable(root, "pytest", "darwin") == root / ".venv" / "bin" / "pytest"


def test_default_ports_cover_windows_linux_and_macos():
    dev = load_dev()

    assert dev.default_port("windows") == "COM6"
    assert dev.default_port("linux") == "/dev/ttyACM0"
    assert dev.default_port("darwin").startswith("/dev/cu.")


def test_platformio_build_flash_and_monitor_commands_are_portable():
    dev = load_dev()
    root = Path("/repo")
    pio = root / ".venv" / "bin" / "platformio"

    assert dev.platformio_args("build", pio, env="esp32-c3-devkitc-02-dev") == [
        str(pio), "run", "-e", "esp32-c3-devkitc-02-dev"
    ]
    assert dev.platformio_args("flash", pio, env="esp32-c3-devkitc-02-dev", port="COM6") == [
        str(pio), "run", "-e", "esp32-c3-devkitc-02-dev", "-t", "upload", "--upload-port", "COM6"
    ]
    assert dev.platformio_args("monitor", pio, port="/dev/ttyACM0", baud=115200) == [
        str(pio), "device", "monitor", "-p", "/dev/ttyACM0", "-b", "115200",
        "--rts", "0", "--dtr", "0", "--no-reconnect"
    ]


def test_env_overrides_select_default_env_and_port(monkeypatch):
    dev = load_dev()
    monkeypatch.setenv("ENV", "esp32-c3-devkitc-02-dev")
    monkeypatch.setenv("PORT", "COM9")

    assert dev.get_env(default="esp32-c3-devkitc-02") == "esp32-c3-devkitc-02-dev"
    assert dev.get_port(os_name="windows") == "COM9"
