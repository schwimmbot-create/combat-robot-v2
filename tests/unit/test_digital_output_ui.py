from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"
GEN = PROJECT_ROOT / "components/web_config/src/web_index_gen.h"


def test_digital_output_ui_has_friendly_presets_and_custom_percentage():
    html = HTML.read_text()
    for token in (
        "TRIGGER_THRESHOLD_PRESETS",
        "Light press (~25%)",
        "Half press (~50%)",
        "Firm press (~75%)",
        "STICK_THRESHOLD_PRESETS",
        "Above center (~40%)",
        "Strong above center (~75%)",
        "Below center (~40%)",
        "Strong below center (~75%)",
        "Custom…",
        "Custom threshold (%)",
        "digital_custom_pct",
    ):
        assert token in html


def test_digital_output_ui_saves_runtime_fields():
    html = HTML.read_text()
    for token in (
        "active_high: !!cfg.active_high",
        "default_state: !!cfg.default_state",
        "digital_mode: cfg.digital_mode",
        "digital_preset: cfg.digital_preset",
        "digital_on_threshold: cfg.digital_on_threshold",
        "digital_off_threshold: cfg.digital_off_threshold",
        "digital_custom_pct: cfg.digital_custom_pct",
        "applyDigitalPreset(cfg)",
    ):
        assert token in html


def test_embedded_web_header_regenerated_with_digital_controls():
    gen = GEN.read_text()
    assert "Generated" in gen
    assert "Light press (~25%)" in gen
    assert "Custom threshold (%)" in gen
    assert "Active low / inverted: ON = LOW" in gen


def test_configuration_backup_ui_download_and_upload_controls():
    html = HTML.read_text()
    for token in (
        "Configuration Backup",
        "Download Configuration",
        "Upload configuration JSON",
        "Upload &amp; Apply Configuration",
        "config-upload-file",
        "btn-config-download",
        "btn-config-upload",
        "config-backup-status",
    ):
        assert token in html


def test_configuration_backup_json_contract_and_apply_paths():
    html = HTML.read_text()
    for token in (
        "combat-robot-controller-v2.config.v1",
        "outputs_patch: editableOutputPatch(state.outputs)",
        "battery: {",
        "max_paired: state.max_paired",
        "patchFromUploadedConfig",
        "apiPostJSON('/api/config', patch)",
        "apiPostJSON('/api/config/battery'",
        "apiPostJSON('/api/config/max_paired'",
        "downloadTextFile(configBackupFilename()",
    ):
        assert token in html
