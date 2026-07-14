from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"
TM_CPP = PROJECT_ROOT / "components/myrobot/src/TaskManager.cpp"


def test_servo_secondary_input_hidden_because_firmware_does_not_use_it():
    html = HTML.read_text()
    runtime = TM_CPP.read_text()
    servo_block = runtime[runtime.index("if (cfg->purpose == OC_PURPOSE_SERVO)"):runtime.index("uint16_t forward", runtime.index("if (cfg->purpose == OC_PURPOSE_SERVO)"))]
    assert "cfg->secondary" not in servo_block
    assert "Servo uses only the primary input" in html
    assert "Secondary/reverse input is only shown for ESC / motor controller outputs" in html
    assert "el('label', { class: 'field' }, 'Secondary input')" not in html


def test_non_esc_output_types_return_before_esc_style_source_grid():
    html = HTML.read_text()
    grid_start = html.index("const grid = el('div', { class: 'grid-2' });")
    pre_grid = html[:grid_start]
    for purpose in ("disabled", "digital_input", "pwm_accessory"):
        marker = f"if (cfg.purpose === '{purpose}')"
        assert marker in pre_grid
        branch = pre_grid[pre_grid.index(marker):]
        assert "return card" in branch
    for marker in (
        "if (isRgbLighting)",
        "if (cfg.purpose === 'disabled')",
        "if (cfg.purpose === 'digital_input')",
        "if (isDigitalOutput)",
        "if (cfg.purpose === 'pwm_accessory')",
    ):
        branch = pre_grid[pre_grid.index(marker):]
        assert "return card" in branch


def test_esc_keeps_reverse_input_because_runtime_uses_secondary():
    html = HTML.read_text()
    runtime = TM_CPP.read_text()
    esc_block = runtime[runtime.index("uint16_t forward"):runtime.index("pulse.writeEsc") + len("pulse.writeEsc(forward, reverse, semantics);")]
    assert "cfg->secondary" in esc_block
    assert "Optional reverse-only input" in html
    assert "Drive input (center = stop)" in html
