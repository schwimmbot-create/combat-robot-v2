from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"


def test_live_output_state_uses_vertical_rows_with_channel_names():
    html = HTML.read_text()
    assert ".status-strip { display: grid; grid-template-columns: 1fr;" in html
    assert ".status-strip .status-chip" in html
    assert "grid-template-columns: auto minmax(0, 1fr) auto" in html
    for token in (
        "channel-id",
        "channel-name",
        "class=\"state\"",
        "Motor 1",
        "Motor 2",
        "Servo 1",
        "Servo 2",
    ):
        assert token in html


def test_live_output_state_runtime_uses_config_display_name_next_to_id():
    html = HTML.read_text()
    start = html.index("function renderLiveOutputStrip()")
    end = html.index("function renderMockRobot", start)
    block = html[start:end]
    assert "const cfg = state.outputs[id] || {};" in block
    assert "const name = cfg.display_name || outputDisplayName(id);" in block
    assert "el('span', { class: 'channel-id' }, id)" in block
    assert "el('span', { class: 'channel-name' }, name)" in block
    assert "el('span', { class: 'state' }, st.text)" in block
