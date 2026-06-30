#!/usr/bin/env bash
# pre_flash_check.sh — Run before flashing the robot.
#
# Runs all host-side tests, prints a summary, and exits non-zero on failure.
# Designed to be the LAST thing you do before `pio run -t upload`.
#
# Usage:
#   ./tests/pre_flash_check.sh
#
# Exit codes:
#   0 = all checks passed, safe to flash
#   1 = tests failed, do NOT flash
#   2 = test runner not installed

set -e

# Resolve script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$PROJECT_ROOT"

echo "========================================"
echo "  Combat Robot v2 — Pre-Flash Check"
echo "========================================"
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Date:         $(date -Iseconds 2>/dev/null || date)"
echo ""

# Check Python is available
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "ERROR: Python not found in PATH"
    echo "  Install Python 3.10+ or activate your venv"
    exit 2
fi

# Pick python or python3
# Try the hermes venv first (where we installed pytest), fall back to PATH
PY=""
for candidate in \
    "C:/Users/kbrow/AppData/Local/hermes/hermes-agent/venv/Scripts/python" \
    "C:/Users/kbrow/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe" \
    "$(command -v python3 2>/dev/null)" \
    "$(command -v python 2>/dev/null)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ] && $candidate -m pytest --version &> /dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    # Last resort: try whatever 'python' is on PATH and check
    if command -v python3 &> /dev/null; then
        PY=python3
    elif command -v python &> /dev/null; then
        PY=python
    else
        echo "ERROR: Python not found in PATH"
        echo "  Install Python 3.10+ or activate your venv"
        exit 2
    fi

    if ! $PY -m pytest --version &> /dev/null; then
        echo "ERROR: pytest not found in $PY"
        echo "  Run: $PY -m pip install -r tests/requirements.txt"
        exit 2
    fi
fi

echo "Running tests..."
echo ""

# Run with summary output (no -v for less noise, but show failures)
$PY -m pytest tests/ -q --tb=line 2>&1 | tee /tmp/pre_flash_test_output.txt
TEST_RESULT=${PIPESTATUS[0]}

echo ""
echo "========================================"

if [ $TEST_RESULT -eq 0 ]; then
    echo "  ✅ ALL TESTS PASSED — safe to flash"
    echo "========================================"
    echo ""
    echo "Next step:"
    echo "  pio run -e esp32-c3-devkitc-02 -t upload"
    echo ""
    exit 0
else
    echo "  ❌ TESTS FAILED — DO NOT FLASH"
    echo "========================================"
    echo ""
    echo "Tests caught a problem. See output above."
    echo ""
    echo "Common failures:"
    echo "  - Schematic pinout mismatch (test_schematic_pinout_warning)"
    echo "  - BLE API surface changed (test_ble_api_consistency)"
    echo "  - myrobot/ files edited (test_ported_files_unchanged)"
    echo "  - Constants.h pins drifted (test_pin_defines)"
    echo ""
    echo "Run with -v for verbose output:"
    echo "  pytest tests/ -v"
    echo ""
    exit 1
fi