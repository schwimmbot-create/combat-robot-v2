#!/usr/bin/env bash
# build_and_flash.sh — Compile the combat-robot-v2 firmware and stream
# the output to a terminal-visible log file so progress is visible.
#
# Usage:
#   bash tools/build_and_flash.sh                  # build only
#   bash tools/build_and_flash.sh upload           # build + flash
#   bash tools/build_and_flash.sh monitor          # build + open serial monitor
#   bash tools/build_and_flash.sh upload monitor   # build + flash + monitor
#
# Output is written to build.log in the project root and also printed to
# the terminal. Use 'tail -f build.log' in another terminal to watch
# progress without losing context.

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PIO="/c/Users/kbrow/.platformio/penv/Scripts/platformio.exe"
ENV="esp32-c3-devkitc-02"
LOG="$PROJECT_ROOT/build.log"

ACTION="${1:-build}"
EXTRA=""
case "$ACTION" in
    build)   EXTRA="run" ;;
    upload)  EXTRA="run -t upload" ;;
    monitor) EXTRA="run -t monitor" ;;
    "upload monitor"|"monitor upload")
            EXTRA="run -t upload,monitor" ;;
    *)
        echo "Unknown action: $ACTION"
        echo "Usage: $0 [build|upload|monitor]"
        exit 1
        ;;
esac

echo "================================================================"
echo "  Combat Robot v2 — Build"
echo "================================================================"
echo "  Project: $PROJECT_ROOT"
echo "  Action:  $ACTION"
echo "  Log:     $LOG"
echo "  Command: $PIO $EXTRA -e $ENV"
echo "================================================================"
echo

# Truncate previous log
: > "$LOG"

# Run with -v for verbose output. Pipe to tee so we get both file and stdout.
# The 2>&1 is inside the subshell so PIO's output (which is on stderr) is captured.
"$PIO" -v $EXTRA -e $ENV 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo "================================================================"
if [ $RC -eq 0 ]; then
    echo "  ✓ Build SUCCEEDED (exit $RC)"
else
    echo "  ✗ Build FAILED (exit $RC)"
fi
echo "  Full log: $LOG"
echo "================================================================"

exit $RC