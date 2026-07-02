# Build and Flash Instructions

This file documents the exact PlatformIO/ESP-IDF workflow that works on Kevin's Windows PC for the ESP32-C3 Mini / ESP32-C3 DevKit target.

## Verified PC setup

- Host: Windows, using Git Bash / MSYS shell.
- Project path: `C:/Users/kbrow/Documents/Codex/combat-robot-v2`
- PlatformIO Core: `6.1.19`
- PlatformIO executable: `C:/Users/kbrow/.platformio/penv/Scripts/platformio.exe`
- Important: `pio` is **not currently on PATH** in the Hermes/Git-Bash shell. Use the full path or export PlatformIO's venv first.
- Confirmed ESP32-C3 serial port: `COM6`
- Confirmed chip during upload: `ESP32-C3 revision v0.4`
- Confirmed MAC during upload: `28:37:2f:cb:9d:04`

## Shell setup for this PC

From Git Bash:

```bash
cd "C:/Users/kbrow/Documents/Codex/combat-robot-v2"
export PATH="$HOME/.platformio/penv/Scripts:$PATH"
pio --version
```

Expected:

```text
PlatformIO Core, version 6.1.19
```

If you do not want to modify `PATH`, use the full executable path:

```bash
"/c/Users/kbrow/.platformio/penv/Scripts/platformio.exe" --version
```

## Finding the ESP32-C3 port

```bash
pio device list
```

Known-good result from this PC:

```text
COM6
----
Hardware ID: USB VID:PID=303A:1001 SER=28:37:2F:CB:9D:04
Description: USB Serial Device (COM6)
```

Ignore the Bluetooth SPP ports (`COM4`, `COM5`, `COM10`, `COM11`, etc.). The ESP32-C3 is the `USB VID:PID=303A:1001` device.

## Building

```bash
cd "C:/Users/kbrow/Documents/Codex/combat-robot-v2"
export PATH="$HOME/.platformio/penv/Scripts:$PATH"
pio run -e esp32-c3-devkitc-02
```

Verbose build:

```bash
pio run -e esp32-c3-devkitc-02 -v
```

The first successful ESP-IDF 5.1.2 build on this PC installed:

```text
framework-espidf @ 3.50102.240122 (5.1.2)
tool-esptoolpy @ 1.40501.0 (4.5.1)
toolchain-riscv32-esp @ 12.2.0+20230208
```

The first build can take several minutes because PlatformIO downloads ESP-IDF, toolchains, libraries, and Python dependencies. Incremental builds are usually seconds.

## Flashing

Use the known ESP32-C3 port explicitly:

```bash
cd "C:/Users/kbrow/Documents/Codex/combat-robot-v2"
export PATH="$HOME/.platformio/penv/Scripts:$PATH"
pio run -e esp32-c3-devkitc-02 -t upload --upload-port COM6
```

Known-good upload output includes:

```text
Serial port COM6
Connecting...
Chip is ESP32-C3 (revision v0.4)
Features: WiFi, BLE
Crystal is 40MHz
MAC: 28:37:2f:cb:9d:04
Uploading stub...
Running stub...
Changing baud rate to 460800
...
Hash of data verified.
Leaving...
Hard resetting via RTS pin...
========================= [SUCCESS]
```

The C3 board on this PC reset automatically via RTS after upload; manually holding BOOT was not required for the verified hello-world flash.

## Serial monitor

```bash
pio device monitor --port COM6 --baud 115200
```

For short automated captures from Git Bash:

```bash
timeout 10 pio device monitor --port COM6 --baud 115200
```

The verified toolchain-test firmware printed one line per second:

```text
[tick 0005] uptime=4984s  heap=327496  hello from combat-robot-v2
[tick 0006] uptime=4985s  heap=327496  hello from combat-robot-v2
[tick 0007] uptime=4986s  heap=327496  hello from combat-robot-v2
```

## What has actually been verified

Verified on hardware:

1. PlatformIO is installed and usable from `~/.platformio/penv/Scripts`.
2. PlatformIO can install/use ESP-IDF 5.1.2 for `espressif32@6.5.0`.
3. RISC-V ESP32-C3 cross-compilation works.
4. Bootloader, partition table, and app image can be generated.
5. esptool can connect to COM6, identify the ESP32-C3, erase/write flash, verify hashes, and reset the board.
6. A minimal ESP-IDF app runs and prints heartbeat logs over USB serial.

Not yet verified:

- The full robot firmware build.
- BLE gamepad pairing.
- Web UI.
- Motor/drum/servo outputs.
- OTA.

## Resolved: 4MB flash partition blocker

The current `partitions.csv` (committed at top-level) fits exactly in 4MB:

```csv
nvs,       data, nvs,     0x9000,   0x6000
phy_init,  data, phy_init,0xf000,   0x1000
factory,   app,  factory, 0x10000,  0x180000
ota_0,     app,  ota_0,   0x190000, 0x180000
storage,   data, spiffs,  0x310000, 0xF0000
```

Every entry ends at or below 0x400000. Verified by `test_pre_flash.py::TestSdkConfig::test_partitions_table_consistent`, which parses the file and checks `offset + size <= 0x400000` and no overlaps.

## Known PlatformIO package issue fixed on this PC

A corrupt/partial package directory existed at:

```text
C:/Users/kbrow/.platformio/packages/framework-espidf
```

It had no `package.json`, causing:

```text
MissingPackageManifestError: Could not find one of 'package.json' manifest files in the package
```

That broken directory was deleted, and PlatformIO successfully installed:

```text
framework-espidf@3.50102.240122
```

If the same error returns, check `C:/Users/kbrow/.platformio/packages/` for a manifestless `framework-espidf` directory and let PlatformIO reinstall it.

## Useful cleanup commands
Generated ESP-IDF/PlatformIO files can be safely removed:

```bash
rm -rf .pio
rm -f CMakeLists.txt dependencies.lock sdkconfig sdkconfig.old sdkconfig.esp32-c3-devkitc-02
```

Do **not** remove source directories like `main/` or `components/` unless intentionally replacing the build with a temporary toolchain-test app.

## Before flashing real robot firmware

Run the host-side gate first:

```bash
pip install -r tests/requirements.txt
bash tests/pre_flash_check.sh
```

Then build and flash:

```bash
pio run -e esp32-c3-devkitc-02
pio run -e esp32-c3-devkitc-02 -t upload --upload-port COM6
pio device monitor --port COM6 --baud 115200
```

If the partition-table error appears, fix `partitions.csv` before continuing. Do not work around it for the full firmware by using an unrelated default partition table; that only proves the toolchain, not that the robot app layout is valid.
