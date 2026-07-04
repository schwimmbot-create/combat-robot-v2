"""Schema and source-level tests for the output_config component.

This test verifies the design contracts the new web UI depends on,
WITHOUT requiring an Arduino build. It's an integration test against
the C source on disk, matching the project's existing pattern of
static + parse-based host tests.

What's verified:
  * OutputConfig component registers cleanly in the PIO build (has
    library.json, src/, include/, CMakeLists.txt, REQUIRES nvs_flash).
  * The JSON schema emitted by output_config_to_json() includes every
    logical output (M1, M2, Weapon, S1, S2) and every input source
    (LX, LY, RX, RY, LT, RT, A, B, X, Y, L1, R1, L2, R2, SELECT,
    START, L3, R3, HOME, DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT,
    NONE).
  * The web_config handler exposes /api/config, /api/config/sources,
    and the POST body handler that calls
    output_config_apply_json_patch().
  * Defaults describe current hard-coded tank drive:
        M1: LY primary, M2: RY primary, normal direction, bi servo_mode (motor)
        Weapon: RT primary
        S1/S2: NONE, uni
  * Patch parser recognizes direction/servo_mode/primary/secondary/
    deadzone and rejects invalid values.
  * NVS key/versioning string is present so future bumps are clear.
"""
import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OC_INCLUDE = PROJECT_ROOT / "components" / "output_config" / "include" / "output_config.h"
OC_SRC = PROJECT_ROOT / "components" / "output_config" / "src" / "output_config.c"
OC_LIB = PROJECT_ROOT / "components" / "output_config" / "library.json"
OC_CMAKE = PROJECT_ROOT / "components" / "output_config" / "CMakeLists.txt"
WC_SRC = PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp"
PLATFORMIO_INI = PROJECT_ROOT / "platformio.ini"


# ---------------------------------------------------------------------------
# Component discovery (PlatformIO library scan)
# ---------------------------------------------------------------------------

class TestOutputConfigBuildWiring:
    def test_library_json_exists(self):
        assert OC_LIB.exists(), "output_config/library.json missing"
        data = json.loads(OC_LIB.read_text())
        assert data["name"] == "output_config"
        assert data["build"]["srcDir"] == "src"
        assert data["build"]["includeDir"] == "include"

    def test_cmakelists_registers_component(self):
        text = OC_CMAKE.read_text()
        assert "REQUIRES" in text
        assert "nvs_flash" in text
        assert "src/output_config.c" in text

    def test_platformio_includes_output_config(self):
        text = PLATFORMIO_INI.read_text()
        assert "components/output_config/include" in text

    def test_web_config_requires_output_config(self):
        text = (PROJECT_ROOT / "components" / "web_config" / "CMakeLists.txt").read_text()
        assert "output_config" in text


# ---------------------------------------------------------------------------
# Public API surface in the header
# ---------------------------------------------------------------------------

EXPECTED_OUTPUT_IDS = {"M1", "M2", "Weapon", "S1", "S2"}

EXPECTED_SOURCES = {
    "NONE", "LX", "LY", "RX", "RY",
    "LT", "RT",
    "A", "B", "X", "Y",
    "L1", "R1", "L2", "R2",
    "SELECT", "START", "L3", "R3", "HOME",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
}

class TestOutputConfigHeader:
    def test_header_exists_with_public_api(self):
        text = OC_INCLUDE.read_text()
        for fn in (
            "output_config_init",
            "output_config_get",
            "output_config_set_direction",
            "output_config_set_servo_mode",
            "output_config_set_deadzone",
            "output_config_set_source",
            "output_config_get_drive_mode",
            "output_config_set_drive_mode",
            "output_config_drive_mode_name",
            "output_config_drive_mode_from_str",
            "output_config_to_json",
            "output_config_sources_to_json",
            "output_config_apply_json_patch",
        ):
            assert fn in text, f"public API {fn} missing from output_config.h"

    def test_header_uses_c_guards(self):
        text = OC_INCLUDE.read_text()
        assert "#ifdef __cplusplus" in text
        assert 'extern "C"' in text


# ---------------------------------------------------------------------------
# Defaults / JSON schema
# ---------------------------------------------------------------------------

