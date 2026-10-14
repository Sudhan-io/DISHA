"""
DISHA — Reminder & Scheduler Engine
Parses:
  - Alarms:
      "set an alarm at 10:30 am today"
      "set an alarm for 7:00 am"
      "alarm at 10:30"
      "is there any alarm set"
      "how long until alarm"
  - Timers:
      "set a timer for 10 minutes"
      "timer 5 minutes"
  - Reminders:
      "remind me in X minutes to Y"
      "remind me at HH:MM to Y"
      "remind me at 10:30 am today"
Persists to reminders.json, survives restarts.
Plays audible alarm chime tone and triggers notification on due time.
"""

import json
import re
import threading
import time
import datetime
from typing import Optional, Callable
from pathlib import Path
from config import REMINDERS_FILE

# Callback injected by main.py at startup: on_trigger(message: str, is_alarm: bool = False)
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


def play_alarm_chime() -> None:
    """Play an audible electronic alarm melody in background thread (never blocks)."""
    def _ring():
        try:
            import winsound
            # Upbeat 3-tone arpeggio (C6, E6, G6) repeated 3 times
            chime_notes = [(1046, 120), (1318, 120), (1568, 250)]
            for _ in range(3):
                for freq, dur in chime_notes:
                    winsound.Beep(freq, dur)
                    time.sleep(0.04)
                time.sleep(0.18)
        except Exception:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass

    threading.Thread(target=_ring, daemon=True).start()


