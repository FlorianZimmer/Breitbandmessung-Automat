from datetime import datetime, timedelta

import breitbandmessung_automate_stateful as bbm


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class ElementInfo:
    def __init__(self, control_type):
        self.control_type = control_type


class Control:
    def __init__(self, *, name, control_type, rect=None, toggle_state=None, visible=True):
        self._name = name
        self.element_info = ElementInfo(control_type)
        self._rect = rect
        self._toggle_state = toggle_state
        self._visible = visible
        self.clicks = 0
        self._enabled = True

    def window_text(self):
        return self._name

    def rectangle(self):
        if self._rect is None:
            raise RuntimeError("no rect")
        return self._rect

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def get_toggle_state(self):
        if self._toggle_state is None:
            raise RuntimeError("no toggle")
        return self._toggle_state

    def click_input(self):
        self.clicks += 1
        if self._toggle_state is not None:
            self._toggle_state = 1

    def wait(self, *_args, **_kwargs):
        return True

    def exists(self, *_args, **_kwargs):
        return True


class Dialog:
    def __init__(self, controls):
        self._controls = list(controls)

    def descendants(self, control_type=None):
        if control_type is None:
            return list(self._controls)
        return [c for c in self._controls if c.element_info.control_type == control_type]


def test_norm_text_and_token_set():
    s = "  Direkte LAN-Verbindung geprüft?  "
    assert bbm._norm_text(s) == "direkte lan verbindung geprueft"
    assert bbm._token_set(s) == {"direkte", "lan", "verbindung", "geprueft"}


def test_try_get_checked_state():
    c = Control(name="x", control_type="CheckBox", toggle_state=1)
    assert bbm._try_get_checked_state(c) is True
    c2 = Control(name="x", control_type="CheckBox", toggle_state=0)
    assert bbm._try_get_checked_state(c2) is False


def test_try_click_named_toggle_clicks_best_match(monkeypatch):
    monkeypatch.setattr(bbm.time, "sleep", lambda *_args, **_kwargs: None)
    target = "VPN-Verbindungen ausgeschaltet?"
    bad = Control(name="Energiesparmodi deaktiviert?", control_type="Button", toggle_state=0)
    good = Control(name="VPN-Verbindungen ausgeschaltet", control_type="Button", toggle_state=0)
    dlg = Dialog([bad, good])
    assert bbm._try_click_named_toggle(dlg, target) is True
    assert good.clicks == 1
    assert bad.clicks == 0


def test_try_click_named_toggle_does_not_click_if_already_checked(monkeypatch):
    monkeypatch.setattr(bbm.time, "sleep", lambda *_args, **_kwargs: None)
    c = Control(name="VPN-Verbindungen ausgeschaltet", control_type="Button", toggle_state=1)
    dlg = Dialog([c])
    assert bbm._try_click_named_toggle(dlg, "VPN-Verbindungen ausgeschaltet?") is True
    assert c.clicks == 0


def test_check_all_disclaimer_checkboxes_clicks_only_unchecked(monkeypatch):
    monkeypatch.setattr(bbm.time, "sleep", lambda *_args, **_kwargs: None)
    cb1 = Control(name="", control_type="CheckBox", rect=Rect(10, 10, 20, 20), toggle_state=0)
    cb2 = Control(name="", control_type="CheckBox", rect=Rect(10, 40, 20, 50), toggle_state=1)
    cb3 = Control(name="", control_type="CheckBox", rect=Rect(10, 70, 20, 80), toggle_state=0, visible=False)
    dlg = Dialog([cb1, cb2, cb3])
    clicked, total = bbm._check_all_disclaimer_checkboxes(dlg)
    assert total == 2  # invisible filtered out
    assert clicked == 1
    assert cb1.clicks == 1
    assert cb2.clicks == 0


def test_click_checkbox_near_label_prefers_named_toggle(monkeypatch):
    monkeypatch.setattr(bbm, "_try_click_named_toggle", lambda *_args, **_kwargs: True)
    dlg = Dialog([])
    assert bbm.click_checkbox_near_label(dlg, "x") is True


def test_click_checkbox_near_label_fallback_clicks_nearest_checkbox(monkeypatch):
    monkeypatch.setattr(bbm, "_try_click_named_toggle", lambda *_args, **_kwargs: False)
    label = Control(
        name="Direkte LAN-Verbindung geprüft?",
        control_type="Text",
        rect=Rect(10, 10, 200, 30),
    )
    near = Control(name="", control_type="CheckBox", rect=Rect(240, 10, 260, 30), toggle_state=0)
    far = Control(name="", control_type="CheckBox", rect=Rect(400, 10, 420, 30), toggle_state=0)
    dlg = Dialog([label, far, near])

    assert bbm.click_checkbox_near_label(dlg, "Direkte LAN-Verbindung geprüft?") is True
    assert near.clicks == 1
    assert far.clicks == 0


def test_detect_progress_from_ui():
    t1 = Control(name=" 6/10 ", control_type="Text")
    t2 = Control(name=" 6/30 ", control_type="Text")
    win = Dialog([t1, t2])
    assert bbm.detect_progress_from_ui(win, day_goal=10, campaign_goal=30) == (6, 6)


