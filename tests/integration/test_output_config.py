"""Schema and source-level tests for the output_config component.

This test verifies the design contracts the new web UI depends on,
WITHOUT requiring an Arduino build. It's an integration test against
the C source on disk, matching the project's existing pattern of
static + parse-based host tests.

What's verified:
  * OutputConfig component registers cleanly in the PIO build (has
    library.json, src/, include/, CMakeLists.txt, REQUIRES nvs_flash).
  * The JSON schema emitted by output_config_to_json() includes every
    current logical outputs (M1, M2, S1, S2) and every input source
    (LX, LY, RX, RY, LT, RT, A, B, X, Y, L1, R1, L2, R2, SELECT,
    START, L3, R3, HOME, DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT,
    NONE).
  * The web_config handler exposes /api/config, /api/config/sources,
    and the POST body handler that calls
    output_config_apply_json_patch().
  * Defaults describe current hard-coded tank drive:
        M1: LY primary, M2: RY primary, normal direction, bi servo_mode (motor)
        S1/S2: NONE, servo/aux defaults
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

    def test_root_html_route_uses_explicit_progmem_response_length(self):
        text = WC_SRC.read_text()
        root_route = re.search(
            r'server->on\("/",\s*HTTP_GET,\s*\[\]\(AsyncWebServerRequest \*req\) \{(?P<body>.*?)\n    \}\);',
            text,
            re.S,
        )
        assert root_route, "root HTML route not found"
        body = root_route.group("body")
        assert "beginResponse_P" in body
        assert "strlen_P(INDEX_HTML)" in body
        assert "send_P" not in body


# ---------------------------------------------------------------------------
# Public API surface in the header
# ---------------------------------------------------------------------------

EXPECTED_OUTPUT_IDS = {"M1", "M2", "S1", "S2"}

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
            "output_config_get_max_paired",
            "output_config_set_max_paired",
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
        # Defaults: M1 -> LY primary, M2 -> RY primary, S1/S2 -> NONE,
        # all "normal" direction, deadzone 10.
        m = re.search(r"kDefaults\[OC_OUT__COUNT\]\s*=\s*\{([\s\S]+?)\};", src_text)
        assert m, "kDefaults not found"
        defaults_blob = m.group(1)

        # Spot-check each.
        assert re.search(r"OC_OUT_M1\][^}]*OC_SRC_LY", defaults_blob)
        assert re.search(r"OC_OUT_M2\][^}]*OC_SRC_RY", defaults_blob)
        assert "OC_OUT_WEAPON" not in defaults_blob
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

    def test_runtime_composable_drive_setup_switches_mixers(self):
        tm = (PROJECT_ROOT / "components" / "myrobot" / "src" / "TaskManager.cpp").read_text()
        assert '#include "output_config.h"' in tm
        assert "output_config_init();" in tm
        assert "output_config_get_drive_setup()" in tm
        assert "driveSetup->layout == OC_DRIVE_LAYOUT_SERVO_STEERING" in tm
        assert "driveSetup->method == OC_DRIVE_METHOD_ARCADE" in tm
        assert "readDriveAxis(driveSetup->throttle_axis" in tm
        assert "readDriveAxis(driveSetup->steering_axis" in tm
        assert "drive.combined_direction(steering, throttle" in tm
        assert "drive.two_stick_drive(left, right" in tm
        assert "drive.single_motor_drive" in tm
        assert "updateSteeringServo" in tm

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

class TestBleGamepadPairingCallbackWiring:
    # Regression: LED1 never blinked in pairing mode because nothing
    # wired ble_gamepad_set_pairing_state() to the LED driver. The
    # contract now is that the BLE subsystem must expose a pairing
    # callback hook and invoke it on every state transition.
    BLE_HDR = PROJECT_ROOT / "components" / "ble_gamepad" / "include" / "ble_gamepad.h"
    BLE_SRC = PROJECT_ROOT / "components" / "ble_gamepad" / "src" / "ble_gamepad.cpp"
    SKETCH  = PROJECT_ROOT / "main" / "sketch.cpp"

    def test_pairing_callback_is_in_public_header(self):
        text = self.BLE_HDR.read_text()
        assert "ble_pairing_callback_t" in text
        assert "ble_gamepad_set_pairing_callback" in text

    def test_pairing_callback_invoked_on_state_change(self):
        text = self.BLE_SRC.read_text()
        # Pairing callback must be stored on s_state and invoked at least
        # at the end of ble_gamepad_set_pairing_state() with the new state.
        assert "s_state.pairing_cb" in text
        m = re.search(
            r"esp_err_t\s+ble_gamepad_set_pairing_state\s*\([\s\S]+?\n\}\s*",
            text)
        assert m, "ble_gamepad_set_pairing_state() body not found"
        body = m.group(0)
        assert "s_state.pairing_cb" in body, (
            "set_pairing_state() must invoke s_state.pairing_cb on transition"
        )

    def test_sketch_wires_pairing_callback_to_led(self):
        # sketch.cpp must register a pairing callback that drives LED1
        # so that POST /api/pair/start actually flashes the LED.
        text = self.SKETCH.read_text()
        assert "ble_gamepad_set_pairing_callback" in text
        assert "DEBUG_LED_PIN" in text

    def test_pairing_state_change_on_connect_uses_public_setter(self):
        # Regression: LED1 kept blinking after a successful pair because
        # the connect path mutated s_state.pairing_state directly and
        # skipped the registered pairing callback. The fix is to go
        # through ble_gamepad_set_pairing_state(PAIRING_STATE_IDLE) on
        # connect so pairing_cb is invoked and the LED stops blinking.
        text = self.BLE_SRC.read_text()
        # Locate the body that handles "subscribed to HID reports" / pair-lock.
        m = re.search(
            r"s_state\.connected\s*=\s*true;[\s\S]+?notify_connection_change\(true[\s\S]+?return true;",
            text)
        assert m, "connect-lock block not found"
        body = m.group(0)
        # Must go through the public setter, not direct field write.
        assert "s_state.pairing_state = PAIRING_STATE_IDLE" not in body, (
            "connect path must not mutate s_state.pairing_state directly; "
            "use ble_gamepad_set_pairing_state(PAIRING_STATE_IDLE) so the "
            "pairing callback fires and the LED stops blinking."
        )
        assert "ble_gamepad_set_pairing_state(PAIRING_STATE_IDLE)" in body

class TestLegacyMyrobotPinsMatchBoardConfig:
    # myrobot still consumes the legacy Constants.h pin names, but the
    # authoritative v2 pin map lives in board_config.h. These aliases must
    # stay aligned or firmware will toggle the wrong physical GPIO (the bug
    # that made LED1/SW1 appear broken).
    CONST_HDR = PROJECT_ROOT / "components" / "myrobot" / "include" / "Constants.h"
    BOARD_HDR = PROJECT_ROOT / "components" / "board_config" / "include" / "board_config.h"

    def _define(self, text: str, name: str) -> int:
        m = re.search(rf"#define\s+{name}\s+(\d+)", text)
        assert m, f"{name} not defined"
        return int(m.group(1))

    def _v2_define(self, text: str, name: str) -> int:
        m = re.search(rf"#if BOARD_REV == 2(?P<body>[\s\S]*?)#elif BOARD_REV == 3", text)
        assert m, "BOARD_REV == 2 block not found"
        return self._define(m.group("body"), name)

    def test_legacy_drive_motor_pins_match_v2_board_config(self):
        constants = self.CONST_HDR.read_text()
        board = self.BOARD_HDR.read_text()
        assert self._define(constants, "DRIVE_MOTOR1_1_PIN") == self._v2_define(board, "PIN_MOTOR1_IN1")
        assert self._define(constants, "DRIVE_MOTOR1_2_PIN") == self._v2_define(board, "PIN_MOTOR1_IN2")
        assert self._define(constants, "DRIVE_MOTOR2_1_PIN") == self._v2_define(board, "PIN_MOTOR2_IN1")
        assert self._define(constants, "DRIVE_MOTOR2_2_PIN") == self._v2_define(board, "PIN_MOTOR2_IN2")

    def test_legacy_sw1_led_and_battery_pins_match_v2_board_config(self):
        constants = self.CONST_HDR.read_text()
        board = self.BOARD_HDR.read_text()
        assert self._define(constants, "MODE_BUTTON_PIN") == self._v2_define(board, "PIN_MODE_BUTTON")
        assert self._define(constants, "DEBUG_LED_PIN") == self._v2_define(board, "PIN_DEBUG_LED")
        assert self._define(constants, "BATT_MEAS_PIN") == self._v2_define(board, "PIN_BATT_MEAS")
        # Live-board correction from Kevin: v2 SW1/ModeButton is IO5 and LED1 is IO10.
        assert self._define(constants, "MODE_BUTTON_PIN") == 5
        assert self._define(constants, "DEBUG_LED_PIN") == 10

class TestLed1GpioOwnership:
    # Regression: LED1 (DEBUG_LED_PIN) must not be claimed by the LEDC
    # peripheral anywhere in the project. The LED class used ledcAttachPin
    # to bind the pin to an LEDC channel, which silently disables
    # digitalWrite() and made the pairing indicator a no-op.
    CONST_HDR  = PROJECT_ROOT / "components" / "myrobot" / "include" / "Constants.h"
    LED_SRC    = PROJECT_ROOT / "components" / "myrobot" / "src" / "LED.cpp"
    SKETCH     = PROJECT_ROOT / "main" / "sketch.cpp"
    LED_HDR    = PROJECT_ROOT / "components" / "myrobot" / "include" / "LED.h"

    def _pin_number(self) -> int:
        m = re.search(r"#define\s+DEBUG_LED_PIN\s+(\d+)", self.CONST_HDR.read_text())
        assert m, "DEBUG_LED_PIN not defined"
        return int(m.group(1))

    def test_no_ledc_attach_for_debug_led_pin(self):
        pin = self._pin_number()
        offenders = []
        pattern = re.compile(r"ledcAttachPin\s*\(\s*([^,()]+)\s*,\s*[^)]+\)")
        for label, path in (("LED.cpp", self.LED_SRC), ("sketch.cpp", self.SKETCH)):
            text = path.read_text()
            for m in pattern.finditer(text):
                first = m.group(1).strip()
                if first == "led_pin" or first == str(pin):
                    offenders.append(f"{label}: {m.group(0)}")
        assert not offenders, (
            f"LEDC must not bind DEBUG_LED_PIN (pin {pin}); offenders: {offenders}"
        )

    def test_led1_task_drives_pin_via_digitalwrite(self):
        # The pairing-indicator task must drive DEBUG_LED_PIN via plain
        # digitalWrite() so it actually reaches the pad.
        text = self.SKETCH.read_text()
        pin = self._pin_number()
        m = re.search(
            r"static void led1_indicator_task[\s\S]+?vTaskDelay\(pdMS_TO_TICKS\(20\)\);",
            text)
        assert m, "led1_indicator_task() body not found"
        body = m.group(0)
        assert f"pinMode(DEBUG_LED_PIN, OUTPUT)" in body
        assert f"digitalWrite(DEBUG_LED_PIN" in body
        # And no LEDC calls inside the task (would shadow the GPIO matrix).
        assert "ledcWrite" not in body
        assert "ledcAttachPin" not in body

    def test_led_class_uses_digitalwrite_for_pattern_output(self):
        # LED::begin() must not call ledcAttachPin on the LED1 pin, and
        # LED::patternTask() must drive the pin via digitalWrite so the
        # morse feedback coexists with the pairing indicator.
        text = self.LED_SRC.read_text()
        assert "ledcAttachPin" not in text, (
            "LED class must not bind any pin to LEDC; the pairing indicator "
            "and the morse patterns must share the pin via digital control."
        )
        assert "ledcWrite" not in text
        assert "pinMode(led_pin, OUTPUT)" in text
        assert "digitalWrite(led_pin" in text

class TestSw1LongPressClearsAndPairs:
    # SW1 is the v2 board's MODE_BUTTON_PIN (GPIO5). Holding it for 5s
    # must clear the controller whitelist and enter pairing mode. The
    # HTML must auto-reflect the new state without a page reload.
    CONST_HDR  = PROJECT_ROOT / "components" / "myrobot" / "include" / "Constants.h"
    BTN_SRC    = PROJECT_ROOT / "components" / "myrobot" / "src" / "Buttons.cpp"
    BTN_HDR    = PROJECT_ROOT / "components" / "myrobot" / "include" / "Buttons.h"
    TM_SRC     = PROJECT_ROOT / "components" / "myrobot" / "src" / "TaskManager.cpp"
    HTML_FILE  = PROJECT_ROOT / "docs" / "config-ui-mockup.html"

    def test_hold_5s_event_is_in_public_enum(self):
        text = self.CONST_HDR.read_text()
        assert "BUTTON_HOLD_5S" in text
        # 5000ms threshold must live in Constants.h so it can be tuned
        # without touching the Buttons implementation.
        m = re.search(r"#define\s+HOLD_5S_TIME\s+(\d+)", text)
        assert m, "HOLD_5S_TIME not defined in Constants.h"
        assert int(m.group(1)) == 5000, "HOLD_5S_TIME must be 5000ms"

    def test_buttons_emits_hold_5s_after_threshold(self):
        text = self.BTN_SRC.read_text()
        hdr = self.BTN_HDR.read_text()
        # Regression: BUTTON_LONG fires at 1s. The 5s hold must still be
        # able to fire later during the same physical press, so BUTTON_HOLD_5S
        # cannot be guarded by the same one-shot eventSent flag.
        assert "HOLD_5S_TIME" in text
        assert "BUTTON_HOLD_5S" in text
        assert "longEventSent" in hdr and "hold5sEventSent" in hdr, (
            "BUTTON_LONG and BUTTON_HOLD_5S need independent one-shot guards"
        )
        assert "!hold5sEventSent" in text, "5s branch must use its own guard"
        assert "!longEventSent" in text, "1s long branch must use its own guard"
        hold_idx = text.find("BUTTON_HOLD_5S")
        long_idx = text.find("BUTTON_LONG")
        assert hold_idx != -1 and long_idx != -1
        assert hold_idx < long_idx, (
            "check the 5s hold threshold before the 1s long threshold so an "
            "already-long press can still become BUTTON_HOLD_5S"
        )

    def test_taskmanager_reacts_to_hold_5s_by_clearing_and_pairing(self):
        text = self.TM_SRC.read_text()
        # The managerTask switch on buttonVal must handle BUTTON_HOLD_5S
        # by clearing the whitelist (which also enters pairing).
        m = re.search(
            r"ButtonPress\s+buttonVal\s*=\s*self->buttons\.checkForPress\(\)[\s\S]+?switch\(buttonVal\)[\s\S]+?default:\s*\n\s*break;",
            text)
        assert m, "buttonVal switch block not found"
        body = m.group(0)
        assert "case BUTTON_HOLD_5S" in body, "BUTTON_HOLD_5S not handled"
        assert "ble_gamepad_clear_paired_macs" in body, (
            "5s hold must clear the whitelist so a fresh controller can pair"
        )

    def test_clear_paired_macs_enters_pairing(self):
        # The existing helper must end with set_pairing_state(ACCEPT) so
        # the new HTML/LED wiring reacts automatically. This test is the
        # safety net that keeps both the LED indicator and the WS state
        # frame in sync with the button-driven clear.
        text = (PROJECT_ROOT / "components" / "ble_gamepad" / "src" / "ble_gamepad.cpp").read_text()
        m = re.search(
            r"esp_err_t ble_gamepad_clear_paired_macs\s*\([\s\S]+?\n\}",
            text)
        assert m, "ble_gamepad_clear_paired_macs() not found"
        body = m.group(0)
        assert "ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT)" in body

    def test_html_documents_hold_5s_gesture(self):
        # The pairing card on the Controller tab must surface the
        # SW1-hold-5s gesture so users know the keyboard-free path exists.
        text = self.HTML_FILE.read_text()
        assert "SW1" in text
        assert "hold SW1 5s" in text
        # The hint should sit inside the same pairing-action container as
        # the Enter Pairing button, so users see it together on screen.
        # Allow some surrounding whitespace/markup between the button and
        # the hint, but keep it tight (no more than a 500-byte offset).
        idx_pair = text.find("btn-pair")
        idx_hint = text.find("hold SW1 5s")
        assert idx_hint > 0, "hold-SW1 hint not found in HTML"
        assert idx_hint < idx_pair + 500, (
            "hold-SW1 hint must live near the pair button so users see it"
        )


    def test_led1_task_uses_connected_priority_when_not_pairing(self):
        # The LED task's else branch must drive the pin to:
        #   HIGH when a controller is connected
        #   LOW  when neither pairing nor connected
        # Reading these in the wrong order caused the LED to keep blinking
        # after a successful pair in the previous build.
        text = (PROJECT_ROOT / "main" / "sketch.cpp").read_text()
        m = re.search(
            r"static void led1_indicator_task[\s\S]+?vTaskDelay\(pdMS_TO_TICKS\(20\)\);",
            text)
        assert m, "led1_indicator_task() body not found"
        body = m.group(0)
        # Connected-state pin writes exist and reflect priority.
        assert "digitalWrite(DEBUG_LED_PIN, connected ? HIGH : LOW)" in body
        # The LED task must read both flags under the spinlock so the
        # output never sees a torn read.
        assert "portENTER_CRITICAL(&g_led1_lock)" in body
        assert "g_pairing_led_active" in body
        assert "g_connected_led_active" in body
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
        assert "len >= 10 && data[0] == 0x01 && data[1] <= 0x0f" in ble_src_text
        assert "parse_8bitdo_report(data, 1);" in ble_src_text
        # 2026-07-05 fix: standard HID reports are 8-9 bytes; the old dispatcher
        # returned on len < 10 and silently dropped valid 9-byte reports such as
        # X/Y/RX/RY/buttons/L2/R2/hat. That made fresh controller input look dead
        # until a controller sent a longer vendor-specific report.
        assert "if (len < 8) return;" in ble_src_text
        assert "if (len < 10) return;" not in ble_src_text
        assert "len >= 9 && data[0] <= 0x0f" in ble_src_text
        assert "len > 12" not in ble_src_text, (
            "stale len > 12 condition silently drops short 8BitDo reports"
        )
        assert "parse_8bitdo_report(data, 0);" in ble_src_text



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
        assert "applyConnectedController(!!s.ble_connected, s.ble_mac)" in body, (
            "applyStatus must drive connected BLE state from /api/status"
        )

    def test_html_connected_mac_updates_from_status_and_ws(self):
        # Regression: after pairing a new controller, the page showed the
        # old paired/connected MAC until a manual reload. Status polling and
        # WS state frames must both flow through the same renderer so the
        # visible MAC updates live.
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        assert "function applyConnectedController(connected, mac)" in html

        m = re.search(r"function applyStatus\(s\) \{[\s\S]+?\n  \}\s*\n\s*async function refreshStatus", html)
        assert m, "applyStatus body not found"
        assert "applyConnectedController(!!s.ble_connected, s.ble_mac)" in m.group(0)

        m = re.search(r"ws\.onmessage = \(ev\) => \{[\s\S]+?\n    \};", html)
        assert m, "ws.onmessage body not found"
        assert "applyConnectedController(!!msg.connected, msg.ble_mac)" in m.group(0)

    def test_html_setBle_initialized_on_boot(self):
        # Boot section must call setBle(false) so the indicator shows
        # 'Disconnected' immediately on first paint rather than '—'.
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        # Look at the tail script block (after "// ---- Boot -----").
        tail = html[html.rfind("// ---- Boot"):]
        assert "setBle(false)" in tail, "boot section must initialize setBle(false)"

    def test_outputs_page_uses_board_v2_inventory(self):
        html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text(encoding="utf-8")
        assert "const BOARD_OUTPUT_PROFILES" in html
        assert "board_v2" in html
        for token in (
            "Motor 1 / P1",
            "Motor 2 / P2",
            "Servo / ESC 1",
            "Servo / ESC 2",
            "Header H1",
            "configOnly: true",
            "SW1",
            "RGB / RGBW LED strip",
            "RGB / RGBW lighting plan",
            "LED count",
            "Rainbow",
            "Chaser / scanner",
            "Battery meter",
            "SW1 timing/actions",
            "Clear controllers and start pairing",
        ):
            assert token in html
        assert "display_name: 'UART'" not in html
        assert "display_name: 'LED1'" not in html
        assert "LED2 / RGB ignored for now" not in html

        output_block = re.search(r"const BOARD_OUTPUT_PROFILES = \{[\s\S]+?\n\};", html)
        assert output_block, "BOARD_OUTPUT_PROFILES missing"
        board_v2 = output_block.group(0)
        assert "Weapon / ESC" not in board_v2
        assert "id: 'Weapon'" not in board_v2

        render_body = re.search(r"function renderOutputs\([\s\S]+?\n\}", html)
        assert render_body, "renderOutputs() missing"
        assert "activeBoardProfile()" in render_body.group(0)
        assert "renderBoardIoCard" in html

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
        assert "s_state.bench_override_active = true" in body
        assert "notify_connection_change(true" in body

    def test_bench_override_blocks_real_ble_notify_until_real_disconnect_or_reconnect(self, ble_src_text):
        assert "bench_override_active" in ble_src_text
        notify = re.search(r"static void notify_cb[\s\S]+?\n\}", ble_src_text)
        assert notify, "notify_cb missing"
        assert "if (s_state.bench_override_active)" in notify.group(0)
        assert "return;" in notify.group(0)
        assert "s_state.bench_override_active = false;" in ble_src_text

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
        m = re.search(r"apply_patch_one\(.*\)[\s\S]+?\n\}", src_text)
        body = m.group(0) if m else ""
        for key in ("direction", "servo_mode", "primary", "secondary", "deadzone"):
            assert f'"{key}"' in body, f"patch parser missing key {key}"
        assert '"drive_mode"' in src_text
        assert '"max_paired"' in src_text

    def test_patch_validates_max_paired_range(self, src_text):
        # Should refuse max_paired outside [1, OC_MAX_PAIRED_CAP].
        # The parser validates n < 1 || n > OC_MAX_PAIRED_CAP.
        assert "n < 1 || n > OC_MAX_PAIRED_CAP" in src_text

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

    def test_to_json_serializes_max_paired_field(self, src_text):
        # /api/config JSON must include the runtime cap so the web UI can
        # pre-fill the input on first load.
        block = re.search(r"int output_config_to_json[\s\S]+?int output_config_sources_to_json", src_text)
        assert block, "output_config_to_json missing"
        body = block.group(0)
        # The C source contains the escaped JSON fragments, e.g. `,\"max_paired\":`
        # because the literal is inside a C double-quoted string.
        assert '\\"max_paired\\"' in body
        # Field should appear after drive_mode and before "outputs".
        i_drive = body.find('\\"drive_mode\\"')
        i_max = body.find('\\"max_paired\\"')
        i_outputs = body.find('\\"outputs\\"')
        assert i_drive > 0, "drive_mode literal not found in json output"
        assert i_max > i_drive, "max_paired must sit after drive_mode"
        assert i_outputs > i_max, "max_paired must sit before outputs"

    def test_patch_parser_validates_max_paired_bounds(self, src_text):
        # Belongs in patch-parser class, but we add it here for cohesion
        # with the other JSON-shape checks. The parser must reject values
        # outside [1, OC_MAX_PAIRED_CAP] without crashing.
        assert "n < 1 || n > OC_MAX_PAIRED_CAP" in src_text


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

    def test_connected_mac_available_to_status_and_ws_feed(self, wc_text):
        # When a newly paired controller connects, the HTML must learn its
        # MAC from live firmware state, not from a later page reload.
        h_text = (PROJECT_ROOT / "components" / "ble_gamepad" / "include" / "ble_gamepad.h").read_text()
        ble_src = (PROJECT_ROOT / "components" / "ble_gamepad" / "src" / "ble_gamepad.cpp").read_text()
        assert "ble_gamepad_get_connected_mac" in h_text
        assert "bool ble_gamepad_get_connected_mac(ble_mac_t *out)" in ble_src
        assert "ble_gamepad_get_connected_mac(&connected_mac)" in wc_text
        assert "mac_to_cstr(&connected_mac" in wc_text
        assert r'\"ble_mac\":\"%s\"' in wc_text
        assert 'strncpy(out->ble_mac, "connected"' not in wc_text

    def test_bench_control_routes_registered_before_hid_injection(self, wc_text):
        # ESPAsyncWebServer route matching can let the generic /api/bench/hid
        # handler shadow /api/bench/hid/enable. Register specific controls
        # first so live bench verification can enable runtime injection.
        enable_pos = wc_text.index('"/api/bench/hid/enable"')
        inject_pos = wc_text.index('"/api/bench/hid"')
        assert enable_pos < inject_pos

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
        for id_ in ("M1", "M2", "S1", "S2"):
            assert f"id: '{id_}'" in html or id_ in html
        assert "id: 'Weapon'" not in html
        assert "state.outputs.Weapon" not in html

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
        reset_match = re.search(r"state\.outputs\s*=\s*\{([\s\S]+?)\n\s*\};\n\s*renderOutputs\(\);", html)
        assert reset_match, "reset-default output block not found"
        reset_block = reset_match.group(1)
        for token in (
            "M2:",
            "direction: 'normal'",
            "servo_mode: 'bi'",
            "deadzone: 10",
            "primary: 'RY'",
            "purpose: 'drive'",
            "protocol: 'none'",
            "digital_mode: 'direct'",
            "digital_preset: 'direct'",
        ):
            assert token in reset_block

    def test_output_ui_explains_signed_stick_mapping(self, html):
        # UX regression: assigning Left Stick Y to a drive motor means the
        # one signed axis drives both directions (above center forward,
        # below center reverse). The UI must say that directly rather than
        # implying separate forward/reverse inputs are required.
        assert "Drive input (center = stop)" in html
        assert "above center = forward, below center = reverse" in html
        assert "Optional reverse-only input" in html

    def test_output_ui_renders_composable_drive_setup(self, html):
        assert "const DRIVE_LAYOUTS = [" in html
        assert "const DRIVE_METHODS" in html
        assert "const DRIVE_AXES" in html
        for token in ("differential", "servo_steering", "tank", "arcade", "RT_MINUS_LT", "DPAD_Y"):
            assert token in html
        assert "Driving Setup" in html
        assert "Drive layout" in html
        assert "Throttle source" in html
        assert "Steering source" in html
        assert "Advanced: drive modifiers" in html

    def test_motor_inputs_are_shown_as_drive_setup_controlled(self, html):
        # Runtime evaluation: TaskManager ignores M1/M2 primary dropdowns and
        # drives motors from composable Driving Setup. The UI must not imply
        # M1/M2 have independently assignable controller-source dropdowns.
        assert "runtimeControlled: true" in html
        assert "function runtimeDriveSources" in html
        assert "function runtimeDriveOutputs" in html
        assert "function renderRuntimeDriveAssignment" in html
        assert "Drive-setup controlled" in html

    def test_drive_sources_are_auto_reserved(self, html):
        # The current code shows drive-mode-controlled sources as selectable
        # (just disabled with "Used by Driving Style"). The new contract is
        # that the active drive mode automatically RESERVES those sources
        # and removes them from the available list for Servo / ESC
        # assignment, while still surfacing the reservation as a hint.
        for token in (
            "function reservedSourceSet()",
            "function selectableSources()",
            "function renderReservedSourcesBanner()",
            "const RESERVED_SOURCES = reservedSourceSet()",
            "for (const src of selectableSources())",
            "Drive setup reserved sources",
            "function sourceSelect(name, value, ownerId)",
            "function assignedSourceOwners(exceptOutputId)",
        ):
            assert token in html, f"missing {token}"
        # Selectable sources must NOT include anything that the active drive
        # mode owns, even when no other output has claimed it yet.
        assert "DRIVE_MODE_LEGACY" in html
        assert "tank_split" in html
        m = re.search(
            r"function selectableSources\(\)\s*\{([\s\S]+?)\n\}",
            html)
        assert m, "selectableSources() body not found"
        body = m.group(1)
        assert "reservedSourceSet()" in body
        # Reserved sources must be filtered out, and 'none' must always
        # remain selectable so an output can be cleared.
        assert "!reserved.has(src.id)" in body
        assert "src.id === 'NONE'" in body

    def test_assignable_sources_are_exclusive_in_outputs_ui(self, html):
        # A controller source already consumed by Driving Style or another
        # output must be unavailable in other output dropdowns. This prevents
        # assigning the same button/axis to multiple systems by accident.
        for token in (
            "function assignedSourceOwners(exceptOutputId)",
            "function sourceSelect(name, value, ownerId)",
            "option.disabled = true",
            "Used by ",
            "runtimeDriveSources()",
            "sourceSelect('primary', cfg.primary, o.id)",
            "sourceSelect('secondary', cfg.secondary, o.id)",
        ):
            assert token in html

    def test_controller_ui_has_max_paired_cap(self, html):
        # Controller tab must include the numeric input + Save handler
        # for the BLE whitelist cap. Mirrors BLE_RUNTIME_MAX_PAIRED_CAP = 4
        # at the input level (min="1" max="4").
        assert 'id="max-paired-input"' in html
        assert 'id="btn-max-paired-save"' in html
        assert 'min="1"' in html
        assert 'max="4"' in html
        # Save handler POSTs to /api/config/max_paired with JSON body.
        assert "apiPostJSON('/api/config/max_paired'" in html
        assert "{ max_paired: raw }" in html
        # State mirror + status/config hydration.
        assert "max_paired: 1" in html  # default in `state`
        assert "s.max_paired" in html   # /api/status hydration
        assert "j.max_paired" in html   # /api/config hydration

    def test_output_ui_renders_live_mock_robot_preview(self, html):
        assert "Mock robot output" in html
        assert "function mockDriveOutput(drive, gp)" in html
        assert "function renderMockRobot(out)" in html
        assert "mock-left-dir" in html
        assert "mock-right-dir" in html
        assert "mock-left-bar" in html
        assert "mock-right-bar" in html
        assert "state.mockDrive = mockDriveOutput(state.drive, state.gp);" in html

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
        # /api/config accepts editable schema-v2 output fields. Hardware IDs
        # remain read-only, but user display names and per-channel power policy
        # are now intentionally editable.
        assert "function editableOutputPatch(outputs)" in html
        assert "apiPostJSON('/api/config', editableOutputPatch(state.outputs))" in html
        m = re.search(r"function editableOutputPatch[\s\S]+?document.getElementById\('btn-save'", html)
        assert m, "editableOutputPatch/save block missing"
        body = m.group(0)
        for field in (
            "drive_mode", "display_name", "direction", "servo_mode", "deadzone",
            "primary", "secondary", "purpose", "protocol", "semantics",
            "power_good", "power_warn", "power_low",
        ):
            assert field in body
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

    def test_live_stick_view_uses_circular_gate(self, html):
        m = re.search(r"function drawStick\([\s\S]+?\n\}\s*\n\s*function liveTick", html)
        assert m, "drawStick body not found"
        body = m.group(0)
        assert "gateRadius" in body
        assert "ctx.arc(cx0, cy0, gateRadius" in body
        assert "ctx.clip()" in body
        assert "Math.hypot(nx, ny)" in body
        assert "strokeRect" not in body

    def test_has_button_chip_strip(self, html):
        for tag in ("btn-chip", "L1 Bumper", "R1 Bumper", "D-Pad Up"):
            assert tag in html

    def test_has_save_and_reset(self, html):
        assert "btn-save" in html and "btn-reset" in html

    def test_header_and_menu_bar_have_no_sticky_gap(self, html):
        assert "top: 51px" not in html
        assert "top: calc(44px + env(safe-area-inset-top))" in html

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

class TestBatteryManagementContract:
    """Battery telemetry/config must be visible and tunable from the web UI."""

    ROOT = PROJECT_ROOT
    WEB_CONFIG = ROOT / "components" / "web_config" / "src" / "web_config.cpp"
    WEB_HEADER = ROOT / "components" / "web_config" / "include" / "web_config.h"
    POWER_CPP = ROOT / "components" / "myrobot" / "src" / "PowerFunctions.cpp"
    POWER_H = ROOT / "components" / "myrobot" / "include" / "PowerFunctions.h"
    MOCKUP = ROOT / "docs" / "config-ui-mockup.html"
    PLATFORMIO = ROOT / "platformio.ini"
    BATTERY_H = ROOT / "components" / "battery_config" / "include" / "battery_config.h"
    BATTERY_C = ROOT / "components" / "battery_config" / "src" / "battery_config.c"

    def test_battery_config_component_is_registered(self):
        assert self.BATTERY_H.exists(), "battery_config public header missing"
        assert self.BATTERY_C.exists(), "battery_config implementation missing"
        header = self.BATTERY_H.read_text()
        src = self.BATTERY_C.read_text()
        pio = self.PLATFORMIO.read_text()
        assert "battery_config_init" in header
        assert "battery_config_to_json" in header
        assert "battery_config_apply_json_patch" in header
        assert "BC_NVS_NAMESPACE" in header and "battery_cfg" in header
        assert "nvs_set_u8" in src and "nvs_commit" in src
        assert "-I components/battery_config/include" in pio

    def test_power_functions_exposes_live_voltage_and_configurable_thresholds(self):
        header = self.POWER_H.read_text()
        src = self.POWER_CPP.read_text()
        assert "getBatteryMillivolts" in header
        assert "battery_config_get_cell_count" in src
        assert "battery_config_get_cutoff_percent" in src
        assert "BATTERY_EMPTY_MV_PER_CELL" in src
        assert "BATTERY_FULL_MV_PER_CELL" in src
        assert "shutdownVoltage_mV = battery_cutoff_millivolts" in src

    def test_status_json_reports_voltage_percent_cell_count_and_cutoff(self):
        header = self.WEB_HEADER.read_text()
        src = self.WEB_CONFIG.read_text()
        for field in ["battery_mv", "battery_pct", "battery_cell_count", "battery_warn_pct", "battery_cutoff_pct", "battery_warn_mv", "battery_cutoff_mv"]:
            assert field in header, f"web_status_t missing {field}"
            assert f"\\\"{field}\\\"" in src, f"/api/status JSON missing {field}"
        assert "PowerFunctions::getLastBatteryMillivolts" in src
        assert "battery_config_get_cell_count" in src
        assert "battery_config_get_warn_percent" in src
        assert "battery_config_get_cutoff_percent" in src

    def test_battery_config_endpoint_exists_and_validates_ranges(self):
        src = self.WEB_CONFIG.read_text()
        assert src.find('"/api/config/battery"') < src.find('"/api/config"'), (
            "ESPAsyncWebServer matches /api/config before /api/config/battery; "
            "register the more-specific battery route first."
        )
        assert "HTTP_GET" in src and "battery_config_to_json" in src
        assert "HTTP_POST" in src and "battery_config_apply_json_patch" in src
        assert "cell_count" in src and "warn_percent" in src and "cutoff_percent" in src
        assert "invalid battery config" in src

    def test_battery_cell_count_supports_1_through_8(self):
        header = self.BATTERY_H.read_text()
        src = self.BATTERY_C.read_text()
        html = self.MOCKUP.read_text()
        # Header bounds (server-side validation).
        assert "BC_CELL_COUNT_MIN 1" in header or "BC_CELL_COUNT_MIN           1" in header, header
        assert "BC_CELL_COUNT_MAX 8" in header or "BC_CELL_COUNT_MAX           8" in header, header
        # Runtime guard rejects 0 and 9.
        assert "valid_cells" in src
        assert "BC_CELL_COUNT_MIN" in src and "BC_CELL_COUNT_MAX" in src
        # Web UI input + save handler both allow 1..8.
        assert 'id="battery-cell-count" type="number" min="1" max="8"' in html, (
            "cell-count input must allow 1..8 cells"
        )
        save_block = html.split("// ---- Battery config wiring", 1)[1]
        assert "cells < 1 || cells > 8" in save_block, save_block

    def test_apply_status_updates_battery_dom_rows_each_poll(self):
        """Voltage / percent / state / cutoff rows must reflect /api/status."""
        html = self.MOCKUP.read_text()
        for needle in (
            "battery-voltage",
            "battery-percent",
            "battery-state",
            "battery-warn-mv",
            "battery-cutoff-mv",
            "setInterval(() => { liveTick(); refreshStatus(); }, 1000);",
            "state.battery",
        ):
            assert needle in html, f"missing {needle}"
        # applyStatus must read battery_mv from /api/status, not a stale state only.
        apply_block = html.split("function applyStatus", 1)[1].split("// ---- ", 1)[0]
        assert "s.battery_mv" in apply_block, "applyStatus must read s.battery_mv"
        assert "battery-voltage" in apply_block and "battery-percent" in apply_block

    def test_battery_state_field_renders_human_label_not_raw_enum(self):
        """Users should see 'Good' / 'Warn' / 'Low', not raw 1/2/3 codes."""
        html = self.MOCKUP.read_text()
        apply_block = html.split("function applyStatus", 1)[1].split("// ---- ", 1)[0]
        # We need a mapping; raw String(battState) is the bug.
        assert "String(battState)" not in apply_block, (
            "applyStatus still prints the raw battery_state enum code; "
            "it should map 1=Good, 2=Warn, 3=Low to readable text."
        )
        for label in ("Good", "Warn", "Low"):
            assert label in apply_block, f"applyStatus missing {label} label"

    def test_battery_inputs_not_overwritten_during_status_polling(self):
        """Polling must NOT clobber a user's in-progress edit of cell count / cutoff."""
        html = self.MOCKUP.read_text()
        apply_block = html.split("function applyStatus", 1)[1].split("// ---- ", 1)[0]
        # Save the user-supplied values so refreshStatus after a successful save
        # (or a half-typed edit) doesn't snap the inputs back to server defaults.
        assert "battery-cell-count" in apply_block
        assert "battery-warn-percent" in apply_block
        assert "battery-cutoff-percent" in apply_block
        # The guard must be stronger than just "input is focused": it must skip
        # the overwrite while there are unsaved user edits.
        for needle in (
            "state.battery.cell_count_dirty",
            "state.battery.warn_percent_dirty",
            "state.battery.cutoff_percent_dirty",
        ):
            assert needle in apply_block, (
                f"applyStatus must respect {needle} so polling doesn't "
                f"overwrite the user's pending edit."
            )
        # Critical regression: applyStatus must NOT recreate state.battery
        # from scratch, because that wipes the dirty flags set by the
        # 'input' event listener.
        assert "state.battery = {" not in apply_block, (
            "applyStatus must preserve state.battery.*_dirty flags "
            "instead of replacing the object."
        )
        assert "state.battery.cell_count_dirty = state.battery.cell_count_dirty" in apply_block or (
            # Equivalent: re-assign individual keys rather than the whole object.
            "battery_cutoff_pct" in apply_block
            and "cell_count" in apply_block
        ), "applyStatus must mutate state.battery fields without losing dirty flags"

    def test_battery_settings_help_text_matches_supported_ranges(self):
        html = self.MOCKUP.read_text()
        assert "1–8 cells" in html, "help text must reflect 1..8 cell range"

    def test_settings_ui_can_view_and_set_battery_config(self):
        html = self.MOCKUP.read_text()
        for needle in [
            'Battery Settings',
            'id="btn-battery-settings-link"',
            'id="battery-voltage"',
            'id="battery-percent"',
            'id="battery-state"',
            'id="battery-cell-count"',
            'id="battery-warn-percent"',
            'id="battery-cutoff-percent"',
            'id="battery-warn-mv"',
            'id="battery-cutoff-mv"',
            'id="btn-battery-save"',
            '/api/config/battery',
            'battery_cell_count',
            'battery_warn_pct',
            'battery_cutoff_pct',
            'warn_percent',
        ]:
            assert needle in html

    def test_power_behavior_cards_are_collapsible_enabled_only_and_highlight_overrides(self):
        html = self.MOCKUP.read_text()
        for needle in [
            "const POWER_DEFAULTS = { GOOD: 'allow', WARN: 'reduce', LOW: 'disable' }",
            "function powerIsEnabled",
            "cfg.purpose === 'disabled'",
            "el('details', { class: `power-card",
            "select.power-select.override",
            "Only enabled output channels appear here",
            "GOOD = Allow, WARN = Reduce to 50%, LOW = Disable",
        ]:
            assert needle in html
        assert "Inherit →" not in html
        assert "Default for this output" not in html


def test_obsolete_weapon_patch_is_rejected():
    src = OC_SRC.read_text()
    assert 'strcmp(key, "Weapon") == 0' in src
    assert 'return ESP_ERR_INVALID_ARG' in src


def test_m1_m2_are_drive_only_in_ui():
    html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text()
    assert "M1 and M2 are the high-current brushed motor outputs" in html
    assert "Drive Method is None" in html
    assert "function renderManualMotorControls" in html
