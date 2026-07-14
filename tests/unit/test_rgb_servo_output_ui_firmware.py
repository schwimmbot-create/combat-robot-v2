from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"
OC_H = PROJECT_ROOT / "components/output_config/include/output_config.h"
OC_C = PROJECT_ROOT / "components/output_config/src/output_config.c"
TM_CPP = PROJECT_ROOT / "components/myrobot/src/TaskManager.cpp"


def test_rgb_lighting_is_firmware_backed_output_role():
    h = OC_H.read_text()
    c = OC_C.read_text()
    for token in (
        "OC_PURPOSE_RGB_LIGHTING",
        "OC_PROTO_RGB",
        "OC_PROTO_RGBW",
        "OC_SEM_RGB_LIGHTING",
        "oc_rgb_pattern_t",
        "OC_RGB_PATTERN_SOLID",
        "OC_RGB_PATTERN_RAINBOW",
        "rgb_pattern",
        "rgb_r",
        "rgb_g",
        "rgb_b",
        "rgb_w",
        "rgb_brightness_pct",
        "rgb_led_count",
    ):
        assert token in h + c
    for token in (
        '"rgb_lighting"',
        '"rgb"',
        '"rgbw"',
        '"solid"',
        '"breathe"',
        '"battery"',
        "rgb_pattern_from_str",
        "purpose_protocol_is_valid",
    ):
        assert token in c


def test_rgb_lighting_runtime_keeps_s1_s2_out_of_servo_pwm_path():
    text = TM_CPP.read_text()
    assert "OC_PURPOSE_RGB_LIGHTING" in text
    assert "OC_PROTO_RGB" in text and "OC_PROTO_RGBW" in text
    assert "digitalWrite(pin, LOW)" in text
    rgb_branch = text[text.index("OC_PURPOSE_RGB_LIGHTING"):text.index("if (cfg->purpose == OC_PURPOSE_SERVO")]
    assert "updatePulseOutput" not in rgb_branch


def test_html_exposes_rgb_rgbw_servo_output_controls():
    html = HTML.read_text()
    for token in (
        "['rgb_lighting', 'RGB / RGBW lighting']",
        "['rgb', 'RGB addressable LED']",
        "['rgbw', 'RGBW addressable LED']",
        "OUTPUT_RGB_PATTERNS",
        "Pattern color wheel",
        "LED count",
        "Number of addressable LEDs in this S1/S2 string (1–300).",
        "rgbChannelInput",
        "data-rgb-channel",
        "Red (0–255)",
        "Green (0–255)",
        "Blue (0–255)",
        "input', { type: 'color'",
        "White channel (0–255)",
        "renderRgbLightingControls",
        "cfg.purpose === 'rgb_lighting'",
        "rgb_pattern: cfg.rgb?.pattern",
        "rgb_brightness_pct: cfg.rgb?.brightness_pct",
        "rgb_led_count: cfg.rgb?.led_count",
    ):
        assert token in html


def test_rgb_patterns_hide_color_wheel_for_generated_status_patterns():
    html = HTML.read_text()
    assert "OUTPUT_RGB_PATTERNS_NEED_COLOR" in html
    assert "new Set(['solid', 'blink', 'breathe', 'chase'])" in html
    assert "This pattern uses generated/status colors, so no color wheel is needed." in html


def test_rgb_lighting_returns_before_irrelevant_servo_source_controls():
    html = HTML.read_text()
    assert "const isRgbLighting = cfg.purpose === 'rgb_lighting';" in html
    start = html.index("if (isRgbLighting) {")
    end = html.index("const grid = el('div', { class: 'grid-2' });", start)
    branch = html[start:end]
    assert "renderRgbLightingControls" in branch
    assert "return card" in branch
    later = html[end:html.index("card.appendChild(grid2);", end)]
    for label in (
        "Direction",
        "Optional reverse-only input",
        "Drive input (center = stop)",
        "Deadzone (%)",
    ):
        assert label in later
