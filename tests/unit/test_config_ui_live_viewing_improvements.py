from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"
GEN = PROJECT_ROOT / "components/web_config/src/web_index_gen.h"


def html_text() -> str:
    return HTML.read_text()


def test_robot_html_has_live_output_state_and_drive_viewing_cards():
    html = html_text()
    for token in (
        "Live Output State",
        "live-output-strip",
        "data-live-output",
        "Live Drive Output",
        "mock-steer-label",
        "function renderLiveOutputStrip",
        "function outputStatus",
    ):
        assert token in html


def test_output_cards_have_runtime_state_chips_and_consistent_names():
    html = html_text()
    for token in (
        "data-output-state-slot",
        "function outputStateChip",
        "`${id} — ${name}`",
        "String(raw).replace",
    ):
        assert token in html


def test_pulse_preview_validation_and_protocol_labels():
    html = html_text()
    for token in (
        "function pulseCalibrationIssue",
        "Pulse order must be min < center < max.",
        "function renderPulsePreview",
        "min ${p.min_us}µs",
        "OneShot42",
        "MultiShot",
    ):
        assert token in html


def test_failsafe_power_battery_pairing_and_danger_zone_ui():
    html = html_text()
    for token in (
        "function renderFailsafeSummary",
        "disconnect = ${disconnect}; LOW battery = ${low}",
        "power-summary-badges",
        "GOOD</span><span>Allow",
        "battery-gauge",
        "battery-gauge-fill",
        "Paired Controllers",
        "Danger Zone",
    ):
        assert token in html


def test_board_io_loading_states_shape_indicators_and_planning_banners():
    html = html_text()
    for token in (
        "settings-board-io",
        "function renderSettingsBoardIo",
        "Loading…",
        "● GOOD",
        "▲ WARN",
        "✕ LOW",
        "Header H1 — config/planning only",
        "RGB/RGBW — planning only",
        "Firmware-backed physical mode button actions",
    ):
        assert token in html


def test_robot_html_does_not_reference_bench_python_or_simulator_reports():
    html = html_text().lower()
    forbidden = (
        "bench_e2e",
        "drive-sim",
        "drive_sim",
        "simulator report",
        "python script",
        "artifacts/drive-sim",
    )
    for token in forbidden:
        assert token not in html


def test_generated_header_contains_live_viewing_ui_after_regeneration():
    gen = GEN.read_text()
    for token in (
        "Live Output State",
        "Live Drive Output",
        "Danger Zone",
        "Pulse order must be min < center < max.",
    ):
        assert token in gen
