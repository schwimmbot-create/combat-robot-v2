from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"


def html() -> str:
    return HTML.read_text()


def test_backup_wrapper_is_versioned_and_credential_free():
    text = html()
    assert "combat-robot-controller-v2.config.v1" in text
    assert "outputs_patch: editableOutputPatch(state.outputs)" in text
    assert "battery:" in text
    assert "max_paired: state.max_paired" in text
    backup = text[text.index("function configBackupPayload"):text.index("function downloadTextFile")]
    for forbidden in ("password", "wifi_password", "api_token", "private_key"):
        assert forbidden not in backup.lower()


def test_import_requires_schema_preview_and_confirmation():
    text = html()
    for token in (
        "incompatible schema",
        "config-import-preview",
        "configImportSummary",
        "preview ready",
        "Apply this configuration?",
        "previewed — not applied",
        "obsolete Weapon output is not supported",
    ):
        assert token in text
    assert text.index("if (!confirm(`Apply this configuration?") < text.index("await applyUploadedConfig(data)")


def test_generic_board_presets_cover_named_use_cases_and_default_safe_stop():
    text = html()
    block = text[text.index("const GENERIC_BOARD_PRESETS"):text.index("function disabledPresetOutput")]
    for preset in (
        "tank_drive", "arcade_drive", "servo_steer", "safety_esc",
        "solenoid_accessory", "led_strip", "bench_safe",
    ):
        assert preset in block
    assert "disconnect_failsafe:'safe_stop'" in text
    assert "weapon_safety:true" in text
    assert "motor_mode:'momentary', primary:'A'" in text
    assert "purpose:'rgb_lighting'" in text
    assert "Load Preset into Form" in text
    assert "review and Save to persist" in text


def test_presets_do_not_auto_post_or_enable_hold_last():
    text = html()
    handler_start = text.index("document.getElementById('btn-config-preset').addEventListener")
    handler_end = text.index("document.getElementById('btn-config-upload')", handler_start)
    handler = text[handler_start:handler_end]
    assert "apiPost" not in handler
    assert "hold_last" not in handler
