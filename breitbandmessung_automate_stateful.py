# -*- coding: utf-8 -*-
import argparse
import json
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, date, time as dtime
from typing import Optional, Tuple

from pywinauto import Desktop
from pywinauto.timings import wait_until_passes, TimeoutError as PywinautoTimeoutError

import sys
from pathlib import Path

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()
LOGFILE = APP_DIR / (Path(sys.argv[0]).stem + ".log" if sys.argv and sys.argv[0] else "breitbandmessung.log")

def _log(msg: str):
    LOGFILE.write_text(LOGFILE.read_text(encoding="utf-8") + msg + "\n" if LOGFILE.exists() else msg + "\n", encoding="utf-8")


WINDOW_TITLE_RE = r".*Breitbandmessung.*"

DISCLAIMER_LABELS = [
    "Direkte LAN-Verbindung geprüft?",
    "WLAN am Router ausgeschaltet und weitere LAN-Verbindungen am Router getrennt?",
    "Keine parallelen Anwendungen und Datenverkehre aktiv?",
    "Aktuelle Router-Firmware installiert?",
    "Energiesparmodi deaktiviert?",
    "VPN-Verbindungen ausgeschaltet?",
]

BTN_DO_MEASUREMENT = "Messung durchführen"
BTN_START_MEASUREMENT = "Messung starten"
NAV_CAMPAIGN = "Messkampagne starten"
TAB_MEASUREMENT = "Messung"
BTN_NEW_CAMPAIGN = "Neue Messkampagne starten"

BTN_DO_MEASUREMENT_RE = r".*Messung.*durchf.*"
BTN_START_MEASUREMENT_RE = r".*Messung.*start.*"
NAV_CAMPAIGN_RE = r".*Messkampagne.*start.*"
TAB_MEASUREMENT_RE = r"^\s*Messung\s*$"
BTN_NEW_CAMPAIGN_RE = r".*Neue.*Messkampagne.*start.*"

DEFAULT_STATE_FILE = "bbm_state.json"


# -----------------------------
# Helpers / time
# -----------------------------
def now() -> datetime:
    return datetime.now()


def iso_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s)


def sleep_until(target: datetime):
    while True:
        remaining = (target - now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))


def required_gap_after_completed(completed_in_day: int) -> timedelta:
    """
    completed_in_day is the number of measurements completed for the day *after* increment.
    Rule: between 5th and 6th start => after completing #5 => 3h gap
          all others => 5 min gap
    """
    return timedelta(hours=3) if completed_in_day == 5 else timedelta(minutes=5)


def parse_hhmm(s: str) -> dtime:
    s = (s or "").strip()
    try:
        hh, mm = s.split(":")
        return dtime(hour=int(hh), minute=int(mm))
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Invalid time {s!r}, expected HH:MM") from e


def day_dt(d: date, t: dtime) -> datetime:
    return datetime.combine(d, t)


def min_gap_after_completed(completed_in_day: int, *, min_gap_buffer_seconds: int) -> timedelta:
    # Always add a safety buffer so we never run at the exact minimum gap.
    return required_gap_after_completed(completed_in_day) + timedelta(seconds=min_gap_buffer_seconds)


def min_remaining_gap_total(
    *,
    next_completed_in_day: int,
    day_goal: int,
    min_gap_buffer_seconds: int,
) -> timedelta:
    # Sum of minimum gaps AFTER completions next_completed_in_day .. (day_goal-1).
    total = timedelta(0)
    for completed in range(next_completed_in_day, day_goal):
        total += min_gap_after_completed(completed, min_gap_buffer_seconds=min_gap_buffer_seconds)
    return total


def latest_start_within_day(window_end: datetime, *, day_end_buffer_seconds: int) -> datetime:
    """
    Start cutoff within the daily window.

    We keep a configurable buffer before window end so the final measurement can actually complete.
    """
    return window_end - timedelta(seconds=day_end_buffer_seconds)


@dataclass(frozen=True)
class CronSchedule:
    """
    Minimal cron-like schedule supporting only minute + hour fields.

    Syntax: "<minute> <hour> * * *"
    - minute: 0-59, supports "*", "*/n", "a,b,c", "a-b", "a-b/n"
    - hour:   0-23, same operators as minute
    Other fields must be "*".
    """

    minutes: Tuple[int, ...]
    hours: Tuple[int, ...]
    raw: str

    def next_on_or_after(self, dt: datetime) -> datetime:
        base = dt.replace(second=0, microsecond=0)
        if dt > base:
            base += timedelta(minutes=1)

        for day_offset in range(0, 370):
            d = base.date() + timedelta(days=day_offset)
            start_hour = base.hour if day_offset == 0 else 0
            for h in self.hours:
                if h < start_hour:
                    continue
                start_minute = base.minute if (day_offset == 0 and h == base.hour) else 0
                m = next((m for m in self.minutes if m >= start_minute), None)
                if m is None:
                    continue
                return datetime.combine(d, dtime(hour=h, minute=m))

            base = datetime.combine(d + timedelta(days=1), dtime(0, 0))

        raise RuntimeError("cron schedule search exceeded bounds")


def _parse_cron_field(field: str, *, min_value: int, max_value: int) -> Tuple[int, ...]:
    field = (field or "").strip()
    if field == "*":
        return tuple(range(min_value, max_value + 1))

    values = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError(f"invalid step: {part!r}")
            values.update(range(min_value, max_value + 1, step))
            continue

        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError(f"invalid step: {part!r}")
        else:
            base, step = part, None

        if "-" in base:
            a_s, b_s = base.split("-", 1)
            a, b = int(a_s), int(b_s)
            if a > b:
                raise ValueError(f"invalid range: {part!r}")
            rng = range(a, b + 1, step or 1)
            values.update(rng)
        else:
            v = int(base)
            values.add(v)

    out = sorted(v for v in values if min_value <= v <= max_value)
    if not out:
        raise ValueError(f"no values in range {min_value}-{max_value}: {field!r}")
    return tuple(out)


def parse_cron_schedule(expr: str) -> CronSchedule:
    parts = [p for p in (expr or "").strip().split() if p]
    if len(parts) != 5:
        raise argparse.ArgumentTypeError("Cron must have 5 fields: '<min> <hour> * * *'")
    minute_s, hour_s, dom, mon, dow = parts
    if dom != "*" or mon != "*" or dow != "*":
        raise argparse.ArgumentTypeError("Only minute+hour cron is supported; use '* * *' for day/month/dow.")
    try:
        minutes = _parse_cron_field(minute_s, min_value=0, max_value=59)
        hours = _parse_cron_field(hour_s, min_value=0, max_value=23)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    return CronSchedule(minutes=minutes, hours=hours, raw=expr)


