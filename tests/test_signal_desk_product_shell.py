from scripts.ui.signal_desk.product_shell import (
    CONTROL_CENTER_TABS,
    USER_WORKSPACE_TABS,
    normalize_product_mode,
)


def test_user_workspace_tabs_hide_operator_surfaces():
    assert USER_WORKSPACE_TABS == ["Rooms", "Signals", "Saved", "Briefs"]
    assert "Task Management" not in USER_WORKSPACE_TABS
    assert "Channels" not in USER_WORKSPACE_TABS
    assert "Logs" not in USER_WORKSPACE_TABS


def test_control_center_tabs_keep_operator_surfaces():
    assert "Task Management" in CONTROL_CENTER_TABS
    assert "Channels" in CONTROL_CENTER_TABS
    assert "Validation" in CONTROL_CENTER_TABS
    assert "Logs" in CONTROL_CENTER_TABS


def test_normalize_product_mode_defaults_to_signal_desk():
    assert normalize_product_mode("") == "Signal Desk"
    assert normalize_product_mode("Control Center") == "Control Center"