def test_detect_calendar_gap_wait_parses_german_message():
    msg = (
        "Sie können die Messung in 27:36 Stunden durchführen, da zwischen den Messtagen "
        "ein zeitlicher Mindestabstand von einem Kalendertag eingehalten werden muss."
    )
    win = Dialog([Control(name=msg, control_type="Text")])
    assert bbm.detect_calendar_gap_wait(win) == timedelta(hours=27, minutes=36)


def test_detect_campaign_complete_screen_from_text():
    win = Dialog([Control(name="Messkampagne abgeschlossen!", control_type="Text")])
    assert bbm.detect_campaign_complete_screen(win) is True


def test_detect_campaign_complete_screen_from_document_text():
    # The Chromium UIA tree often exposes the whole screen as a single Document element.
    win = Dialog([Control(name="... Messkampagne abgeschlossen! ...", control_type="Document")])
    assert bbm.detect_campaign_complete_screen(win) is True


def test_detect_campaign_complete_screen_from_new_campaign_link_only():
    # Some UI dumps show the "new campaign" control as a Hyperlink.
    win = Dialog([Control(name="Neue Messkampagne starten", control_type="Hyperlink")])
    assert bbm.detect_campaign_complete_screen(win) is True


def test_wait_for_campaign_ready_returns_on_campaign_complete(monkeypatch):
    monkeypatch.setattr(bbm.time, "sleep", lambda *_args, **_kwargs: None)
    win = Dialog([Control(name="Messkampagne abgeschlossen!", control_type="Text")])
    assert bbm.wait_for_campaign_ready(win, timeout=1) is True


def test_click_by_text_clicks(monkeypatch):
    monkeypatch.setattr(bbm, "wait_until_passes", lambda _t, _i, fn: fn())
    btn = Control(name="Messung durchführen", control_type="Button")

    class Win:
        def child_window(self, **_kwargs):
            return btn

    assert bbm.click_by_text(Win(), text="Messung durchführen", control_type="Button", timeout=1) is True
    assert btn.clicks == 1


def test_ensure_on_measurement_tab_clicks_messung(monkeypatch):
    calls = []
    monkeypatch.setattr(bbm.time, "sleep", lambda *_args, **_kwargs: None)

    def _fake_click_by_text(_win, text=None, *, title_re=None, control_type=None, timeout=10):
        calls.append((text, title_re, control_type, timeout))
        return True

    monkeypatch.setattr(bbm, "click_by_text", _fake_click_by_text)

    assert bbm.ensure_on_measurement_tab(object()) is True
    assert calls[0][0] == bbm.TAB_MEASUREMENT


def test_ensure_on_campaign_page_calls_ensure_on_measurement_tab(monkeypatch):
    calls = []
    monkeypatch.setattr(bbm, "ensure_on_measurement_tab", lambda _w: calls.append("tab") or True)

    class Btn:
        def exists(self, *_args, **_kwargs):
            return True

        def wait(self, *_args, **_kwargs):
            return True

    class Win:
        def child_window(self, **_kwargs):
            return Btn()

    bbm.ensure_on_campaign_page(Win())
    assert calls == ["tab"]


def test_click_start_measurement_waits_until_enabled(monkeypatch):
    class Btn:
        def __init__(self):
            self._enabled = False
            self._visible = True
            self.clicks = 0

        def exists(self, *_args, **_kwargs):
            return True

        def wait(self, *_args, **_kwargs):
            return True

        def is_enabled(self):
            return self._enabled

        def is_visible(self):
            return self._visible

        def click_input(self):
            self.clicks += 1
            self._visible = False

    btn = Btn()

    sleep_calls = {"n": 0}

    def _sleep(_s):
        sleep_calls["n"] += 1
        # After one short wait, the button becomes clickable.
        if sleep_calls["n"] >= 1:
            btn._enabled = True

    monkeypatch.setattr(bbm.time, "sleep", _sleep)

    class Win:
        def child_window(self, **_kwargs):
            return btn

    assert bbm.click_start_measurement(Win(), timeout=2) is True
    assert btn.clicks == 1


def test_run_single_measurement_smoke(monkeypatch):
    calls = []
    monkeypatch.setattr(bbm, "ensure_on_campaign_page", lambda _w, **_kw: calls.append("ensure_on_campaign_page"))
    monkeypatch.setattr(bbm, "wait_for_campaign_ready", lambda _w, timeout=0: calls.append(f"ready:{timeout}"))
    monkeypatch.setattr(bbm, "click_by_text", lambda *_a, **_kw: calls.append("click_by_text") or True)
    monkeypatch.setattr(bbm, "click_start_measurement", lambda *_a, **_kw: calls.append("click_start_measurement") or True)
    monkeypatch.setattr(bbm, "_check_all_disclaimer_checkboxes", lambda _d: (6, 6))
    monkeypatch.setattr(bbm, "wait_until_passes", lambda *_a, **_kw: True)
    monkeypatch.setattr(bbm.time, "sleep", lambda *_args, **_kwargs: None)

    times = iter([datetime(2026, 1, 7, 12, 0, 0), datetime(2026, 1, 7, 12, 5, 0)])
    monkeypatch.setattr(bbm, "now", lambda: next(times))

    class Win:
        def set_focus(self):
            return None

    st, et = bbm.run_single_measurement(Win())
    assert st == datetime(2026, 1, 7, 12, 0, 0)
    assert et == datetime(2026, 1, 7, 12, 5, 0)
    assert "ensure_on_campaign_page" in calls