class TestOutputConfigImplementation:
    @pytest.fixture(scope="class")
    def src_text(self) -> str:
        return OC_SRC.read_text()

    @pytest.fixture(scope="class")
    def header_text(self) -> str:
        return OC_INCLUDE.read_text()

    def test_output_id_strings_complete(self, src_text):
        # Pull the kOutputIdStrings array literal and check values.
        m = re.search(r"kOutputIdStrings\[OC_OUT__COUNT\]\s*=\s*\{([^}]+)\}", src_text)
        assert m, "kOutputIdStrings not found"
        ids = {tok.strip().strip('"')
               for tok in m.group(1).split(",")
               if tok.strip()}
        assert ids == EXPECTED_OUTPUT_IDS, (
            f"output id list drift: got {ids}, expected {EXPECTED_OUTPUT_IDS}"
        )

    def test_source_names_complete(self, src_text):
        m = re.search(r"kSourceNames\[OC_SRC__COUNT\]\s*=\s*\{([^}]+)\}", src_text)
        assert m, "kSourceNames not found"
        names = {tok.strip().strip('"')
                 for tok in m.group(1).split(",")
                 if tok.strip()}
        # A couple of multi-word entries contain a space; strip comments.
        names = {n.split()[0] for n in names}
        assert names == EXPECTED_SOURCES, (
            f"source list drift: got {names}, expected {EXPECTED_SOURCES}"
        )

    def test_defaults_match_current_tank_drive(self, src_text):
        # Defaults: M1 -> LY primary, M2 -> RY primary, Weapon -> RT, S1/S2 -> NONE,
        # all "normal" direction, deadzone 10 (Weapon: 5), uni for servos.
        m = re.search(r"kDefaults\[OC_OUT__COUNT\]\s*=\s*\{([\s\S]+?)\};", src_text)
        assert m, "kDefaults not found"
        defaults_blob = m.group(1)

        # Spot-check each.
        assert re.search(r"OC_OUT_M1\][^}]*OC_SRC_LY", defaults_blob)
        assert re.search(r"OC_OUT_M2\][^}]*OC_SRC_RY", defaults_blob)
        assert re.search(r"OC_OUT_WEAPON\][^}]*OC_SRC_RT", defaults_blob)
        assert re.search(r"OC_OUT_S1\][^}]*OC_DIR_NORMAL", defaults_blob)
        assert re.search(r"OC_OUT_S2\][^}]*OC_DIR_NORMAL", defaults_blob)

    def test_runtime_drive_path_uses_negative_y_as_forward(self):
        # HID Y-up decodes negative, then setForwardInputLimits reverses the
        # forward range so negative Y becomes positive FORWARD PWM.
        tm = (PROJECT_ROOT / "components" / "myrobot" / "src" / "TaskManager.cpp").read_text()
        drive = (PROJECT_ROOT / "components" / "myrobot" / "src" / "Drive.cpp").read_text()
        assert "drive.setForwardInputLimits(511,-512);" in tm
        assert "_leftDriveInput   = cs.leftStickY;" in tm
        assert "_rightDriveInput  = cs.rightStickY;" in tm
        assert "_leftTurnInput    = cs.leftStickX;" in tm
        assert "_rightTurnInput   = cs.rightStickX;" in tm
        assert "if(leftMotorSpeed < 0){leftMotor.setSpeed(left_speed, REVERSE" in drive
        assert "else{leftMotor.setSpeed(left_speed, FORWARD" in drive

    def test_runtime_drive_mode_switches_mixers(self):
        tm = (PROJECT_ROOT / "components" / "myrobot" / "src" / "TaskManager.cpp").read_text()
        assert '#include "output_config.h"' in tm
        assert "output_config_init();" in tm
        assert "switch(output_config_get_drive_mode())" in tm
        assert "case OC_DRIVE_ARCADE_LEFT:" in tm
        assert "combined_direction(self->_leftTurnInput, self->_leftDriveInput" in tm
        assert "case OC_DRIVE_ARCADE_RIGHT:" in tm
        assert "combined_direction(self->_rightTurnInput, self->_rightDriveInput" in tm
        assert "case OC_DRIVE_ARCADE_SPLIT:" in tm
        assert "combined_direction(self->_rightTurnInput, self->_leftDriveInput" in tm
        assert "case OC_DRIVE_TANK_SPLIT:" in tm
        assert "two_stick_drive(self->_leftDriveInput, self->_rightDriveInput" in tm

    def test_drive_modes_are_serialized_and_patchable(self, src_text, header_text):
        for tok in ("OC_DRIVE_TANK_SPLIT", "OC_DRIVE_ARCADE_LEFT",
                    "OC_DRIVE_ARCADE_RIGHT", "OC_DRIVE_ARCADE_SPLIT"):
            assert tok in header_text
        for tok in ("tank_split", "arcade_left", "arcade_right", "arcade_split"):
            assert tok in src_text
        assert "OC_NVS_KEY_DRIVE_MODE" in header_text
        assert '"drive_mode"' in src_text
        assert "output_config_drive_mode_from_str" in src_text
        assert "nvs_set_u8(h, OC_NVS_KEY_DRIVE_MODE" in src_text
        assert "nvs_get_u8(h, OC_NVS_KEY_DRIVE_MODE" in src_text

    def test_nvs_namespace_is_namespaced(self, header_text):
        assert "OC_NVS_NAMESPACE" in header_text
        # Should be a namespaced string, not a bare key.
        m = re.search(r'#define\s+OC_NVS_NAMESPACE\s+"([^"]+)"', header_text)
        assert m and m.group(1).startswith("output_"), (
            f"NVS namespace should be namespaced, got {m.group(1) if m else '<not found>'}"
        )

    def test_json_writer_is_self_contained(self, src_text):
        # The source contains an explanatory comment that mentions
        # ArduinoJson by name; the rule is "we don't *depend* on it".
        # Strip comments before checking.
        stripped = re.sub(r"//.*", "", src_text)
        stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
        assert "ArduinoJson" not in stripped
        # Must implement the two render functions.
        assert "output_config_to_json" in src_text
        assert "output_config_sources_to_json" in src_text


# ---------------------------------------------------------------------------
# BLE gamepad — diagnostic logs + default-state regression guards.
# User reported that pairing state changes (clicking "Enter Pairing Mode")
# were not visible on the page. These tests pin the firmware contract that
# prevents that bug class from coming back.
# ---------------------------------------------------------------------------

