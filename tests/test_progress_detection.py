import breitbandmessung_automate_stateful as bbm


class ElementInfo:
    def __init__(self, control_type):
        self.control_type = control_type


class Control:
    def __init__(self, *, text: str, control_type: str):
        self._text = text
        self.element_info = ElementInfo(control_type)

    def window_text(self):
        return self._text


class Dialog:
    def __init__(self, controls):
        self._controls = list(controls)

    def descendants(self, control_type=None):
        if control_type is None:
            return list(self._controls)
        return [c for c in self._controls if c.element_info.control_type == control_type]


def test_detect_progress_from_ui_finds_progress_in_non_text_controls():
    # Some Chromium-hosted UIs expose the progress counters on non-Text elements.
    win = Dialog(
        [
            Control(text="Fortschritt: 9/10", control_type="Pane"),
            Control(text="Gesamt: 10/30", control_type="Pane"),
        ]
    )
    assert bbm.detect_progress_from_ui(win, day_goal=10, campaign_goal=30) == (9, 10)