def try_schedule_command(text: str) -> Optional[str]:
    """
    Parse alarm, reminder, or timer commands. Returns confirmation string or None.
    Never raises.
    """
    lowered = text.strip().lower()
    now = datetime.datetime.now()

    # -----------------------------------------------------------------------
    # 1. Clear / Cancel Alarms, Reminders, or Timers
    # -----------------------------------------------------------------------
    if re.search(r"\b(?:clear|cancel|delete|remove|stop)\s+(?:all\s+)?(?:al[a-z]?rm|alarm|timer|reminder)s?\b", lowered):
        _save([])
        return "All alarms, timers, and reminders have been cleared."

    # -----------------------------------------------------------------------
    # 2. Check / List Alarms (e.g. "is there any alarm set", "check alarms", "any alrm set")
    # -----------------------------------------------------------------------
    if re.search(r"\b(?:is there any|any|what|check|list|show)\s+(?:active\s+)?(?:al[a-z]{1,3}m|al[a-z]?rm|alarm)s?(?:\s+set)?\b", lowered):
        active = [r for r in _load() if not r.get("triggered", False) and r.get("type", "reminder") == "alarm"]
        if not active:
            return "You don't have any active alarms set right now."
        lines = []
        for a in active:
            try:
                dt = datetime.datetime.fromisoformat(a["due"])
                t_str = dt.strftime("%I:%M %p")
                day_str = "today" if dt.date() == now.date() else ("tomorrow" if dt.date() == (now + datetime.timedelta(days=1)).date() else dt.strftime("%A, %b %d"))
                diff = dt - now
                mins = max(0, int(diff.total_seconds() // 60))
                time_rel = "right now" if mins == 0 else (f"in about {mins} minute{'s' if mins > 1 else ''}")
                lines.append(f"- {t_str} {day_str} ({time_rel})")
            except Exception:
                lines.append(f"- {a.get('message', 'Alarm')}")
        return f"You have {len(active)} alarm{'s' if len(active) > 1 else ''} set:\n" + "\n".join(lines)

    # -----------------------------------------------------------------------
    # 3. How long until alarm / Time left (e.g. "how long until alarm", "how mong until alfm", "time until alarm")
    # -----------------------------------------------------------------------
    if re.search(r"\b(?:how\s+(?:long|much time|mong)|time\s+until|when\s+is|when\s+does)\s+(?:until\s+|left\s+for\s+)?(?:the\s+|my\s+)?(?:al[a-z]{1,3}m|al[a-z]?rm|alarm|timer|reminder)s?(?:\s+go\s+off)?\b", lowered):
        active = [r for r in _load() if not r.get("triggered", False)]
        if not active:
            return "You don't have any active alarms or reminders scheduled."
        
        # Sort by nearest due time
        def _due_key(item):
            try:
                return datetime.datetime.fromisoformat(item["due"])
            except Exception:
                return datetime.datetime.max
        active.sort(key=_due_key)
        nearest = active[0]
        try:
            dt = datetime.datetime.fromisoformat(nearest["due"])
            diff = dt - now
            total_sec = int(diff.total_seconds())
            t_str = dt.strftime("%I:%M %p")
            if total_sec <= 0:
                return f"Your {nearest.get('type', 'alarm')} for {t_str} is going off right now!"
            
            hours = total_sec // 3600
            mins = (total_sec % 3600) // 60
            secs = total_sec % 60
            
            parts = []
            if hours > 0:
                parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
            if mins > 0:
                parts.append(f"{mins} minute{'s' if mins > 1 else ''}")
            if hours == 0 and mins < 2 and secs > 0:
                parts.append(f"{secs} second{'s' if secs > 1 else ''}")
            
            rel_str = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + f", and {parts[-1]}"
            day_str = "today" if dt.date() == now.date() else "tomorrow"
            return f"Your {nearest.get('type', 'alarm')} for {t_str} {day_str} goes off in {rel_str}."
        except Exception:
            return f"Your next scheduled alert is {nearest.get('message', 'active')}."

    # -----------------------------------------------------------------------
    # 4. Set Alarm (e.g. "set an alarm at 10:30 am today", "alarm for 7:00 am", "set alarm at 10:30")
    # -----------------------------------------------------------------------
    m_alarm = re.search(
        r"(?:set\s+(?:an?\s+)?)?alarm\s+(?:at|for)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s+(today|tomorrow))?(?:\s+(?:for|to|about)\s+(.+))?",
        lowered
    )
    if m_alarm:
        hour = int(m_alarm.group(1))
        minute = int(m_alarm.group(2)) if m_alarm.group(2) else 0
        ampm = m_alarm.group(3)
        day_kw = m_alarm.group(4)
        msg = m_alarm.group(5).strip() if m_alarm.group(5) else ""

        # Handle 12-hour AM/PM normalization
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif not ampm:
            # If no AM/PM provided and hour <= 12, infer intelligently
            if hour < now.hour and (hour + 12) < 24:
                hour += 12

        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_kw == "tomorrow" or (due <= now and day_kw != "today"):
            due += datetime.timedelta(days=1)
        elif day_kw == "today" and due <= now:
            # If time already passed today, assume tomorrow
            due += datetime.timedelta(days=1)

        alarm_label = msg if msg else f"Alarm for {due.strftime('%I:%M %p')}"
        _add_item(alarm_label, due, item_type="alarm")
        day_text = "today" if due.date() == now.date() else "tomorrow"
        return f"Alarm set for {due.strftime('%I:%M %p')} {day_text}."

    # -----------------------------------------------------------------------
    # 5. Set Timer (e.g. "set a timer for 10 minutes", "timer 5 minutes")
    # -----------------------------------------------------------------------
    m_timer = re.search(r"(?:set a\s+)?timer (?:for\s+)?(\d+)\s*(minute|hour|second)s?", lowered)
    if m_timer:
        n, unit = int(m_timer.group(1)), m_timer.group(2)
        seconds = n * (60 if unit == "minute" else 3600 if unit == "hour" else 1)
        due = now + datetime.timedelta(seconds=seconds)
        _add_item(f"Timer: {n} {unit}{'s' if n > 1 else ''} up!", due, item_type="timer")
        return f"Timer set for {n} {unit}{'s' if n > 1 else ''}."

    # -----------------------------------------------------------------------
    # 6. Remind me in N minutes/hours (e.g. "remind me in 10 minutes to drink water")
    # -----------------------------------------------------------------------
    m_rem_rel = re.search(r"remind me in (\d+)\s*(minute|hour|second)s?\s*(?:to\s+|about\s+)(.+)", lowered)
    if m_rem_rel:
        n, unit, msg = int(m_rem_rel.group(1)), m_rem_rel.group(2), m_rem_rel.group(3).strip()
        seconds = n * 60 if unit == "minute" else (n * 3600 if unit == "hour" else n)
        due = now + datetime.timedelta(seconds=seconds)
        _add_item(msg, due, item_type="reminder")
        return f"I'll remind you about '{msg}' in {n} {unit}{'s' if n > 1 else ''}."

    # -----------------------------------------------------------------------
    # 7. Remind me at HH:MM [AM/PM] (e.g. "remind me at 10:30 am to check mail")
    # -----------------------------------------------------------------------
    m_rem_abs = re.search(r"remind me at (\d{1,2}):(\d{2})\s*(am|pm)?(?:\s+(today|tomorrow))?(?:\s+(?:to\s+|about\s+)(.+))?", lowered)
    if m_rem_abs:
        hour, minute = int(m_rem_abs.group(1)), int(m_rem_abs.group(2))
        ampm = m_rem_abs.group(3)
        day_kw = m_rem_abs.group(4)
        msg = m_rem_abs.group(5).strip() if m_rem_abs.group(5) else f"Reminder at {hour}:{minute:02d}"

        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_kw == "tomorrow" or (due <= now and day_kw != "today"):
            due += datetime.timedelta(days=1)
        elif day_kw == "today" and due <= now:
            due += datetime.timedelta(days=1)

        _add_item(msg, due, item_type="reminder")
        day_text = "today" if due.date() == now.date() else "tomorrow"
        return f"Reminder set for {due.strftime('%I:%M %p')} {day_text} — '{msg}'."

    # -----------------------------------------------------------------------
    # 8. List Reminders (e.g. "what are my reminders", "list reminders")
    # -----------------------------------------------------------------------
    if re.search(r"\b(?:what are my|list|show)\s+(?:reminders|timers)\b", lowered):
        rems = [r for r in _load() if not r.get("triggered", False)]
        if not rems:
            return "You have no active reminders or alarms right now."
        lines = []
        for r in rems:
            try:
                dt = datetime.datetime.fromisoformat(r["due"])
                time_str = dt.strftime("%I:%M %p")
            except Exception:
                time_str = r.get("due", "")[11:16]
            tag = "⏰" if r.get("type") == "alarm" else ("⏳" if r.get("type") == "timer" else "🔔")
            lines.append(f"{tag} {r['message']} (due at {time_str})")
        return "Your active schedule:\n" + "\n".join(lines)

    return None


def _add_item(message: str, due: datetime.datetime, item_type: str = "reminder") -> None:
    items = _load()
    items.append({
        "message": message,
        "due": due.isoformat(),
        "type": item_type,
        "triggered": False,
    })
    _save(items)


def _checker_loop() -> None:
    """Background thread: checks every 3 seconds for precision, fires due items."""
    while True:
        try:
            _check_due()
        except Exception:
            pass
        time.sleep(3)


def _check_due() -> None:
    items = _load()
    now = datetime.datetime.now()
    changed = False
    for r in items:
        if r.get("triggered", False):
            continue
        try:
            due = datetime.datetime.fromisoformat(r["due"])
        except Exception:
            continue
        if now >= due:
            r["triggered"] = True
            changed = True
            is_alarm = r.get("type") == "alarm" or "alarm" in r.get("message", "").lower()
            if is_alarm:
                play_alarm_chime()
            if _on_trigger:
                try:
                    # Pass message to UI trigger
                    _on_trigger(r["message"])
                except Exception:
                    pass
    if changed:
        cutoff = now - datetime.timedelta(hours=24)
        items = [
            r for r in items
            if not r.get("triggered") or datetime.datetime.fromisoformat(r["due"]) > cutoff
        ]
        _save(items)


def _load() -> list:
    if not REMINDERS_FILE.exists():
        return []
    try:
        return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list) -> None:
    import os
    temp_path = REMINDERS_FILE.with_suffix(".tmp")
    try:
        temp_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temp_path, REMINDERS_FILE)
    except OSError:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