def parse_next_start(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        raise argparse.ArgumentTypeError("Empty datetime")
    if re.match(r"^\\d{1,2}:\\d{2}$", s):
        t = parse_hhmm(s)
        dt = day_dt(date.today(), t)
        if dt <= now():
            dt += timedelta(days=1)
        return dt
    try:
        return datetime.fromisoformat(s)
    except Exception as e:
        raise argparse.ArgumentTypeError(
            "Invalid datetime; use 'YYYY-MM-DD HH:MM[:SS]' / ISO-8601 or 'HH:MM'."
        ) from e


def choose_next_start_time(
    *,
    last_start: datetime,
    last_end: datetime,
    completed_in_day: int,
    day_goal: int,
    window_end: datetime,
    day_end_buffer_seconds: int,
    min_gap_buffer_seconds: int,
    post_measurement_settle_seconds: int,
    rng: random.Random,
    schedule: Optional[CronSchedule] = None,
) -> Optional[datetime]:
    earliest = max(
        last_start + min_gap_after_completed(completed_in_day, min_gap_buffer_seconds=min_gap_buffer_seconds),
        last_end + timedelta(seconds=post_measurement_settle_seconds),
    )

    min_future = min_remaining_gap_total(
        next_completed_in_day=completed_in_day + 1,
        day_goal=day_goal,
        min_gap_buffer_seconds=min_gap_buffer_seconds,
    )
    # Avoid starting exactly at the cutoff by staying strictly before it (sleep jitter can otherwise push us over).
    latest_allowed_start = latest_start_within_day(window_end, day_end_buffer_seconds=day_end_buffer_seconds) - timedelta(
        seconds=1
    )
    latest = latest_allowed_start - min_future

    if earliest > latest:
        return None

    if schedule is not None:
        cand = schedule.next_on_or_after(earliest)
        return cand if cand <= latest else None

    slack_seconds = max(0.0, (latest - earliest).total_seconds())
    if slack_seconds <= 1.0:
        return earliest

    # Spread measurements across the day by only spending a share of the remaining slack
    # on the current gap, leaving room for later gaps to also vary.
    gaps_left_including_current = max(1, day_goal - completed_in_day)
    avg_slack = slack_seconds / gaps_left_including_current
    extra_seconds = rng.uniform(0.20 * avg_slack, 1.80 * avg_slack)
    extra_seconds = min(slack_seconds, max(0.0, extra_seconds))
    return earliest + timedelta(seconds=extra_seconds)


# -----------------------------
# State
# -----------------------------
def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {
            "day_goal": 10,
            "campaign_goal": 30,
            "campaign_done": 0,
            "current_day": date.today().isoformat(),
            "day_done": 0,
            "last_start": None,
            "last_end": None,
            "measurement_days": [],  # list of YYYY-MM-DD where we did at least 1 measurement
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def ensure_day_rollover(state: dict):
    def _reset_today_progress():
        state["day_done"] = 0
        state["last_start"] = None
        state["last_end"] = None
        # New day => no measurements recorded for "today" yet; keep state consistent.
        prune_today_from_measurement_days_if_no_progress(state)

    today = date.today().isoformat()
    if state.get("current_day") != today:
        state["current_day"] = today
        _reset_today_progress()
        return

    # Guard against stale progress when `current_day` is already "today" but the last activity
    # timestamps are from a previous calendar day (e.g. after a run across midnight).
    day_done = int(state.get("day_done") or 0)
    if day_done <= 0:
        prune_today_from_measurement_days_if_no_progress(state)
        return

    last_activity = None
    for k in ("last_end", "last_start"):
        s = state.get(k)
        if not s:
            continue
        try:
            last_activity = datetime.fromisoformat(s)
            break
        except Exception:
            continue
    if last_activity is not None and last_activity.date().isoformat() != today:
        _reset_today_progress()


def record_measurement_day(state: dict):
    d = state.get("current_day")
    if not d:
        return
    if "measurement_days" not in state or not isinstance(state["measurement_days"], list):
        state["measurement_days"] = []
    if d not in state["measurement_days"]:
        state["measurement_days"].append(d)


def prune_today_from_measurement_days_if_no_progress(state: dict):
    """
    Keeps `measurement_days` consistent with `day_done`.

    If `day_done == 0`, the current day must not be present as the most recent
    measurement day, otherwise calendar-gap calculations can be off by a full
    day (e.g. after using --seed-day-done 0).
    """
    if int(state.get("day_done") or 0) != 0:
        return
    today = state.get("current_day") or date.today().isoformat()
    days = state.get("measurement_days")
    if not isinstance(days, list) or not days:
        return
    while days and days[-1] == today:
        days.pop()


def sync_progress_from_ui(win, state: dict) -> bool:
    """
    Best-effort: update `state["day_done"]` / `state["campaign_done"]` from the app UI.

    Returns True if state was changed.
    """
    try:
        # The progress counters are most reliably visible on the campaign page.
        ensure_on_campaign_page(win)
        ui_prog = detect_progress_from_ui(win, state["day_goal"], state["campaign_goal"])
    except Exception:
        return False
    if not ui_prog:
        return False
    ui_day_done, ui_campaign_done = ui_prog
    changed = False
    if state.get("day_done") != ui_day_done:
        state["day_done"] = ui_day_done
        changed = True
    if state.get("campaign_done") != ui_campaign_done:
        state["campaign_done"] = ui_campaign_done
        changed = True
    return changed


def ui_progress_sync_enabled(args: argparse.Namespace) -> bool:
    """
    Whether UI progress sync should be used for this run.

    Manual seeding should win over UI reads, so we disable UI progress sync when
    --seed-day-done / --seed-campaign-done are provided.
    """
    if not bool(getattr(args, "try_read_ui_progress", False)):
        return False
    if getattr(args, "seed_day_done", None) is not None:
        return False
    if getattr(args, "seed_campaign_done", None) is not None:
        return False
    return True


def calendar_gap_ok(state: dict) -> bool:
    """
    BNetzA rule (as you described): between measurement days >= 1 calendar day.
    That means: if last measurement day was yesterday, today is NOT allowed for a "new day start".
    Allowed patterns: Mon -> Wed -> Fri (diff >= 2 days)
    """
    days = state.get("measurement_days", [])
    if not days:
        return True
    last = date.fromisoformat(days[-1])
    today = date.today()
    delta = (today - last).days
    return delta >= 2  # at least one calendar day *between* => need diff 2+


# -----------------------------
# UI Automation
# -----------------------------
class CalendarGapBlocked(RuntimeError):
    def __init__(self, wait: timedelta, message: str):
        super().__init__(message)
        self.wait = wait
        self.message = message


_CALENDAR_GAP_TIME_RE = re.compile(
    r"\bin\s+(?P<hours>\d{1,3})\s*:\s*(?P<minutes>\d{2})\s*(?:stunden|std\.?|h|hours?)\b",
    re.IGNORECASE,
)


def detect_calendar_gap_wait(win) -> Optional[timedelta]:
    """
    Detects the BNetzA "calendar day gap" block message in the UI and returns the remaining wait time.

    Example: "Sie können die Messung in 27:36 Stunden durchführen, da zwischen den Messtagen ... Kalendertag ..."
    """
    try:
        texts = []
        for t in win.descendants(control_type="Text"):
            try:
                s = (t.window_text() or "").strip()
            except Exception:
                continue
            if s:
                texts.append(s)
        if not texts:
            return None
    except Exception:
        return None

    joined = "\n".join(texts)
    norm = _norm_text(joined)
    if not any(k in norm for k in ("mindestabstand", "kalendertag", "messtagen")):
        return None

    m = _CALENDAR_GAP_TIME_RE.search(joined)
    if not m:
        return None
    hours = int(m.group("hours"))
    minutes = int(m.group("minutes"))
    return timedelta(hours=hours, minutes=minutes)


def detect_campaign_complete_screen(win) -> bool:
    """
    Detects the "Messkampagne abgeschlossen!" screen in the UI.

    This is important because after the last measurement, the usual "Messung durchführen"
    button may no longer appear; instead, the app shows the completion screen with a
    "Neue Messkampagne starten" button.
    """
    # Fast path: try the explicit "new campaign" button.
    for ct in ("Button", None):
        try:
            kwargs = {"title_re": BTN_NEW_CAMPAIGN_RE}
            if ct is not None:
                kwargs["control_type"] = ct
            if win.child_window(**kwargs).exists(timeout=0.2):
                return True
        except Exception:
            pass

    # Fallback: scan visible text.
    try:
        texts = []
        for t in win.descendants(control_type="Text"):
            try:
                s = (t.window_text() or "").strip()
            except Exception:
                continue
            if s:
                texts.append(s)
        if not texts:
            return False
    except Exception:
        return False

    joined = "\n".join(texts)
    norm = _norm_text(joined)
    return ("messkampagne" in norm) and ("abgeschlossen" in norm)

def _find_chrome_content_handle(parent_hwnd: int) -> Optional[int]:
    """
    The Breitbandmessung app UI is rendered inside a Chromium child window.
    The top-level window has almost no UIA-accessible descendants, but the
    'Chrome_RenderWidgetHostHWND' child does.
    """
    try:
        parent = Desktop(backend="win32").window(handle=parent_hwnd)
        for ch in parent.children():
            try:
                if ch.class_name() == "Chrome_RenderWidgetHostHWND":
                    return int(ch.handle)
            except Exception:
                continue
    except Exception:
        return None
    return None


def connect_main_window():
    desk = Desktop(backend="uia")
    wins = desk.windows(title_re=WINDOW_TITLE_RE, top_level_only=True)
    if not wins:
        raise RuntimeError(f"No window found matching title {WINDOW_TITLE_RE!r}")

    visible = [w for w in wins if w.is_visible()]
    candidates = visible or wins

    def _score(w) -> int:
        spec = desk.window(handle=getattr(w, "handle", None))
        score = 0
        try:
            title = (w.window_text() or "").strip()
            if title == "Breitbandmessung":
                score += 50
            if "mozilla firefox" in title.lower():
                score -= 50
        except Exception:
            pass
        try:
            cls = (getattr(w.element_info, "class_name", "") or "").lower()
            if "chrome_widgetwin" in cls:
                score += 20
            if "mozillawindowclass" in cls:
                score -= 20
        except Exception:
            pass

        # Prefer windows where we can also access the Chromium content handle.
        content_hwnd = _find_chrome_content_handle(int(getattr(w, "handle", 0)))
        if content_hwnd:
            score += 20
            content_spec = desk.window(handle=content_hwnd)
        else:
            content_spec = spec

        # Check for typical content elements inside the Chromium host.
        try:
            if content_spec.child_window(title_re=NAV_CAMPAIGN_RE).exists(timeout=0.5):
                score += 10
        except Exception:
            pass
        try:
            if content_spec.child_window(title_re=BTN_DO_MEASUREMENT_RE).exists(timeout=0.5):
                score += 10
        except Exception:
            pass
        return score

    if len(candidates) > 1:
        _log("Multiple windows matched WINDOW_TITLE_RE; selecting best candidate.")
        for w in candidates:
            try:
                _log(f"  hwnd={w.handle} title={w.window_text()!r} visible={w.is_visible()} enabled={w.is_enabled()}")
            except Exception:
                _log("  hwnd=? title=? visible=? enabled=?")

    win = max(candidates, key=_score)
    wait_until_passes(15, 0.5, lambda: win.is_visible() or True)
    win.set_focus()

    top_hwnd = int(getattr(win, "handle", 0))
    content_hwnd = _find_chrome_content_handle(top_hwnd)
    root = desk.window(handle=content_hwnd) if content_hwnd else desk.window(handle=top_hwnd)

    try:
        print(
            f"Connected to window: {win.window_text()!r} (hwnd={top_hwnd})"
            + (f" content_hwnd={content_hwnd}" if content_hwnd else " (no content hwnd found)"),
            flush=True,
        )
    except Exception:
        print("Connected to window (hwnd unknown)", flush=True)
    return root


def dump_ui(win, tag: str) -> Optional[Path]:
    try:
        dump_path = APP_DIR / (
            f"bbm_ui_dump_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        win.print_control_identifiers(filename=str(dump_path))
        _log(f"UI_DUMP tag={tag} path={dump_path}")
        return dump_path
    except Exception as e:
        _log(f"UI_DUMP_FAILED tag={tag} err={e!r}")
        return None


def click_by_text(win, text=None, *, title_re=None, control_type=None, timeout=10):
    def _do():
        candidates = []
        if text is not None:
            if control_type:
                candidates.append(win.child_window(title=text, control_type=control_type))
            candidates.append(win.child_window(title=text))
        if title_re is not None:
            if control_type:
                candidates.append(win.child_window(title_re=title_re, control_type=control_type))
            candidates.append(win.child_window(title_re=title_re))

        last_err = None
        for el in candidates:
            try:
                if not el.exists(timeout=0.5):
                    continue
                el.wait("visible", timeout=3)
                el.click_input()
                return True
            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(f"Control not found/clickable (text={text!r}, title_re={title_re!r})") from last_err
        return True
    return wait_until_passes(timeout, 0.5, _do)


def click_start_measurement(win, *, timeout: int = 30) -> bool:
    """
    Click the "Messung starten" button once it is actually clickable.

    In some app versions the button becomes visible slightly before it becomes clickable/enabled.
    """

    def _get_btn():
        btn = win.child_window(title_re=BTN_START_MEASUREMENT_RE, control_type="Button")
        if not btn.exists(timeout=0.5):
            btn = win.child_window(title_re=BTN_START_MEASUREMENT_RE)
        return btn

    deadline = time.time() + timeout
    last_err = None
    while True:
        if time.time() >= deadline:
            raise PywinautoTimeoutError("'Messung starten' was not clickable in time") from last_err
        try:
            btn = _get_btn()
            btn.wait("visible", timeout=2)

            try:
                btn.wait("enabled", timeout=2)
            except Exception:
                pass

            try:
                if hasattr(btn, "is_enabled") and (not btn.is_enabled()):
                    time.sleep(0.25)
                    continue
            except Exception:
                pass

            btn.click_input()

            # Ensure the click was accepted: the button should disappear or become disabled shortly after.
            time.sleep(0.5)
            try:
                btn2 = _get_btn()
                try:
                    if hasattr(btn2, "is_visible") and (not btn2.is_visible()):
                        return True
                except Exception:
                    return True
                if not btn2.exists(timeout=0.2):
                    return True
                try:
                    btn2.wait("visible", timeout=0.2)
                except Exception:
                    return True
                try:
                    if hasattr(btn2, "is_enabled") and (not btn2.is_enabled()):
                        return True
                except Exception:
                    return True
            except Exception:
                return True
        except Exception as e:
            last_err = e
        time.sleep(0.25)


def rect_center(r):
    return ((r.left + r.right) / 2, (r.top + r.bottom) / 2)


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = (
        s.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _token_set(s: str) -> set:
    ns = _norm_text(s)
    return {t for t in ns.split(" ") if t}


def _try_get_checked_state(el) -> Optional[bool]:
    # For UIA CheckBox/ToggleButton-like controls (Chromium often exposes toggle buttons).
    if hasattr(el, "get_toggle_state"):
        try:
            state = el.get_toggle_state()
            return state == 1  # 1=On, 0=Off, 2=Indeterminate
        except Exception:
            return None
    return None


def _try_click_named_toggle(dialog, label_text: str, *, min_score: float = 0.65) -> bool:
    target_tokens = _token_set(label_text)
    if not target_tokens:
        return False

    best = None
    best_score = 0.0
    for c in dialog.descendants():
        ct = getattr(c.element_info, "control_type", None)
        if ct not in ("Button", "CheckBox"):
            continue
        try:
            name = (c.window_text() or "").strip()
        except Exception:
            continue
        if not name:
            continue

        cand_tokens = _token_set(name)
        if not cand_tokens:
            continue
        overlap = len(target_tokens & cand_tokens)
        coverage = overlap / max(1, len(target_tokens))
        precision = overlap / max(1, len(cand_tokens))
        score = coverage * 0.8 + precision * 0.2
        if score > best_score:
            best_score = score
            best = c

    if best is None or best_score < min_score:
        return False

    try:
        already = _try_get_checked_state(best)
        if already is True:
            return True
    except Exception:
        pass
    best.click_input()
    time.sleep(0.1)
    return True


def _check_all_disclaimer_checkboxes(dialog) -> Tuple[int, int]:
    """
    The 6 main disclaimer items are exposed as unlabeled UIA CheckBox controls.
    Click all unchecked ones in stable visual order.
    """
    checkboxes = []
    for c in dialog.descendants(control_type="CheckBox"):
        try:
            if not c.is_visible():
                continue
            r = c.rectangle()
            checkboxes.append((r.top, r.left, c))
        except Exception:
            continue

    checkboxes.sort(key=lambda x: (x[0], x[1]))
    clicked = 0
    for _, _, cb in checkboxes:
        try:
            state = cb.get_toggle_state()
            if state == 1:
                continue
        except Exception:
            pass
        try:
            cb.click_input()
            clicked += 1
            time.sleep(0.05)
        except Exception:
            continue

    return clicked, len(checkboxes)


def click_checkbox_near_label(dialog, label_text):
    """
    Robustly clicks a disclaimer toggle.

    In the Chromium-hosted UI, these often appear as Buttons with the disclaimer text.
    Fallback: if no directly-labeled control is found, clicks the nearest small-ish
    control to the right of the label.
    """
    target_tokens = _token_set(label_text)

    # 1) Prefer directly-labeled toggles (Button/CheckBox) matching by token overlap.
    if _try_click_named_toggle(dialog, label_text, min_score=0.65):
        return True

    # 2) Fallback: find a label-like element and click nearest clickable to the right.
    label = None
    for t in dialog.descendants():
        ct = getattr(t.element_info, "control_type", None)
        if ct not in ("Text", "Button", "Pane", "Document"):
            continue
        try:
            name = (t.window_text() or "").strip()
        except Exception:
            continue
        if not name:
            continue
        if target_tokens and len(target_tokens & _token_set(name)) / max(1, len(target_tokens)) >= 0.8:
            label = t
            break
    if label is None:
        raise RuntimeError(f"Label not found: {label_text}")

    lr = label.rectangle()
    (lx, ly) = rect_center(lr)

    checkbox_candidates = []
    other_candidates = []
    for c in dialog.descendants():
        ct = getattr(c.element_info, "control_type", None)
        if ct not in ("CheckBox", "Button"):
            continue
        try:
            r = c.rectangle()
        except Exception:
            continue
        (cx, cy) = rect_center(r)
        if cx <= lx + 30:
            continue
        if abs(cy - ly) > 35:
            continue

        w = r.right - r.left
        h = r.bottom - r.top
        if w > 200 or h > 120:
            continue

        dx = (cx - lx)
        score = dx + abs(cy - ly) * 3
        if ct == "CheckBox":
            checkbox_candidates.append((score, dx, c))
        else:
            other_candidates.append((score, c))

    if checkbox_candidates:
        # Prefer the nearest checkbox to the right of the label.
        checkbox_candidates.sort(key=lambda x: (x[1], x[0]))
        checkbox_candidates[0][2].click_input()
        return True

    if not other_candidates:
        raise RuntimeError(f"No checkbox candidate found near label: {label_text}")

    other_candidates.sort(key=lambda x: x[0])
    other_candidates[0][1].click_input()
    return True


def wait_for_campaign_ready(win, timeout=1200):
    deadline = time.time() + timeout
    last_status = 0.0
    while True:
        try:
            btn = win.child_window(title_re=BTN_DO_MEASUREMENT_RE, control_type="Button")
            if not btn.exists(timeout=0.5):
                btn = win.child_window(title_re=BTN_DO_MEASUREMENT_RE)
            btn.wait("visible", timeout=2)
            return True
        except Exception:
            pass

        # After the last measurement of a campaign, the app may show a completion screen
        # instead of returning to the normal campaign page.
        if detect_campaign_complete_screen(win):
            return True

        gap_wait = detect_calendar_gap_wait(win)
        if gap_wait:
            raise CalendarGapBlocked(
                gap_wait,
                f"Calendar-gap block detected in UI; wait remaining: {gap_wait}.",
            )

        now_s = time.time()
        if now_s >= deadline:
            raise PywinautoTimeoutError("timed out")
        if now_s - last_status >= 60:
            remaining = int(deadline - now_s)
            print(f"Still waiting for readiness... ({remaining}s left)", flush=True)
            last_status = now_s
        time.sleep(2)


def ensure_on_measurement_tab(win) -> bool:
    """
    Best-effort: click the "Messung" tab in the campaign UI.

    Some app versions hide the "Messung durchführen" button while on the "Ergebnisse" tab.
    """
    for ct in ("TabItem", "Button", "Text", None):
        try:
            click_by_text(win, TAB_MEASUREMENT, title_re=TAB_MEASUREMENT_RE, control_type=ct, timeout=3)
            time.sleep(0.5)
            return True
        except Exception:
            continue
    return False


def try_start_new_campaign(win) -> bool:
    for ct in ("Button", "Text", None):
        try:
            click_by_text(win, BTN_NEW_CAMPAIGN, title_re=BTN_NEW_CAMPAIGN_RE, control_type=ct, timeout=10)
            return True
        except Exception:
            continue
    return False


def ensure_on_campaign_page(win, *, allow_start_new_campaign: bool = False):
    if allow_start_new_campaign and detect_campaign_complete_screen(win):
        if try_start_new_campaign(win):
            _log("UI new_campaign_started")
            time.sleep(1)

    # Normalize state: if the app was left on "Ergebnisse", switch back to "Messung".
    ensure_on_measurement_tab(win)

    try:
        btn = win.child_window(title_re=BTN_DO_MEASUREMENT_RE, control_type="Button")
        if not btn.exists(timeout=0.5):
            btn = win.child_window(title_re=BTN_DO_MEASUREMENT_RE)
        btn.wait("visible", timeout=2)
        return
    except Exception:
        pass

    # Try navigation / "start campaign" entry points.
    for ct in ("Button", "Text", None):
        try:
            click_by_text(win, NAV_CAMPAIGN, title_re=NAV_CAMPAIGN_RE, control_type=ct, timeout=5)
            break
        except Exception:
            continue

    time.sleep(1)
    try:
        btn = win.child_window(title_re=BTN_DO_MEASUREMENT_RE, control_type="Button")
        if not btn.exists(timeout=0.5):
            btn = win.child_window(title_re=BTN_DO_MEASUREMENT_RE)
        btn.wait("visible", timeout=2)
    except Exception as e:
        _log(f"UI campaign_page_nav_done but button not visible yet: {e!r}")
        # Don't fail here: the app may enforce a cool-down; run_single_measurement will wait for readiness.
        return


def run_single_measurement(win, *, allow_start_new_campaign: bool = False) -> Tuple[datetime, datetime]:
    ensure_on_campaign_page(win, allow_start_new_campaign=allow_start_new_campaign)

    # If the app enforces a cool-down, this button may appear later; wait a bit before failing.
    print("Waiting for 'Messung durchführen' to become available...", flush=True)
    wait_for_campaign_ready(win, timeout=900)
    click_by_text(win, BTN_DO_MEASUREMENT, title_re=BTN_DO_MEASUREMENT_RE, control_type="Button", timeout=10)

    def _wait_start_btn():
        btn = win.child_window(title_re=BTN_START_MEASUREMENT_RE, control_type="Button")
        if not btn.exists(timeout=0.5):
            btn = win.child_window(title_re=BTN_START_MEASUREMENT_RE)
        btn.wait("visible", timeout=2)
        return True

    wait_until_passes(
        15, 0.5,
        _wait_start_btn
    )

    win.set_focus()
    dialog = win

    # Only tick the unlabeled checkboxes. The "Automatisch überprüfte Angaben" tiles
    # are also clickable and may open a blocking popup, so we intentionally avoid them.
    clicked, total = _check_all_disclaimer_checkboxes(dialog)
    _log(f"UI disclaimers_checkboxes clicked={clicked} total={total}")

    start_time = now()
    click_start_measurement(win, timeout=30)

    wait_for_campaign_ready(win, timeout=1800)
    end_time = now()
    return start_time, end_time


# -----------------------------
# Optional: try read progress from UI
# -----------------------------
def detect_progress_from_ui(win, day_goal: int, campaign_goal: int) -> Optional[Tuple[int, int]]:
    """
    Best-effort: scan UI elements for patterns like "6/10" and "6/30".
    Returns (day_done, campaign_done) if found.
    """
    strict = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
    loose = re.compile(r"(\d+)\s*/\s*(\d+)")
    pairs = []

    def _collect(descendants):
        for el in descendants:
            try:
                s = (el.window_text() or "").strip()
            except Exception:
                continue
            if not s:
                continue
            m = strict.match(s)
            if m:
                pairs.append((int(m.group(1)), int(m.group(2))))
                continue
            m2 = loose.search(s)
            if m2:
                pairs.append((int(m2.group(1)), int(m2.group(2))))

    # Fast path: most UIs expose these as Text elements.
    _collect(win.descendants(control_type="Text"))
    # Fallback: Chromium-hosted UIs sometimes expose text on other element types.
    _collect(win.descendants())

    day_done = None
    campaign_done = None
    for a, b in pairs:
        if b == day_goal:
            day_done = a
        if b == campaign_goal:
            campaign_done = a

    if day_done is not None and campaign_done is not None:
        return (day_done, campaign_done)
    return None


# -----------------------------
# Main
# -----------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    ap.add_argument("--day-goal", type=int, default=None)
    ap.add_argument("--campaign-goal", type=int, default=None)
    ap.add_argument(
        "--skip-initial-wait",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip the initial resume wait (default: enabled, useful to validate the first run).",
    )
    ap.add_argument("--random-seed", type=int, default=None, help="Optional RNG seed for scheduling.")

    # Seed / resume options
    ap.add_argument("--seed-day-done", type=int, default=None, help="If you already did X/10 today, set X once.")
    ap.add_argument("--seed-campaign-done", type=int, default=None, help="If you already did Y/30 overall, set Y once.")
    ap.add_argument(
        "--try-read-ui-progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Best-effort read of 6/10 and 6/30 from UI (default: enabled; auto-disabled when seeding).",
    )

    # Safety / scheduling
    ap.add_argument(
        "--enforce-calendar-gap",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enforce at least 1 full calendar day between measurement days (default: enabled).",
    )
    ap.add_argument(
        "--wait-calendar-gap",
        action="store_true",
        help="If calendar-gap blocks, sleep until allowed instead of stopping.",
    )
    ap.add_argument("--force", action="store_true", help="Ignore calendar-gap block.")

    # Control how much to run now
    ap.add_argument(
        "--run-until-campaign-done",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run across days until the campaign is complete (default: enabled).",
    )
    ap.add_argument(
        "--run-forever",
        action="store_true",
        help="After finishing a campaign, start a new one and continue forever (requires app support).",
    )
    ap.add_argument(
        "--run-today",
        action="store_true",
        help="Alias for --no-run-until-campaign-done (stop after today's limit).",
    )

    # Daily scheduling / spreading
    ap.add_argument("--day-start", type=parse_hhmm, default=parse_hhmm("07:00"), help="Daily window start HH:MM.")
    ap.add_argument("--day-end", type=parse_hhmm, default=parse_hhmm("23:00"), help="Daily window end HH:MM.")
    ap.add_argument(
        "--day-end-buffer-seconds",
        type=int,
        default=1800,
        help="Keep this much time before --day-end free (prevents scheduling the last start too close to window end).",
    )
    ap.add_argument(
        "--next-start",
        type=parse_next_start,
        default=None,
        help="Override the start time of the next measurement (ISO datetime or HH:MM).",
    )
    ap.add_argument(
        "--schedule-cron",
        type=parse_cron_schedule,
        default=None,
        help="Cron-like schedule for measurement starts: '<min> <hour> * * *' (minute+hour only).",
    )
    ap.add_argument(
        "--day-start-jitter-minutes",
        type=int,
        default=45,
        help="Random delay (0..N minutes) applied to the first measurement of a new day.",
    )
    ap.add_argument(
        "--min-gap-buffer-seconds",
        type=int,
        default=120,
        help="Safety buffer added on top of the minimum required gaps (prevents cutting it too close).",
    )
    ap.add_argument(
        "--post-measurement-settle-seconds",
        type=int,
        default=30,
        help="Additional settle time after a measurement completes before scheduling the next one.",
    )
    return ap


def main():
    args = build_arg_parser().parse_args()
    if getattr(sys, "frozen", False):
        p = Path(args.state_file)
        if not p.is_absolute():
            args.state_file = str((APP_DIR / p).resolve())

    if args.day_end <= args.day_start:
        raise SystemExit("--day-end must be later than --day-start (same-day window).")
    if args.day_end_buffer_seconds < 0:
        raise SystemExit("--day-end-buffer-seconds must be >= 0.")
    window_len_seconds = (day_dt(date.today(), args.day_end) - day_dt(date.today(), args.day_start)).total_seconds()
    if args.day_end_buffer_seconds >= window_len_seconds:
        raise SystemExit("--day-end-buffer-seconds is too large for the configured daily window.")

    schedule = args.schedule_cron
    if schedule is not None:
        d0 = date(2000, 1, 1)
        start_dt = day_dt(d0, args.day_start)
        end_dt = day_dt(d0, args.day_end)
        latest_start_dt = latest_start_within_day(end_dt, day_end_buffer_seconds=args.day_end_buffer_seconds)
        any_in_window = False
        for h in schedule.hours:
            for m in schedule.minutes:
                t = datetime.combine(d0, dtime(hour=h, minute=m))
                if start_dt <= t < latest_start_dt:
                    any_in_window = True
                    break
            if any_in_window:
                break
        if not any_in_window:
            raise SystemExit(
                "--schedule-cron has no times within the daily window (after applying --day-end-buffer-seconds); "
                "adjust --schedule-cron/--day-start/--day-end/--day-end-buffer-seconds."
            )

    rng_seed = args.random_seed if args.random_seed is not None else int(now().timestamp())
    rng = random.Random(rng_seed)
    _log(f"SCHED rng_seed={rng_seed}")

    state = load_state(args.state_file)

    # Override goals if provided
    if args.day_goal is not None:
        state["day_goal"] = args.day_goal
    if args.campaign_goal is not None:
        state["campaign_goal"] = args.campaign_goal

    ensure_day_rollover(state)

    # Connect window early (needed for UI progress read)
    win = connect_main_window()

    # Optionally read progress from UI (disabled when seeding).
    ui_sync = ui_progress_sync_enabled(args)
    if ui_sync:
        sync_progress_from_ui(win, state)
    elif args.try_read_ui_progress and (args.seed_day_done is not None or args.seed_campaign_done is not None):
        _log("UI ui_progress_sync_skipped reason=manual_seed")

    # Seed progress (one-time or when you know UI is correct)
    if args.seed_day_done is not None:
        if args.seed_day_done < 0 or args.seed_day_done > state["day_goal"]:
            raise SystemExit(f"--seed-day-done must be in [0..{state['day_goal']}].")
        state["day_done"] = args.seed_day_done
    if args.seed_campaign_done is not None:
        if args.seed_campaign_done < 0 or args.seed_campaign_done > state["campaign_goal"]:
            raise SystemExit(f"--seed-campaign-done must be in [0..{state['campaign_goal']}].")
        state["campaign_done"] = args.seed_campaign_done

    if state.get("day_done", 0) > 0:
        record_measurement_day(state)
    else:
        # If day_done was seeded down to 0, ensure we don't carry "today" in measurement_days.
        prune_today_from_measurement_days_if_no_progress(state)
        state["last_start"] = None
        state["last_end"] = None

    # Initial wait if resuming and we know last_start
    last_start = parse_iso_dt(state.get("last_start"))
    last_end = parse_iso_dt(state.get("last_end"))
    if state["day_done"] > 0:
        if args.skip_initial_wait:
            print(
                f"Resuming at {state['day_done']}/{state['day_goal']} today. "
                f"Skipping initial wait (use --no-skip-initial-wait to enforce it)."
            )
        else:
            gap = min_gap_after_completed(state["day_done"], min_gap_buffer_seconds=args.min_gap_buffer_seconds)
            if last_start:
                next_allowed = last_start + gap
            else:
                next_allowed = now() + gap  # conservative
            if last_end:
                next_allowed = max(next_allowed, last_end + timedelta(seconds=args.post_measurement_settle_seconds))
            if now() < next_allowed:
                print(f"Resuming at {state['day_done']}/{state['day_goal']} today. Waiting until {next_allowed} ...")
                sleep_until(next_allowed)

    save_state(args.state_file, state)

    if args.run_today:
        run_until_campaign = False
    else:
        run_until_campaign = args.run_until_campaign_done or args.run_forever
    next_start_override = args.next_start

    def _day_start_end(d: date) -> Tuple[datetime, datetime]:
        return day_dt(d, args.day_start), day_dt(d, args.day_end)

    def _latest_start_for_day(d: date) -> datetime:
        _day_start_dt, _day_end_dt = _day_start_end(d)
        return latest_start_within_day(_day_end_dt, day_end_buffer_seconds=args.day_end_buffer_seconds)

    def _next_allowed_measurement_day(last_measured_day: date) -> date:
        if args.enforce_calendar_gap and not args.force:
            return last_measured_day + timedelta(days=2)
        return last_measured_day + timedelta(days=1)

    def _first_start_for_day(d: date) -> datetime:
        day_start_dt, day_end_dt = _day_start_end(d)
        latest_start_dt = _latest_start_for_day(d)
        latest_allowed_start_dt = latest_start_dt - timedelta(seconds=1)
        min_gaps = min_remaining_gap_total(
            next_completed_in_day=1,
            day_goal=state["day_goal"],
            min_gap_buffer_seconds=args.min_gap_buffer_seconds,
        )
        latest_first = latest_allowed_start_dt - min_gaps
        if schedule is not None:
            cand = schedule.next_on_or_after(day_start_dt)
            return cand if cand < latest_start_dt else day_start_dt

        jitter_cap_seconds = max(0, args.day_start_jitter_minutes) * 60
        jitter_room = max(0.0, (latest_first - day_start_dt).total_seconds())
        jitter_seconds = rng.uniform(0.0, min(jitter_cap_seconds, jitter_room)) if jitter_room > 0 else 0.0
        return day_start_dt + timedelta(seconds=jitter_seconds)

    ui_failures = 0
    while state["campaign_done"] < state["campaign_goal"]:
        ensure_day_rollover(state)
        today = date.fromisoformat(state["current_day"])
        day_start_dt, day_end_dt = _day_start_end(today)
        latest_start_dt = _latest_start_for_day(today)

        if state["day_done"] >= state["day_goal"]:
            if not run_until_campaign:
                print("Daily limit reached. Stop for today.")
                return

            last_measured = date.fromisoformat(state["measurement_days"][-1]) if state.get("measurement_days") else today
            next_day = _next_allowed_measurement_day(last_measured)
            target = _first_start_for_day(next_day)
            print(f"Daily limit reached. Next measurement day earliest: {target}.")
            _log(f"SCHED daily_limit next={iso_dt(target)}")
            print(f"Waiting until next measurement day: {target} ...")
            sleep_until(target)
            continue

        # Calendar-gap enforcement only when starting a new day (day_done == 0)
        if args.enforce_calendar_gap and not args.force and state["day_done"] == 0 and state.get("measurement_days"):
            if not calendar_gap_ok(state):
                # If state says "new day start", but the UI still shows e.g. 9/10, we're actually resuming
                # an incomplete measurement day (midnight rollover). Trust the UI to avoid false blocks.
                try:
                    win = connect_main_window()
                    if ui_sync and sync_progress_from_ui(win, state) and int(state.get("day_done") or 0) > 0:
                        _log(
                            f"SCHED ui_progress_resume day_done={state.get('day_done')} "
                            f"campaign_done={state.get('campaign_done')}"
                        )
                        save_state(args.state_file, state)
                        print(
                            f"UI shows progress {state['day_done']}/{state['day_goal']} "
                            f"today; treating this as a resume (not a new measurement day)."
                        )
                        continue
                except Exception:
                    pass

                last = date.fromisoformat(state["measurement_days"][-1])
                next_day = _next_allowed_measurement_day(last)
                target = _first_start_for_day(next_day)
                print(
                    f"Calendar-gap predicted from state (last measurement day: {last.isoformat()}). "
                    f"Earliest next start: {target}."
                )
                _log(f"SCHED calendar_gap_predicted next={iso_dt(target)} last={last.isoformat()}")
                if args.wait_calendar_gap and run_until_campaign:
                    print(f"Waiting until {target} ...")
                    sleep_until(target)
                    continue
                # Don't exit here: the state-based calendar-gap check is a heuristic and can be wrong
                # if a measurement day carried across midnight. The UI-level check in run_single_measurement
                # will still enforce the rule if the app blocks.

        # If it's before the daily window, wait until the window opens.
        # (Also applies when resuming an incomplete measurement day across midnight.)
        if now() < day_start_dt:
            target = _first_start_for_day(today) if state["day_done"] == 0 else day_start_dt
            if now() < target:
                print(f"Waiting for daily window start: {target} ...")
                _log(f"SCHED day_window_start sleep_until={iso_dt(target)}")
                sleep_until(target)
            continue

        # Optional: align to a user-provided schedule / start override before attempting the next measurement.
        planned = None
        planned_is_override = False
        if next_start_override is not None:
            planned = next_start_override
            planned_is_override = True
        elif schedule is not None:
            planned = schedule.next_on_or_after(now())

        if planned is not None:
            planned = planned.replace(second=0, microsecond=0)
            if planned > now():
                # If this wait would cross a calendar-gap blocked period, default to stopping unless explicitly told to wait.
                if (
                    args.enforce_calendar_gap
                    and not args.force
                    and state["day_done"] == 0
                    and state.get("measurement_days")
                ):
                    last = date.fromisoformat(state["measurement_days"][-1])
                    allowed_day = last + timedelta(days=2)
                    if planned.date() < allowed_day:
                        planned = _first_start_for_day(allowed_day)

                # Don't wait past the point where finishing today's remaining measurements becomes infeasible.
                if planned.date() == today:
                    latest_next_start = (latest_start_dt - timedelta(seconds=1)) - min_remaining_gap_total(
                        next_completed_in_day=state["day_done"] + 1,
                        day_goal=state["day_goal"],
                        min_gap_buffer_seconds=args.min_gap_buffer_seconds,
                    )
                    if planned > latest_next_start:
                        msg = (
                            f"WARNING: Planned next start {planned} is too late to finish today "
                            f"(latest feasible next start: {latest_next_start}). Starting earlier."
                        )
                        print(msg)
                        _log("SCHED " + msg)
                        planned = None
                        next_start_override = None

                if planned is not None:
                    if (
                        (not planned_is_override)
                        and (not args.wait_calendar_gap)
                        and (planned.date() - today).days >= 2
                        and (not run_until_campaign)
                    ):
                        print(
                            f"Calendar-gap wait required. Earliest next start: {planned}. "
                            f"(Use --wait-calendar-gap to sleep)"
                        )
                        _log(f"SCHED calendar_gap_stop next={iso_dt(planned)}")
                        return

                    print(f"Next measurement scheduled at {planned} ...")
                    _log(f"SCHED next_override sleep_until={iso_dt(planned)}")
                    sleep_until(planned)
                    next_start_override = None
                    continue
            next_start_override = None

        # If it's too late to start/continue today, warn and roll to the next day.
        if now() >= latest_start_dt:
            if state["day_done"] == 0:
                print(
                    f"WARNING: It's past today's start cutoff ({latest_start_dt}) "
                    f"(window end {day_end_dt}). "
                    f"Not starting a new measurement day now."
                )
            else:
                print(
                    f"WARNING: It's past today's start cutoff ({latest_start_dt}) "
                    f"(window end {day_end_dt}). "
                    f"Day may not be completable ({state['day_done']}/{state['day_goal']} done)."
                )

            if not run_until_campaign:
                return

            if state["day_done"] == 0:
                next_day = today + timedelta(days=1)
            else:
                last_measured = (
                    date.fromisoformat(state["measurement_days"][-1]) if state.get("measurement_days") else today
                )
                next_day = _next_allowed_measurement_day(last_measured)
            target = _first_start_for_day(next_day)
            print(f"Waiting until next measurement day: {target} ...")
            _log(f"SCHED day_end sleep_until={iso_dt(target)} day_done={state.get('day_done')}")
            sleep_until(target)
            continue

        # Feasibility check: can we still finish today's remaining measurements within the window?
        latest_next_start = (latest_start_dt - timedelta(seconds=1)) - min_remaining_gap_total(
            next_completed_in_day=state["day_done"] + 1,
            day_goal=state["day_goal"],
            min_gap_buffer_seconds=args.min_gap_buffer_seconds,
        )
        if now() > latest_next_start:
            msg = (
                f"WARNING: Starting the next measurement now ({now()}) is too late to finish "
                f"today within the window ending at {day_end_dt} "
                f"(done {state['day_done']}/{state['day_goal']})."
            )
            print(msg)
            _log("SCHED " + msg)
            if state["day_done"] == 0 and run_until_campaign:
                next_day = today + timedelta(days=1)
                target = _first_start_for_day(next_day)
                print(f"Waiting until next measurement day: {target} ...")
                _log(f"SCHED infeasible_start sleep_until={iso_dt(target)}")
                sleep_until(target)
                continue

        # Refresh the window (script may sleep for hours/days)
        try:
            win = connect_main_window()
            st, et = run_single_measurement(win, allow_start_new_campaign=args.run_forever)
            ui_failures = 0
        except CalendarGapBlocked as e:
            ui_failures = 0
            earliest = now() + e.wait + timedelta(seconds=30)
            d = earliest.date()
            day_start_dt, day_end_dt = _day_start_end(d)
            latest_start_dt = _latest_start_for_day(d)
            if earliest > latest_start_dt:
                target = _first_start_for_day(d + timedelta(days=1))
            else:
                target = max(earliest, _first_start_for_day(d))
            print(f"Calendar-gap block in UI. Earliest next start: {target}.")
            _log(f"SCHED calendar_gap_ui next={iso_dt(target)} wait={e.wait}")
            if run_until_campaign:
                print(f"Waiting until {target} ...")
                sleep_until(target)
                continue
            return
        except (PywinautoTimeoutError, RuntimeError) as e:
            ui_failures += 1
            dump_path = dump_ui(win, "ui_failure") if "win" in locals() else None
            delay = min(600, 30 * ui_failures)
            msg = f"WARNING: UI not ready ({e}). Retrying in {delay}s..."
            print(msg, flush=True)
            _log("UI_RETRY " + msg + (f" dump={dump_path}" if dump_path else ""))
            sleep_until(now() + timedelta(seconds=delay))
            continue
        state["last_start"] = iso_dt(st)
        state["last_end"] = iso_dt(et)
        state["day_done"] += 1
        state["campaign_done"] += 1
        record_measurement_day(state)
        save_state(args.state_file, state)

        print(f"Done: day {state['day_done']}/{state['day_goal']} | campaign {state['campaign_done']}/{state['campaign_goal']}")

        if state["campaign_done"] >= state["campaign_goal"]:
            print("Campaign complete.")
            if args.run_forever:
                try:
                    if detect_campaign_complete_screen(win):
                        print("UI shows campaign completion; starting new campaign...", flush=True)
                    if try_start_new_campaign(win):
                        time.sleep(1)
                except Exception as e:
                    _log(f"UI new_campaign_start_failed err={e!r}")
                state["campaign_cycles_completed"] = int(state.get("campaign_cycles_completed", 0)) + 1
                state["campaign_done"] = 0
                save_state(args.state_file, state)
                print(f"Starting next campaign (completed cycles: {state['campaign_cycles_completed']}).")
                continue
            return

        if state["day_done"] >= state["day_goal"]:
            # loop will handle next-day waiting (or stop if --run-today)
            continue

        next_start = choose_next_start_time(
            last_start=st,
            last_end=et,
            completed_in_day=state["day_done"],
            day_goal=state["day_goal"],
            window_end=day_end_dt,
            day_end_buffer_seconds=args.day_end_buffer_seconds,
            min_gap_buffer_seconds=args.min_gap_buffer_seconds,
            post_measurement_settle_seconds=args.post_measurement_settle_seconds,
            rng=rng,
            schedule=schedule,
        )

        if next_start is None:
            msg = (
                f"WARNING: Cannot schedule the remaining measurements today within the window ending at {day_end_dt}. "
                f"(done {state['day_done']}/{state['day_goal']})."
            )
            print(msg)
            _log("SCHED " + msg)
            if not run_until_campaign:
                return

            last_measured = date.fromisoformat(state["measurement_days"][-1]) if state.get("measurement_days") else today
            next_day = _next_allowed_measurement_day(last_measured)
            target = _first_start_for_day(next_day)
            print(f"Waiting until next measurement day: {target} ...")
            _log(f"SCHED cannot_fit_today sleep_until={iso_dt(target)}")
            sleep_until(target)
            continue

        print(
            f"Next measurement scheduled at {next_start} "
            f"(start cutoff {latest_start_dt}, window end {day_end_dt})"
        )
        _log(
            f"SCHED next_start={iso_dt(next_start)} start_cutoff={iso_dt(latest_start_dt)} window_end={iso_dt(day_end_dt)}"
        )
        sleep_until(next_start)


if __name__ == "__main__":
    import faulthandler
    faulthandler.enable()

    try:
        _log(f"BOOT exe={sys.executable} argv={sys.argv}")
        print("BOOT: script started, writing log to", str(LOGFILE), flush=True)
        print("Starting Breitbandmessung automation...", flush=True)
        main()
    except Exception as e:
        import sys, traceback
        print("FATAL ERROR:", e, file=sys.stderr)
        traceback.print_exc()
        raise
