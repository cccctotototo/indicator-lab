from quant_labeler.ui import SIGNAL_STATUS_COLORS, signal_marker_color


def test_signal_marker_colors_follow_labeling_semantics():
    assert signal_marker_color(None, 1, None) == SIGNAL_STATUS_COLORS["unlabeled"]
    assert signal_marker_color("win", 2, None) == SIGNAL_STATUS_COLORS["win"]
    assert signal_marker_color("loss", 3, None) == SIGNAL_STATUS_COLORS["loss"]


def test_selected_signal_is_always_blue():
    assert signal_marker_color(None, 7, 7) == SIGNAL_STATUS_COLORS["selected"]
    assert signal_marker_color("win", 7, 7) == SIGNAL_STATUS_COLORS["selected"]
    assert signal_marker_color("loss", 7, 7) == SIGNAL_STATUS_COLORS["selected"]
