# Build Instructions

## Prerequisites

- PlatformIO Core 6.x (or the PlatformIO IDE in VSCode)
- ESP32 platform: `pioarduino/platform-espressif32#develop` (configured in `platformio.ini`)
- USB driver for your ESP32-C3 (CH343 or CP2102; Windows often installs these automatically)

## Building

```bash
# From the project root (combat-robot-v2/)
pio run -e esp32-c3-devkitc-02

# Or with verbose output to see component fetch progress
pio run -e esp32-c3-devkitc-02 -v
```

On first build, PlatformIO will:
1. Fetch the ESP32 platform (~200MB).
2. Fetch the Arduino-esp32 framework.
3. Fetch NimBLE from the component manager (~150MB).
4. Fetch ESPAsyncWebServer and AsyncTCP.
5. Compile the project.

Expect 5-15 minutes for the first build, ~30s for incremental.

## Uploading

```bash
# Hold BOOT button on C3, then run:
pio run -e esp32-c3-devkitc-02 -t upload

# Or with the auto-reset pattern (most C3 dev boards):
pio run -e esp32-c3-devkitc-02 -t upload --upload-port /dev/ttyUSB0
```

On Windows, the upload port is `COMx` — find it via Device Manager.

## Flashing without PlatformIO (advanced)

If you have a pre-built `.bin` and want to flash directly with `esptool.py`:

```bash
esptool.py --chip esp32c3 --port /dev/ttyUSB0 --baud 460800 \
    write_flash 0x0 .pio/build/esp32-c3-devkitc-02/firmware.bin
```

## Build artifacts

After `pio run`, look in `.pio/build/esp32-c3-devkitc-02/`:
- `firmware.bin` — flashable image
- `firmware.elf` — symbol table for debugging
- `firmware.map` — memory map (useful for finding what takes flash)

## Targets

| Environment | Board | Notes |
|---|---|---|
| `esp32-c3-devkitc-02` | ESP32-C3 DevKit M02 | **Primary target.** BLE-only, 4MB flash. |
| `esp32dev` | ESP32 DevKit | Full classic BT + BLE. Larger. |
| `esp32-s3-devkitc-1` | ESP32-S3 | Dual core, BLE only. |
| `esp32-c6-devkitc-1` | ESP32-C6 | BLE + 802.15.4. |
| `esp32-h2-devkitm-1` | ESP32-H2 | BLE + 802.15.4. |

All use the same source; pin defines in `myrobot/include/Constants.h` are C3-specific and may need tweaking per board.

## Common build errors

### `fatal error: nimble/nimble_port.h: No such file or directory`
The NimBLE managed component hasn't been fetched. Run `pio run` again to let PIO resolve it, or manually `pio pkg install -l "espressif/nimble@~1.5.0"`.

### `undefined reference to initArduino()`
The Arduino framework is not registering the loop task. Check that `framework = espidf` is set in `platformio.ini` and that the `arduino` component is in the `requires` list of `myrobot/CMakeLists.txt`.

### `error: 'CONFIG_BT_NIMBLE_HOST_ONLY' undeclared`
The NimBLE component version doesn't support this option. Check `components/ble_gamepad/idf_component.yml` and pin to a version that has it. (Latest NimBLE versions have it.)

### `region 'iram0_0' overflowed`
Out of IRAM. Common when NimBLE's ACL buffers are too large. Reduce `CONFIG_BT_NIMBLE_MSYS1_BLOCK_COUNT` and `CONFIG_BT_NIMBLE_MSYS2_BLOCK_COUNT` in `sdkconfig.defaults`.