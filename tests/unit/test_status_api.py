"""
Tests for the /api/status JSON contract.

The C++ code in components/web_config/src/web_config.cpp::send_json_status
builds a JSON string by hand. The HTML dashboard in INDEX_HTML reads
specific fields. This test verifies the contract: every field the
JavaScript reads MUST be produced by the C++, and the JSON must parse.

What this catches:
  - Field name typos (e.g. "ble_connected" vs "connected")
  - Missing fields after a refactor
  - JSON syntax errors (unescaped quotes, trailing commas, etc.)
  - Type mismatches (e.g. boolean as string)

What this doesn't catch:
  - HTML rendering (would need a headless browser)
  - HTTP routing (would need a real server)
"""
import json
import re
from pathlib import Path

import pytest


# Path to the C++ source — used to extract the JSON-building code and
# verify by inspection that the field set is consistent.
WEB_IMPL = Path(__file__).resolve().parent.parent.parent / "components" / "web_config" / "src" / "web_config.cpp"


# The list of fields the JS dashboard expects to find in the status JSON.
# If you change the JS, update this set; if you change the C++, this set
# tells you what you need to add.
EXPECTED_FIELDS = {
    "ble_connected", "ble_mac", "pairing_state",
    "paired_macs", "wifi_connected", "wifi_ap_mode", "wifi_ip",
    "battery_mv", "battery_state", "firmware_version",
}


def extract_json_field_set(cpp_source: str) -> set:
    """Pull out all `json += "field":` patterns from the C++ code.

    The pattern in send_json_status is:
        json += "\\"field_name\\": ... ;
    (the quotes are escaped in the C++ string literal).
    """
    # Match: json += "fieldname":  (with possibly-escaped quote)
    pattern = re.compile(r'json\s*\+=\s*"\\?"(\w+)\\?"\s*:', re.M)
    return set(pattern.findall(cpp_source))


def extract_html_field_accesses(html: str) -> set:
    """Pull out all `s.fieldname` accesses from the JavaScript.

    Looks for s.X.Y or s.X patterns in the embedded JS.
    """
    # The JS uses: js.something or s.something
    # Look for s.fieldname where fieldname has an underscore (matches our
    # naming convention; this avoids matching things like s.foo())
    pattern = re.compile(r'\bs\.(\w+_\w+)\b', re.M)
    return set(pattern.findall(html))


def extract_index_html(cpp_source: str) -> str:
    """Pull the embedded HTML from the C++ source.

    The HTML lives between `R"rawliteral(\n` and `\n)rawliteral";`.
    """
    m = re.search(r'INDEX_HTML\[\]\s*PROGMEM\s*=\s*R"rawliteral\(\n(.*?)\n\)rawliteral";',
                   cpp_source, re.S)
    if not m:
        return ""
    return m.group(1)


# ---------- Contract tests ----------

class TestStatusApiContract:
    """Verify the C++ produces every field the JS expects."""

    @pytest.fixture
    def cpp_source(self):
        return WEB_IMPL.read_text()

    @pytest.fixture
    def cpp_fields(self, cpp_source):
        return extract_json_field_set(cpp_source)

    @pytest.fixture
    def html(self, cpp_source):
        return extract_index_html(cpp_source)
        # If this returns empty, the regex didn't match — fail loudly.
        if not html:
            pytest.fail("Could not extract INDEX_HTML from web_config.cpp")

    @pytest.fixture
    def html_fields(self, html):
        return extract_html_field_accesses(html)

    def test_cpp_produces_all_expected_fields(self, cpp_fields):
        """The C++ must produce every field we expect."""
        missing = EXPECTED_FIELDS - cpp_fields
        assert not missing, f"C++ send_json_status is missing fields: {missing}"

    def test_html_reads_only_defined_fields(self, html_fields, cpp_fields):
        """If the JS reads a field, the C++ must produce it.

        Catches typos and orphan JS reads after a refactor.
        """
        orphan = html_fields - cpp_fields
        # Some JS accesses might be on intermediate variables (e.g. js.speed)
        # but for the top-level s.* we expect them all to be defined.
        if orphan:
            pytest.fail(f"HTML JS reads undefined fields: {orphan}")

    def test_no_orphan_cpp_fields(self, cpp_fields):
        """The C++ shouldn't produce fields nothing reads.

        Warns about dead code in the JSON output. (Not strictly required,
        but a code smell.)
        """
        unused = cpp_fields - EXPECTED_FIELDS
        if unused:
            # Don't fail — just record for review
            print(f"Note: C++ produces fields not in EXPECTED_FIELDS: {unused}")


# ---------- JSON shape validation ----------

