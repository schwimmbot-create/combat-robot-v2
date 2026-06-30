# Hardware Reference Files

This directory contains the EasyEDA source files for the ESP32-C3-MINI-1 robot controller boards.

## Files

| File | Board | Description |
|---|---|---|
| `board-v2-rev1-schematic.epro` | v2 (production) | EasyEDA schematic source. The board you currently have. |
| `board-v2-rev1-pcb-layout.epro2` | v2 (production) | EasyEDA PCB layout. Not used for firmware development. |
| `board-v3-rev1-schematic.epro` | v3 (next rev) | EasyEDA schematic source. Designed, not yet fabricated. |
| `board-v3-rev1-rendered.pdf` | v3 (next rev) | Rendered v3 schematic as PDF. Used for vision-based pinout extraction. |

## File naming convention

Files are named: `board-{rev}-rev{N}-{type}.epro{,2}` or `.pdf`

- **rev** = v2 or v3
- **N** = revision number (rev1, rev2, etc.)
- **type** = `schematic` (`.epro`), `pcb-layout` (`.epro2`), or `rendered` (`.pdf`)

## How to open these files

1. Go to https://easyeda.com/editor
2. File → Open → EasyEDA Project (.epro / .epro2)
3. Or open directly in the EasyEDA Pro desktop app

## How these files were named

The original files in `.hermes/desktop-attachments/` had confusing names:

- `ProPrj_Generic_Robot_Controller_ver2_2025-08-17.epro` — this is the **v3** board (newer design, but titled "ver2" because it's an internal revision of v2). Renamed to `board-v3-rev1-schematic.epro`.
- `ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro` — this is the **v2** board (the one in production). Renamed to `board-v2-rev1-schematic.epro`.
- `ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro2` — this is the **v2** PCB layout. Renamed to `board-v2-rev1-pcb-layout.epro2`.
- `SCH_Schematic1_1_2026-06-29.pdf` — this is a rendered PDF export of the **v3** board schematic. Renamed to `board-v3-rev1-rendered.pdf`.

## Source of truth for firmware pin assignments

See `../docs/BOARD_HARDWARE.md` for the full board reference, including:
- ESP32-C3-MINI-1-H4 pinout (all 53 pads)
- v2 and v3 board pin assignments
- Motor driver topology (v2 has 2, v3 has 4)
- CN5 spare output header (v3 only, for BLDC ESCs)
- v1.3 firmware mistakes (and how the new `board_config.h` fixes them)

The `board_config.h` file in `../components/board_config/include/` is the firmware source of truth — when in doubt, the schematic is the design intent and the code is what runs.
