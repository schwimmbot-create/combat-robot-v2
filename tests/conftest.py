"""
Shared pytest fixtures and configuration for combat-robot-v2 tests.

Path setup: tests live in tests/ but exercise code in components/ and main/.
We add the project root to sys.path so tests can import from fixtures/
without weird relative imports.
"""
import sys
from pathlib import Path

# Project root = parent of tests/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "fixtures"))

# Common paths used across tests
SRC_PATHS = {
    "project_root": PROJECT_ROOT,
    "main": PROJECT_ROOT / "main",
    "components": PROJECT_ROOT / "components",
    "myrobot": PROJECT_ROOT / "components" / "myrobot",
    "ble_gamepad": PROJECT_ROOT / "components" / "ble_gamepad",
    "web_config": PROJECT_ROOT / "components" / "web_config",
    "v1_repo": PROJECT_ROOT.parent / "esp-idf-arduino-bluepad32-template",
    "constants_h": PROJECT_ROOT / "components" / "myrobot" / "include" / "Constants.h",
    "ble_header": PROJECT_ROOT / "components" / "ble_gamepad" / "include" / "ble_gamepad.h",
    "ble_impl": PROJECT_ROOT / "components" / "ble_gamepad" / "src" / "ble_gamepad.cpp",
    "web_impl": PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp",
    "main_c": PROJECT_ROOT / "main" / "main.c",
    "sketch_cpp": PROJECT_ROOT / "main" / "sketch.cpp",
}


def pytest_configure(config):
    """Sanity-check that the project layout is what we expect."""
    root = PROJECT_ROOT
    expected = [
        root / "platformio.ini",
        root / "sdkconfig.defaults",
        root / "main" / "main.c",
        root / "main" / "sketch.cpp",
        root / "components" / "ble_gamepad" / "include" / "ble_gamepad.h",
        root / "components" / "web_config" / "src" / "web_config.cpp",
    ]
    missing = [str(p.relative_to(root)) for p in expected if not p.exists()]
    if missing:
        import warnings
        warnings.warn(
            f"Project layout incomplete. Missing: {missing}. "
            f"Tests will fail until these are restored."
        )