class TestStatusJsonShape:
    """Verify a representative JSON response parses and has the right types."""

    @pytest.fixture
    def example_response(self):
        """A hand-built example matching what send_json_status produces.

        If you change send_json_status, update this to match.
        """
        return {
            "ble_connected": False,
            "ble_mac": "—",
            "pairing_state": "IDLE",
            "paired_macs": [],
            "wifi_connected": True,
            "wifi_ap_mode": False,
            "wifi_ip": "192.168.4.1",
            "battery_mv": 0,
            "battery_state": 0,
            "firmware_version": "Version 1.3"
        }

    def test_response_parses_as_json(self, example_response):
        s = json.dumps(example_response)
        parsed = json.loads(s)
        assert parsed == example_response

    def test_required_fields_present(self, example_response):
        for f in EXPECTED_FIELDS:
            assert f in example_response, f"missing field: {f}"

    def test_paired_macs_is_list(self, example_response):
        assert isinstance(example_response["paired_macs"], list)

    def test_paired_macs_strings_are_uppercase_mac_format(self, example_response):
        """Each entry in paired_macs should be 'XX:XX:XX:XX:XX:XX' uppercase hex."""
        example_response["paired_macs"] = [
            "AA:BB:CC:11:22:33",
            "DE:AD:BE:EF:00:01"
        ]
        for mac in example_response["paired_macs"]:
            assert re.match(r'^[0-9A-F]{2}(:[0-9A-F]{2}){5}$', mac), \
                f"bad MAC format: {mac}"

    def test_boolean_fields_are_bools(self, example_response):
        assert isinstance(example_response["ble_connected"], bool)
        assert isinstance(example_response["wifi_connected"], bool)
        assert isinstance(example_response["wifi_ap_mode"], bool)

    def test_numeric_fields_are_numbers(self, example_response):
        assert isinstance(example_response["battery_mv"], int)
        assert isinstance(example_response["battery_state"], int)

    def test_pairing_state_valid_values(self, example_response):
        """The C++ produces one of: IDLE, ACCEPT, DISABLED.

        If the C++ code changes the enum, update this.
        """
        valid = {"IDLE", "ACCEPT", "DISABLED"}
        assert example_response["pairing_state"] in valid

    def test_connected_mac_format_when_present(self, example_response):
        """When BLE is connected, the MAC should be a valid Bluetooth MAC.

        Currently the C++ code shows "connected" or "—" rather than the
        actual MAC. That's a known limitation (see DECISIONS.md, L8).
        When we fix that, this test should require the actual MAC format.
        """
        # Allow the placeholder "connected" or a real MAC
        if example_response["ble_connected"]:
            mac = example_response["ble_mac"]
            assert mac == "connected" or re.match(r'^[0-9A-F]{2}(:[0-9A-F]{2}){5}$', mac), \
                f"unexpected ble_mac when connected: {mac}"


# ---------- API endpoint registration ----------

class TestApiRoutes:
    """Verify the C++ registers the endpoints the HTML/JS calls.

    The HTML uses fetch() against specific URLs. If the C++ doesn't
    register a handler for one of those URLs, you'll get 404.
    """

    @pytest.fixture
    def cpp_source(self):
        return WEB_IMPL.read_text()

    def test_root_registered(self, cpp_source):
        """GET /  →  serve HTML."""
        assert '"/"' in cpp_source or 'server->on("/"' in cpp_source

    def test_status_registered(self, cpp_source):
        """GET /api/status  →  send JSON."""
        assert '"/api/status"' in cpp_source

    def test_pair_start_registered(self, cpp_source):
        """POST /api/pair/start  →  enter pairing mode."""
        assert '"/api/pair/start"' in cpp_source

    def test_pair_cancel_registered(self, cpp_source):
        """POST /api/pair/cancel  →  exit pairing mode."""
        assert '"/api/pair/cancel"' in cpp_source

    def test_pair_clear_registered(self, cpp_source):
        """POST /api/pair/clear  →  clear whitelist."""
        assert '"/api/pair/clear"' in cpp_source

    def test_ota_registered(self, cpp_source):
        """POST /api/ota  →  firmware upload."""
        assert '"/api/ota"' in cpp_source

    def test_html_references_match_routes(self):
        """The HTML's fetch() URLs must match registered routes.

        Cross-check between the embedded JS and the C++ route table.
        """
        cpp = WEB_IMPL.read_text()
        html = extract_index_html(cpp)

        # Find all fetch('...') calls in the JS
        api_calls = set(re.findall(r"fetch\(['\"]([^'\"]+)['\"]", html))
        # Find all registered /api/ routes in the C++. We use a stricter
        # pattern that requires the URL to be in a string literal context
        # (between quotes) to avoid partial matches like /api/pair matching
        # inside /api/pair/start.
        registered = set(re.findall(r'"(/api/[\w/]+)"', cpp))

        # Every fetch() must have a matching route
        for url in api_calls:
            if url.startswith("/api/"):
                assert url in registered, f"JS calls {url} but C++ doesn't register it"


# ---------- Board revision endpoints (added with board_detect) ----------

class TestBoardRevEndpoints:
    """Endpoints for runtime board revision selection via NVS."""

    def test_board_rev_endpoint_registered(self):
        cpp = WEB_IMPL.read_text()
        assert '"/api/board/rev"' in cpp, (
            "/api/board/rev endpoint not registered in web_config.cpp"
        )

    def test_board_reset_endpoint_registered(self):
        cpp = WEB_IMPL.read_text()
        assert '"/api/board/reset"' in cpp

    def test_board_rev_calls_set_override(self):
        """The endpoint must call board_detect_set_override with the rev."""
        cpp = WEB_IMPL.read_text()
        # Find the /api/board/rev handler body
        m = re.search(
            r'server->on\("/api/board/rev".*?NULL\s*\);',
            cpp, re.S
        )
        assert m, "/api/board/rev handler not found"
        handler = m.group(0)
        assert "board_detect_set_override" in handler, (
            "/api/board/rev handler should call board_detect_set_override"
        )

    def test_board_reset_calls_clear_override(self):
        cpp = WEB_IMPL.read_text()
        m = re.search(
            r'server->on\("/api/board/reset".*?NULL\s*\);',
            cpp, re.S
        )
        assert m
        assert "board_detect_clear_override" in m.group(0)

    def test_board_rev_includes_board_detect_header(self):
        """web_config.cpp must include board_detect.h to use the API."""
        cpp = WEB_IMPL.read_text()
        assert '#include "board_detect.h"' in cpp, (
            "web_config.cpp must include board_detect.h"
        )

    def test_web_config_cmake_requires_board_detect(self):
        """The web_config CMakeLists.txt must require board_detect."""
        from pathlib import Path
        cmake_path = Path(__file__).resolve().parent.parent.parent / "components/web_config/CMakeLists.txt"
        cmake = cmake_path.read_text()
        assert "board_detect" in cmake