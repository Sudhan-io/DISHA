"""
DISHA — Reminder & Scheduler Engine
Parses: "remind me in X minutes/hours to Y"
        "remind me at HH:MM to Y"
        "set a timer for X minutes"
Persists to reminders.json, survives restarts.
Runs a background daemon thread that checks every 30 seconds.
"""

import json
import re
import threading
import time
import datetime
from typing import Optional, Callable
from pathlib import Path
from config import REMINDERS_FILE

# Callback injected by main.py at startup
_on_trigger: Optional[Callable[[str], None]] = None


def init(on_trigger: Callable[[str], None]) -> None:
    """
    Call this from main.py after building the Tk root.
    on_trigger: function that shows popup / speaks the reminder text.
    Starts the background checker thread.
    """
    global _on_trigger
    _on_trigger = on_trigger
    t = threading.Thread(target=_checker_loop, daemon=True)
    t.start()


def try_schedule_command(text: str) -> Optional[str]:
    """
    Parse a reminder/timer command. Returns confirmation string or None.
    Patterns matched:
      - "remind me in N minutes/hours/seconds to X"
      - "remind me at H:MM [AM/PM] to X"
      - "set a timer for N minutes/seconds"
    """
    lowered = text.strip().lower()

    # Pattern: "remind me in N minutes/hours/seconds to X"
    m = re.search(r"remind me in (\d+)\s*(minute|hour|second)s?\s*(?:to\s+|about\s+)(.+)", lowered)
    if m:
        n, unit, msg = int(m.group(1)), m.group(2), m.group(3).strip()
        seconds = n * 60 if unit == "minute" else (n * 3600 if unit == "hour" else n)
        due = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        _add_reminder(msg, due)
        return f"I'll remind you about '{msg}' in {n} {unit}{'s' if n > 1 else ''}."

    # Pattern: "set a timer for N minutes"
    m = re.search(r"(?:set a\s+)?timer (?:for\s+)?(\d+)\s*(minute|hour|second)s?", lowered)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        seconds = n * (60 if unit == "minute" else 3600 if unit == "hour" else 1)
        due = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        _add_reminder(f"Timer: {n} {unit}{'s' if n > 1 else ''} up!", due)
        return f"Timer set for {n} {unit}{'s' if n > 1 else ''}."

    # Pattern: "remind me at H:MM [AM/PM] to X"
    m = re.search(r"remind me at (\d{1,2}):(\d{2})\s*(am|pm)?\s*(?:to\s+|about\s+)(.+)", lowered)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        ampm = m.group(3)
        msg = m.group(4).strip()
        now = datetime.datetime.now()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += datetime.timedelta(days=1)  # next occurrence
        _add_reminder(msg, due)
        return f"Reminder set for {due.strftime('%I:%M %p')} — '{msg}'."

    # Pattern: "what are my reminders" / "list reminders" / "show reminders"
    if re.search(r"\b(?:what are my|list|show)\s+reminders\b", lowered):
        rems = [r for r in _load() if not r.get("triggered", False)]
        if not rems:
            return "You have no active reminders right now."
        lines = [f"- {r['message']} (due at {r['due'][11:16]})" for r in rems]
        return "Your active reminders:\n" + "\n".join(lines)

    return None


def _add_reminder(message: str, due: datetime.datetime) -> None:
    reminders = _load()
    reminders.append({
        "message": message,
        "due": due.isoformat(),
        "triggered": False,
    })
    _save(reminders)


def _checker_loop() -> None:
    """Background thread: checks every 5s for precision, fires due reminders."""
    while True:
        try:
            _check_due()
        except Exception:
            pass
        time.sleep(5)


def _check_due() -> None:
    reminders = _load()
    now = datetime.datetime.now()
    changed = False
    for r in reminders:
        if r.get("triggered", False):
            continue
        try:
            due = datetime.datetime.fromisoformat(r["due"])
        except Exception:
            continue
        if now >= due:
            r["triggered"] = True
            changed = True
            if _on_trigger:
                try:
                    _on_trigger(r["message"])
                except Exception:
                    pass
    if changed:
        # Purge triggered reminders older than 24 hours
        cutoff = now - datetime.timedelta(hours=24)
        reminders = [
            r for r in reminders
            if not r.get("triggered") or datetime.datetime.fromisoformat(r["due"]) > cutoff
        ]
        _save(reminders)


def _load() -> list:
    if not REMINDERS_FILE.exists():
        return []
    try:
        return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(reminders: list) -> None:
    try:
        REMINDERS_FILE.write_text(
            json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