class TestBleGamepadGuiContract:
    BLE_SRC = PROJECT_ROOT / "components" / "ble_gamepad" / "src" / "ble_gamepad.cpp"

    @pytest.fixture(scope="class")
    def ble_src_text(self) -> str:
        return self.BLE_SRC.read_text()

    def test_uses_nimble_arduino_api(self, ble_src_text):
        assert "#include <NimBLEDevice.h>" in ble_src_text
        assert "NimBLEAdvertisedDeviceCallbacks" in ble_src_text

    def test_boot_logs_observable(self, ble_src_text):
        # Diagnostic logs make it possible to verify on serial that
        # NimBLE actually advertised and started scanning. Without
        # these, a silent boot looks identical to a no-op boot.
        for log in ('ESP_LOGI(TAG, "advertising + bench service up"',
                    'ESP_LOGI(TAG, "set_pairing_state:',
                    'ESP_LOGI(TAG, "start_scan: ok='):
            assert log in ble_src_text, f"missing diagnostic log: {log!r}"

    def test_boot_does_not_start_pairing_scan(self, ble_src_text):
        # ESP32-C3 WiFi and BLE share the 2.4GHz radio. Boot must keep
        # BLE scanning idle (pairing_state == IDLE) so the SoftAP / web UI
        # is reachable; the user explicitly enters ACCEPT via
        # /api/pair/start when they want a new pairing.
        assert "s_state.pairing_state = PAIRING_STATE_IDLE" in ble_src_text
        start_block = re.search(
            r"esp_err_t ble_gamepad_start\(void\)\s*\{[\s\S]+?\n\}",
            ble_src_text,
        )
        assert start_block, "ble_gamepad_start() not found"
        body = start_block.group(0)
        assert "start_scan();" not in body
        # Boot may ARM auto_reconnect, but it must NOT call start_scan()
        # directly. The poll loop / connect path takes it from here.
        assert "auto_reconnect = (count > 0)" in body
        assert "ble_gamepad_poll" in ble_src_text

    def test_boot_arms_auto_reconnect_when_whitelist_exists(self, ble_src_text):
        # Regression: 8BitDo power-cycled after a successful bond did not
        # auto-reconnect. start_scan() used to require pairing_state==ACCEPT
        # unconditionally. Boot must now also set auto_reconnect=true when
        # at least one whitelisted MAC is in NVS, so the poll loop keeps
        # scanning without the user re-clicking "Enter Pairing Mode".
        assert "s_state.auto_reconnect" in ble_src_text
        start_block = re.search(
            r"esp_err_t ble_gamepad_start\(void\)\s*\{[\s\S]+?\n\}",
            ble_src_text,
        )
        assert start_block, "ble_gamepad_start() not found"
        body = start_block.group(0)
        assert "s_state.pairing_state = PAIRING_STATE_IDLE" in body
        assert "auto_reconnect = (count > 0)" in body

    def test_start_scan_honors_auto_reconnect_gate(self, ble_src_text):
        # start_scan() must allow scanning when auto_reconnect is on even
        # though pairing_state is IDLE. Otherwise the onDisconnect path
        # silently does nothing and a paired controller never reconnects.
        body = re.search(r"static void start_scan\(void\)\s*\{[\s\S]+?^\}",
                         ble_src_text, re.M)
        assert body, "start_scan() not found"
        b = body.group(0)
        assert "accept_open" in b
        assert "auto_open" in b
        # The old unconditional early-return must NOT be present anymore.
        assert "!s_state.pairing_state == PAIRING_STATE_ACCEPT" not in b
        assert "skipping state=%d auto=%d" in b

    def test_on_disconnect_re_arms_auto_reconnect(self, ble_src_text):
        # When the controller drops the link, we want the poll loop to keep
        # trying if there's still a whitelisted MAC in NVS. This is what
        # the user sees as "power-cycle reconnect".
        body = re.search(
            r"void onDisconnect\(NimBLEClient \*client\) override[\s\S]+?\n    \}",
            ble_src_text,
        )
        assert body, "onDisconnect() not found"
        b = body.group(0)
        assert "nvs_get_count() > 0" in b
        assert "s_state.auto_reconnect = true" in b

    def test_clear_paired_macs_drops_auto_reconnect(self, ble_src_text):
        body = re.search(
            r"esp_err_t ble_gamepad_clear_paired_macs\(void\)\s*\{[\s\S]+?\n\}",
            ble_src_text,
        )
        assert body, "ble_gamepad_clear_paired_macs() not found"
        b = body.group(0)
        assert "s_state.auto_reconnect = false" in b


    def test_8bitdo_ultimate_report_id_layout_matches_capture(self, ble_src_text):
        # Captured from tools/ble_recordings/hidapi-20260703-161017.jsonl:
        #   01 0f 7f 7f 7f 7f 00 00 00 00 ...
        # byte0 is a report id, byte1 is the hat, byte2..5 are axes,
        # byte6/7 are R2/L2 analog, byte8/9 are button bytes.
        assert "parse_8bitdo_report" in ble_src_text
        assert "data[base + 1]" in ble_src_text  # LX
        assert "data[base + 2]" in ble_src_text  # LY
        assert "data[base + 3]" in ble_src_text  # RX
        assert "data[base + 4]" in ble_src_text  # RY
        assert "rightTrigger = (int)data[base + 5] * 4" in ble_src_text
        assert "leftTrigger = (int)data[base + 6] * 4" in ble_src_text
        assert "decode_8bitdo_buttons(data[base + 7], data[base + 8])" in ble_src_text
        assert "dpad = decode_hat(data[base])" in ble_src_text

    def test_8bitdo_ultimate_button_bits_are_remapped_to_internal_order(self, ble_src_text):
        # The Windows HIDAPI capture used b0 bits 0,1,3,4 for A,B,X,Y and
        # b1 bits 2,3,4,5,6 for SELECT,START,HOME,L3,R3. Internally the
        # UI expects A,B,X,Y,L1,R1,L2,R2,SELECT,START,L3,R3,HOME in bits 0..12.
        expected = [
            "if (b0 & 0x01) buttons |= (1u << 0);  // A",
            "if (b0 & 0x02) buttons |= (1u << 1);  // B",
            "if (b0 & 0x08) buttons |= (1u << 2);  // X",
            "if (b0 & 0x10) buttons |= (1u << 3);  // Y",
            "if (b0 & 0x40) buttons |= (1u << 4);  // L1",
            "if (b0 & 0x80) buttons |= (1u << 5);  // R1",
            "if (b1 & 0x01) buttons |= (1u << 6);  // L2 digital",
            "if (b1 & 0x02) buttons |= (1u << 7);  // R2 digital",
            "if (b1 & 0x04) buttons |= (1u << 8);  // SELECT / SHARE",
            "if (b1 & 0x08) buttons |= (1u << 9);  // START / OPTIONS",
            "if (b1 & 0x20) buttons |= (1u << 10); // L3",
            "if (b1 & 0x40) buttons |= (1u << 11); // R3",
            "if (b1 & 0x10) buttons |= (1u << 12); // HOME",
        ]
        for needle in expected:
            assert needle in ble_src_text, f"missing 8BitDo remap: {needle}"

    def test_8bitdo_parser_accepts_report_id_and_hogp_payload_forms(self, ble_src_text):
        # Windows HIDAPI includes report id 0x01; BLE Report char values often
        # omit it. Firmware must handle both or the same controller appears
        # static on the ESP32 even though the host-side capture looks correct.
        assert "data[0] == 0x01 && data[1] <= 0x0f" in ble_src_text
        assert "parse_8bitdo_report(data, 1);" in ble_src_text
        # 2026-07-04 fix: removed the `len > 12` skip that silently dropped
        # 10–12 byte no-report-id reports; now any report with `data[0] <= 0x0f`
        # is accepted (the function-level len < 10 guard covers the floor).
        assert "data[0] <= 0x0f" in ble_src_text
        assert "len > 12" not in ble_src_text, (
            "stale len > 12 condition silently drops short 8BitDo reports"
        )
        assert "parse_8bitdo_report(data, 0);" in ble_src_text
        # Also assert the hard floor for the parser dispatcher.
        assert "if (len < 10)" in ble_src_text, (
            "parse_hid_report must reject reports shorter than 10 bytes"
        )



    def test_subscribes_all_hid_input_report_characteristics(self, ble_src_text):
        # Regression: 8BitDo Ultimate 2 exposes multiple notifiable input
        # Report chars. The first notifiable handle (id=2) can stay quiet;
        # the real gamepad state arrived on the second input report (id=1).
        assert "subscribed_reports" in ble_src_text
        assert "UUID_DSC_REPORT_REF" in ble_src_text
        assert "report_type == 0xff || report_type == 1" in ble_src_text
        assert "chr->subscribe(use_notify, notify_cb)" in ble_src_text
        assert "break;" not in re.search(
            r"for \(NimBLERemoteCharacteristic \*chr : \*chars\)[\s\S]+?if \(subscribed_reports == 0\)",
            ble_src_text,
        ).group(0)

    def test_8bitdo_rotating_address_allowed_after_prior_pair(self, ble_src_text):
        # Regression: after pairing AE, the controller advertised as AF and
        # was ignored in IDLE because auto-reconnect only accepted exact MACs.
        assert "is_8bitdo_ultimate_name" in ble_src_text
        assert "known_8bitdo_rotation" in ble_src_text
        assert "s_state.auto_reconnect && (nvs_get_count() > 0)" in ble_src_text
        assert "!pairing_open && !whitelisted && !known_8bitdo_rotation" in ble_src_text


    def test_disconnect_clears_synthetic_bench_connection(self, ble_src_text):
        m = re.search(r"esp_err_t ble_gamepad_disconnect[\s\S]+?\n\}", ble_src_text)
        assert m, "ble_gamepad_disconnect() not found"
        body = m.group(0)
        assert "if (s_state.connected)" in body
        assert "s_state.connected = false" in body
        assert "s_state.controller_state = ControllerState{}" in body
        assert "notify_connection_change(false" in body


    def test_bench_hid_injection_disabled_in_production_builds(self):
        wc_text = (PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp").read_text()
        # Look at the enable/disable endpoints as well, since they are dev-only.
        for ep in ('"/api/bench/hid"', '"/api/bench/hid/enable"', '"/api/bench/hid/disable"'):
            # Capture the entire endpoint body up to the matching outer close-paren.
            m = re.search(r'server->on\(' + re.escape(ep) + r'.*?NULL\s*\);', wc_text, re.DOTALL)
            assert m, f"{ep} block not found"
            block = m.group(0)
            assert "#ifndef BENCH_HID_PUBLIC" in block, f"{ep} missing BENCH_HID_PUBLIC guard"
            assert ("{\"err\":\"disabled\"}" in block
                    or "{\\\"err\\\":\\\"disabled\\\"}" in block), f"{ep} missing disabled response"
        # The inject block additionally requires runtime enable.
        inj = re.search(r'server->on\("/api/bench/hid", HTTP_POST.*?NULL\s*\);', wc_text, re.DOTALL)
        assert inj, "/api/bench/hid inject block not found"
        assert "ble_gamepad_bench_is_enabled" in inj.group(0)

    def test_bench_hid_runtime_disable_via_nvs_flag(self):
        # Public API must expose enable/disable + is_enabled for runtime control.
        h_text = (PROJECT_ROOT / "components" / "ble_gamepad" / "include" / "ble_gamepad.h").read_text()
        for fn in ("ble_gamepad_bench_set_enabled", "ble_gamepad_bench_is_enabled",
                   "ble_gamepad_bench_inject_hid_report"):
            assert fn in h_text
            assert f"{fn}" in h_text
        # Stubbed no-op fallback must exist when BENCH_HID_PUBLIC is off.
        assert "static inline esp_err_t ble_gamepad_bench_set_enabled" in h_text
        assert "static inline bool ble_gamepad_bench_is_enabled" in h_text
        assert "static inline esp_err_t ble_gamepad_bench_inject_hid_report" in h_text

    def test_bench_runtime_flag_default_off(self):
        # NVS default for bench flag must be off (false / 0), and the
        # helper is_enabled must consult NVS not a hardcoded true.
        cpp = (PROJECT_ROOT / "components" / "ble_gamepad" / "src" / "ble_gamepad.cpp").read_text()
        m = re.search(r"bool ble_gamepad_bench_is_enabled\([\s\S]+?\n\}", cpp)
        assert m, "is_enabled helper not found"
        body = m.group(0)
        assert "nvs_get_u8" in body
        assert "BLE_BENCH_FLAG_NAMESPACE" in body
        assert "return false;" in body

    # ----- Web UI hardening regressions (paired-controller crash + missing
    # connected indicator). These guard the docs/config-ui-mockup.html file
    # that gen_web_index.py bakes into web_index_gen.h and serves from the
    # board at GET /.
    def test_html_setBle_driven_from_status(self):
        # applyStatus() must call setBle(!!s.ble_connected) so the
        # header indicator reflects /api/status truth and is not stuck
        # on the initial '—' placeholder.
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        m = re.search(r"function applyStatus\(s\) \{[\s\S]+?\n  \}\s*\n\s*async function refreshStatus", html)
        assert m, "applyStatus body not found"
        body = m.group(0)
        assert "setBle(!!s.ble_connected)" in body, (
            "applyStatus must drive setBle from s.ble_connected"
        )

    def test_html_setBle_initialized_on_boot(self):
        # Boot section must call setBle(false) so the indicator shows
        # 'Disconnected' immediately on first paint rather than '—'.
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        # Look at the tail script block (after "// ---- Boot -----").
        tail = html[html.rfind("// ---- Boot"):]
        assert "setBle(false)" in tail, "boot section must initialize setBle(false)"

    def test_html_renderOutput_seeds_missing_cfg(self):
        # renderOutput(o) must not throw when state.outputs[o.id] is
        # undefined (e.g. partial /api/config response). It should seed
        # a defaults object before reading cfg.direction.
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        m = re.search(r"function renderOutput\([\s\S]+?\n  return card;\n\}", html)
        assert m, "renderOutput body not found"
        body = m.group(0)
        assert "!state.outputs[o.id]" in body, (
            "renderOutput must guard against undefined state.outputs[o.id]"
        )
        # Defaults seeded inline must include the keys the rest of the
        # function reads (direction, primary, etc.).
        assert "direction:" in body
        assert "primary:" in body

    def test_html_liveTick_safe_against_partial_gp(self):
        # liveTick must clamp every gp field it touches so a malformed
        # WS frame (missing lx/ly/lx/etc.) never throws.
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        m = re.search(r"function liveTick\([\s\S]+?\n\}\s*\n\s*function setBle", html)
        assert m, "liveTick body not found"
        body = m.group(0)
        for field in ("lx", "ly", "rx", "ry", "lt", "rt"):
            assert f"typeof gp.{field} === 'number'" in body, (
                f"liveTick must guard gp.{field} with typeof number check"
            )

    def test_html_renderButtonChips_safe_against_partial_gp(self):
        # renderButtonChips must guard buttons/dpad so a partial WS frame
        # doesn't crash on `undefined >> i`.
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        m = re.search(r"function renderButtonChips\([\s\S]+?\n\}\s*\n\s*function drawStick", html)
        assert m, "renderButtonChips body not found"
        body = m.group(0)
        assert "typeof gp.buttons === 'number'" in body
        assert "typeof gp.dpad === 'number'" in body

    def test_platformio_ini_defaults_bench_to_off(self):
        # Production env must NOT define BENCH_HID_PUBLIC=1 (no flag = default 0).
        # A separate dev env is allowed to set it to 1.
        ini = (PROJECT_ROOT / "platformio.ini").read_text()
        prod_match = re.search(
            r"\[env:esp32-c3-devkitc-02\]\n[^\[]*", ini)
        assert prod_match, "esp32-c3-devkitc-02 env not found"
        prod_block = prod_match.group(0)
        assert "BENCH_HID_PUBLIC=1" not in prod_block, (
            "production env must NOT compile bench code in"
        )
        # Dev env must exist with the flag on.
        dev_match = re.search(
            r"\[env:esp32-c3-devkitc-02-dev\]\n[^\[]*", ini)
        assert dev_match, "esp32-c3-devkitc-02-dev env not found"
        dev_block = dev_match.group(0)
        assert "BENCH_HID_PUBLIC=1" in dev_block, "dev env must define BENCH_HID_PUBLIC=1"

    def test_bench_hid_endpoint_registered_for_autonomous_parser_replay(self):
        wc_text = (PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp").read_text()
        assert '"/api/bench/hid"' in wc_text
        assert "ble_gamepad_bench_inject_hid_report" in wc_text
        assert '"hex"' in wc_text

    def test_bench_inject_uses_same_hid_parser(self, ble_src_text):
        assert "ble_gamepad_bench_inject_hid_report" in ble_src_text
        m = re.search(r"esp_err_t ble_gamepad_bench_inject_hid_report[\s\S]+?\n\}", ble_src_text)
        assert m, "bench inject function not found"
        body = m.group(0)
        assert "parse_hid_report(data, len)" in body
        assert "notify_connection_change(true" in body

    def test_ws_state_ltrt_mapping_is_not_swapped(self):
        # Regression: the WS payload used to send "lt": cs.rightTrigger
        # and "rt": cs.leftTrigger, which swapped the L2/R2 bars on the
        # Controller tab. The labels must match the field source.
        wc_text = (PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp").read_text()
        # Find the line where the trigger fields are passed to snprintf.
        # Must be in left-then-right order to match the JSON keys "lt"/"rt".
        m = re.search(
            r"cs\.leftStickX,\s*cs\.leftStickY,\s*cs\.rightStickX,\s*cs\.rightStickY,\s*\n\s*cs\.(leftTrigger|rightTrigger),\s*cs\.(leftTrigger|rightTrigger),",
            wc_text,
        )
        assert m, "trigger arg order not found in web_config.cpp"
        assert m.group(1) == "leftTrigger" and m.group(2) == "rightTrigger", (
            f"triggers swapped in WS payload: {m.group(0)!r}"
        )

    def test_ws_live_feed_rate_stays_below_queue_pressure_threshold(self):
        # Regression: 30Hz textAll() on ESPAsyncWebServer AP mode can fill
        # AsyncWebSocket client queues, creating seconds of visible UI lag.
        wc_text = (PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp").read_text()
        m = re.search(r"#define\s+GAMEPAD_TICK_HZ\s+(\d+)", wc_text)
        assert m, "GAMEPAD_TICK_HZ define missing"
        assert int(m.group(1)) <= 20

    def test_ws_tick_drops_frames_when_clients_not_writable(self):
        # The WS tick must not queue stale controller states when clients are
        # backed up. It should cleanup clients and skip textAll() unless all
        # clients are writable.
        wc_text = (PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp").read_text()
        m = re.search(r"static void gamepad_ws_tick\(void\) \{[\s\S]+?\n\}", wc_text)
        assert m, "gamepad_ws_tick() not found"
        body = m.group(0)
        assert "ws->cleanupClients();" in body
        assert "!ws->availableForWriteAll()" in body
        assert "s_gp.broadcast_pending = true" in body
        assert body.index("!ws->availableForWriteAll()") < body.index("ws->textAll(buf)")

    def test_ws_immediate_broadcast_checks_client_writability(self):
        wc_text = (PROJECT_ROOT / "components" / "web_config" / "src" / "web_config.cpp").read_text()
        m = re.search(r"static void gamepad_ws_broadcast_now\(void\) \{[\s\S]+?\n\}", wc_text)
        assert m, "gamepad_ws_broadcast_now() not found"
        body = m.group(0)
        assert "ws->cleanupClients();" in body
        assert "!ws->availableForWriteAll()" in body
        assert body.index("!ws->availableForWriteAll()") < body.index("ws->textAll(buf)")

    def test_mockup_handles_ws_pairing_field(self):
        mockup = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text()
        assert "msg.pairing" in mockup
        assert "pair-state" in mockup


# ---------------------------------------------------------------------------
# Patch parser logic — verified against the source patterns.
# ---------------------------------------------------------------------------

class TestOutputConfigPatchParser:
    @pytest.fixture(scope="class")
    def src_text(self) -> str:
        return OC_SRC.read_text()

    def test_patch_accepts_documented_keys(self, src_text):
        m = re.search(r"apply_patch_one\([^)]*\)[\s\S]+?\n\}", src_text)
        body = m.group(0) if m else ""
        for key in ("direction", "servo_mode", "primary", "secondary", "deadzone"):
            assert f'"{key}"' in body, f"patch parser missing key {key}"
        assert '"drive_mode"' in src_text

    def test_patch_validates_direction_values(self, src_text):
        m = re.search(r"apply_patch_one[\s\S]+?\n\}", src_text)
        body = m.group(0) if m else ""
        # Must reject anything other than normal/reversed.
        assert '"normal"' in body and '"reversed"' in body
        assert "return false" in body  # invalid value branch

    def test_patch_validates_servo_values(self, src_text):
        m = re.search(r"apply_patch_one[\s\S]+?\n\}", src_text)
        body = m.group(0) if m else ""
        assert '"bi"' in body and '"uni"' in body

    def test_patch_validates_deadzone_range(self, src_text):
        m = re.search(r"apply_patch_one[\s\S]+?\n\}", src_text)
        body = m.group(0) if m else ""
        # Should refuse deadzone > 50 (0..50 range).
        assert "d < 0 || d > 50" in body

    def test_patch_returns_invalid_arg_on_malformed_json(self, src_text):
        # The top-level apply function should return ESP_ERR_INVALID_ARG
        # when the JSON doesn't start with '{'.
        m = re.search(r"output_config_apply_json_patch\([^)]*\)[\s\S]+?\n\}", src_text)
        body = m.group(0) if m else ""
        assert "return ESP_ERR_INVALID_ARG" in body

    def test_config_json_closes_each_output_once(self, src_text):
        # Regression: /api/config emitted `"M1":{...}},"M2"...`,
        # which was invalid JSON even though truncated curl output looked OK.
        block = re.search(r"int output_config_to_json[\s\S]+?int output_config_sources_to_json", src_text)
        assert block, "output_config_to_json missing"
        body = block.group(0)
        assert 'json_append_raw(out_buf, out_buf_len, &used, "}");' in body
        assert 'json_append_raw(out_buf, out_buf_len, &used, "}}");\n    }' not in body

    def test_patch_parser_accepts_numeric_deadzone_and_top_level_commas(self, src_text):
        # The HTML sends deadzone as a JSON number and saves all outputs in
        # one patch object, so POST /api/config must accept both.
        assert "strtol(p, &end, 10)" in src_text
        assert "if (*p == ',') p++;" in src_text


# ---------------------------------------------------------------------------
# web_config integration
# ---------------------------------------------------------------------------

class TestWebConfigApiRoutes:
    @pytest.fixture(scope="class")
    def wc_text(self) -> str:
        return WC_SRC.read_text()

    @pytest.fixture(scope="class")
    def gen_text(self) -> str:
        p = PROJECT_ROOT / "components" / "web_config" / "src" / "web_index_gen.h"
        return p.read_text() if p.exists() else ""

    def test_api_config_route_present(self, wc_text):
        assert '"/api/config"' in wc_text
        assert "HTTP_GET" in wc_text.split('"/api/config"')[1].split('//')[0]

    def test_api_config_sources_route_present(self, wc_text):
        assert '"/api/config/sources"' in wc_text

    def test_api_config_sources_registered_before_generic_config(self, wc_text):
        # ESPAsyncWebServer route matching can let the shorter /api/config
        # handler consume /api/config/sources if the generic route is added
        # first. The longer route must be registered first.
        assert wc_text.index('"/api/config/sources"') < wc_text.index('"/api/config"')

    def test_json_buffer_large_enough_for_sources(self):
        header = (PROJECT_ROOT / "components" / "output_config" / "include" / "output_config.h").read_text()
        m = re.search(r"#define\s+OC_JSON_BUF_SIZE\s+(\d+)", header)
        assert m and int(m.group(1)) >= 2048

    def test_api_config_post_uses_body_handler(self, wc_text):
        # ESPAsyncWebServer 3.6.0 requires an upload handler (we pass NULL)
        # and a body handler with signature (req, uint8_t*, size_t, size_t, size_t).
        assert "uint8_t *data, size_t len" in wc_text
        assert "static_cast<String *>(req->_tempObject)" in wc_text

    def test_init_calls_output_config_init(self, wc_text):
        m = re.search(r"web_config_init\([^{]*\{[\s\S]+?\}", wc_text)
        body = m.group(0) if m else ""
        assert "output_config_init" in body

    def test_chunks_2_3_wiring(self, wc_text, gen_text):
        # Chunk 2: web_index_gen.h is included AND was generated from the
        # HTML mockup (the page body should be present in the generated
        # header). This means the firmware serves the real mockup HTML
        # at "/" rather than the old inline placeholder.
        assert "web_index_gen.h" in wc_text
        assert "INDEX_HTML" in gen_text or "INDEX_HTML" in wc_text
        # The generated HTML must contain the mockup's signature markers.
        assert "Combat Robot v2" in gen_text, "generated HTML missing page title"
        assert "8BitDo" not in gen_text or "8BitDo Ultimate" in gen_text
        # Chunk 3: AsyncWebSocket created and event handler registered.
        assert "new AsyncWebSocket" in wc_text
        assert "addHandler(ws)" in wc_text
        assert "ble_gamepad_set_connection_callback" in wc_text
        assert "gamepad_ws_tick" in wc_text
        # The handler builds the expected state JSON with numeric stick values.
        # In C source the leading " is escaped, so look for the escaped form.
        assert '\\"lx\\":%d' in wc_text
        assert '\\"buttons\\":%u' in wc_text

    def test_pairing_state_in_ws_feed(self, wc_text):
        # Bug fix: the WS state message must carry a `pairing` field so the
        # page can show ACCEPT/IDLE without polling /api/status. Pairing
        # endpoints and BLE callbacks must request a broadcast immediately.
        # The actual ws->textAll call is intentionally deferred to the web
        # loop; AsyncWebServer/AsyncTCP are unsafe from NimBLE callbacks.
        assert '\\"pairing\\":\\"%s\\"' in wc_text, "WS feed must include pairing state"
        assert "gamepad_ws_broadcast_now" in wc_text
        assert "broadcast_pending" in wc_text
        for path in ("/api/pair/start", "/api/pair/cancel", "/api/pair/clear"):
            block = wc_text.split(path, 1)
            assert len(block) > 1, f"no handler block for {path}"
            next_300_chars = block[1][:600]
            assert "broadcast_pending = true" in next_300_chars, (
                f"{path} handler doesn't request a deferred WS broadcast"
            )
        cb_block = wc_text.split("on_ble_connection_change(bool connected", 1)
        assert len(cb_block) > 1, "no on_ble_connection_change definition"
        body_open = cb_block[1].find("{")
        assert body_open >= 0, "on_ble_connection_change has no {"
        depth = 0
        i = body_open
        while i < len(cb_block[1]):
            if cb_block[1][i] == "{": depth += 1
            elif cb_block[1][i] == "}":
                depth -= 1
                if depth == 0: break
            i += 1
        body = cb_block[1][body_open:i+1]
        assert "broadcast_pending = true" in body, \
            "on_ble_connection_change body doesn't request deferred WS broadcast"
        assert "gamepad_ws_broadcast_now" not in body, \
            "NimBLE callback must not call ws->textAll directly"


    def test_chunk_4_captive_portal(self, wc_text):
        # Captive portal: include DNSServer, start it in AP mode, process it
        # in the loop, and the onNotFound handler already redirects to "/".
        assert "#include <DNSServer.h>" in wc_text
        assert "DNSServer       dnsServer" in wc_text
        assert "dnsServer.start(53" in wc_text
        assert "dnsServer.processNextRequest" in wc_text
        # Existing onNotFound redirects non-/api/ paths to "/" — required
        # for the portal to work end-to-end.
        assert "req->redirect(\"/\")" in wc_text


# ---------------------------------------------------------------------------
# HTML mockup — make sure it covers everything the firmware API does
# ---------------------------------------------------------------------------

class TestConfigUiMockup:
    @pytest.fixture(scope="class")
    def html(self) -> str:
        return (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text()

    @pytest.fixture(scope="class")
    def gen_html(self) -> str:
        # What the firmware actually serves at "/" is the GENERATED
        # header, which is the mockup wrapped as a C raw literal.
        p = PROJECT_ROOT / "components" / "web_config" / "src" / "web_index_gen.h"
        return p.read_text() if p.exists() else ""

    def test_has_tabs(self, html):
        for tab in ("Controller", "Outputs", "Settings", "About"):
            assert f">{tab}<" in html, f"tab '{tab}' missing from HTML"

    def test_has_pairing_in_controller_tab(self, html):
        # Pairing lives on the Controller tab — must be present.
        assert "Enter Pairing Mode" in html
        assert "Cancel" in html
        assert "Clear All Paired Controllers" in html
        # Pairing endpoints MUST be wired.
        assert "/api/pair/start" in html
        assert "/api/pair/cancel" in html
        assert "/api/pair/clear" in html

    def test_has_ota_in_settings_tab(self, html):
        # OTA form must reference /api/ota with multipart/form-data.
        assert "/api/ota" in html
        assert 'enctype="multipart/form-data"' in html
        assert 'type="file"' in html
        assert 'accept=".bin"' in html

    def test_has_wifi_status_in_settings(self, html):
        # The Settings tab shows WiFi mode/IP.
        assert "wifi-mode" in html
        assert "wifi-ip" in html

    def test_has_board_rev_in_settings(self, html):
        # Board-rev override buttons must hit /api/board/rev.
        assert "/api/board/rev" in html
        assert "/api/board/reset" in html

    def test_lists_all_outputs(self, html):
        for id_ in ("M1", "M2", "Weapon", "S1", "S2"):
            assert f"id: '{id_}'" in html or id_ in html

    def test_lists_all_sources(self, html):
        s = re.search(r"const SOURCES\s*=\s*\[([\s\S]+?)\];", html)
        body = s.group(1) if s else ""
        for tok in ("LX", "LY", "RX", "RY", "LT", "RT",
                    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
                    "SELECT", "START", "L3", "R3", "HOME",
                    "A", "B", "X", "Y", "L1", "R1", "L2", "R2", "NONE"):
            assert f"'{tok}'" in body or f'"{tok}"' in body

    def test_output_ui_reset_defaults_match_tank_drive(self, html):
        assert "state.drive_mode = 'tank_split';" in html
        assert "M2:     { direction: 'normal', servo_mode: 'bi',  deadzone: 10, primary: 'RY'" in html

    def test_output_ui_explains_signed_stick_mapping(self, html):
        # UX regression: assigning Left Stick Y to a drive motor means the
        # one signed axis drives both directions (above center forward,
        # below center reverse). The UI must say that directly rather than
        # implying separate forward/reverse inputs are required.
        assert "Drive input (center = stop)" in html
        assert "above center = forward, below center = reverse" in html
        assert "Optional reverse-only input" in html

    def test_output_ui_renders_drive_mode_selector(self, html):
        assert "const DRIVE_MODES = [" in html
        for mode in ("tank_split", "arcade_left", "arcade_right", "arcade_split"):
            assert mode in html
        assert "Driving Style" in html
        assert "Saved to NVS and used by the runtime drive mixer after Save." in html
        assert "Drive mode is live:" in html

    def test_output_ui_renders_live_mock_robot_preview(self, html):
        assert "Mock robot output" in html
        assert "function mockDriveOutput(mode, gp)" in html
        assert "function renderMockRobot(out)" in html
        assert "mock-left-dir" in html
        assert "mock-right-dir" in html
        assert "mock-left-bar" in html
        assert "mock-right-bar" in html
        assert "state.mockDrive = mockDriveOutput(state.drive_mode, state.gp);" in html

    def test_direction_toggle_input_precedes_label_for_checked_css(self, html):
        # CSS uses `.toggle input:checked + label`; the input must be
        # appended immediately before the label or the selected option will
        # never be highlighted.
        assert "input:checked + label" in html
        assert "wrap.appendChild(inp);" in html
        assert "wrap.appendChild(lab);" in html
        assert "wrap.appendChild(make('normal',   'Normal')[1])" not in html

    def test_hash_deep_links_to_outputs_tab(self, html):
        # #outputs previously opened the Controller tab because the code
        # validated hashes against OUTPUTS (M1/M2/etc.) instead of tab names.
        assert "const TAB_NAMES = ['controller', 'outputs', 'settings', 'about'];" in html
        assert "function tabFromHash()" in html
        assert "TAB_NAMES.includes(h)" in html
        assert "hashchange" in html

    def test_save_payload_sends_only_editable_output_fields(self, html):
        # /api/config accepts only editable fields; read-only fields like
        # numeric id/display_name must not be echoed back or browser Save 400s.
        assert "function editableOutputPatch(outputs)" in html
        assert "apiPostJSON('/api/config', editableOutputPatch(state.outputs))" in html
        m = re.search(r"function editableOutputPatch[\s\S]+?document.getElementById\('btn-save'", html)
        assert m, "editableOutputPatch/save block missing"
        body = m.group(0)
        for field in ("drive_mode", "direction", "servo_mode", "deadzone", "primary", "secondary"):
            assert field in body
        assert "display_name" not in body
        assert "id:" not in body

    def test_each_output_rendered_with_dropdowns(self, html):
        # The renderOutput() function must include primary, secondary
        # dropdown + direction toggle + deadzone for motors and servo_mode
        # for servos.
        m = re.search(r"function renderOutput\([\s\S]+?\n\}\s*", html)
        assert m, "renderOutput() missing"
        body = m.group(0)
        for tok in ("sourceSelect", "directionToggle", "servo_mode",
                    "deadzone", "isServo"):
            assert tok in body, f"renderOutput missing {tok}"
        ok_ = m is not None

    def test_has_live_stick_canvases(self, html):
        assert "<canvas" in html
        assert "Left Stick" in html and "Right Stick" in html

    def test_has_button_chip_strip(self, html):
        for tag in ("btn-chip", "L1 Bumper", "R1 Bumper", "D-Pad Up"):
            assert tag in html

    def test_has_save_and_reset(self, html):
        assert "btn-save" in html and "btn-reset" in html

    def test_chunks_2_3_real_fetch_and_ws(self, gen_html):
        # The mockup calls /api/config for both the load-on-boot and the
        # save-on-button, and it connects to /ws for live state.
        assert "/api/config" in gen_html
        assert "fetch(`${API_BASE}" in gen_html
        assert "method: 'POST'" in gen_html
        assert "application/json" in gen_html
        assert "JSON.stringify" in gen_html
        assert "new WebSocket" in gen_html
        assert "/ws`" in gen_html
        assert "msg.type === 'state'" in gen_html
