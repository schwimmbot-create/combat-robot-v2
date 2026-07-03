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
  * Defaults match the v1.3 combat_robot behavior:
        M1/M2: LY primary, normal direction, bi servo_mode (motor)
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

    def test_defaults_match_v1_3(self, src_text):
        # Defaults: M1/M2 -> LY primary, Weapon -> RT, S1/S2 -> NONE,
        # all "normal" direction, deadzone 10 (Weapon: 5), uni for servos.
        m = re.search(r"kDefaults\[OC_OUT__COUNT\]\s*=\s*\{([\s\S]+?)\};", src_text)
        assert m, "kDefaults not found"
        defaults_blob = m.group(1)

        # Spot-check each.
        assert re.search(r"OC_OUT_M1\][^}]*OC_SRC_LY", defaults_blob)
        assert re.search(r"OC_OUT_M2\][^}]*OC_SRC_LY", defaults_blob)
        assert re.search(r"OC_OUT_WEAPON\][^}]*OC_SRC_RT", defaults_blob)
        assert re.search(r"OC_OUT_S1\][^}]*OC_DIR_NORMAL", defaults_blob)
        assert re.search(r"OC_OUT_S2\][^}]*OC_DIR_NORMAL", defaults_blob)

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
        # ESP32-C3 WiFi and BLE share the 2.4GHz radio. The HTML page is
        # the pairing trigger, so boot must keep BLE scanning idle until
        # the user presses Enter Pairing Mode; otherwise the SoftAP can be
        # unreachable before the page loads.
        assert "s_state.pairing_state = PAIRING_STATE_IDLE" in ble_src_text
        assert "scan deferred" in ble_src_text
        start_block = ble_src_text.split("esp_err_t ble_gamepad_start(void)", 1)[1]
        start_block = start_block.split("void ble_gamepad_deinit", 1)[0]
        assert "start_scan();" not in start_block
        assert "ble_gamepad_poll" in ble_src_text

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
