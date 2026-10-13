"""
DISHA — Local Brain (offline rule-based answers)
Handles: time, date, battery, CPU/RAM, Wi-Fi, math, unit conversion,
         and general "what can you do" queries.
Never imports gemini_client. Never makes network calls.
"""

import re
import datetime
import math
import random
import subprocess
from typing import Optional, Callable
import psutil


def _ans_time(m, text: str) -> str:
    now = datetime.datetime.now()
    return f"It's {now.strftime('%I:%M %p')} right now."


def _ans_date(m, text: str) -> str:
    now = datetime.datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}."


def _ans_battery(m, text: str) -> str:
    batt = psutil.sensors_battery()
    if batt is None:
        return "Can't read battery — are you on a desktop?"
    pct = int(batt.percent)
    charging = "charging" if batt.power_plugged else "on battery"
    return f"Battery is at {pct}%, {charging}."


def _ans_cpu(m, text: str) -> str:
    pct = psutil.cpu_percent(interval=0.5)
    return f"CPU is at {pct:.0f}% right now."


def _ans_ram(m, text: str) -> str:
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024**3)
    total_gb = mem.total / (1024**3)
    return f"RAM: {used_gb:.1f} GB used of {total_gb:.1f} GB ({mem.percent:.0f}%)."


def _ans_gpu(m, text: str) -> str:
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            util, mem_used, mem_total, temp, name = parts[0], parts[1], parts[2], parts[3], parts[4]
            return f"{name}: {util}% utilization ({temp}°C, VRAM: {mem_used} MB of {mem_total} MB used)."
    except Exception:
        pass
    return "GPU metrics could not be retrieved from hardware sensors."


def _ans_disk(m, text: str) -> str:
    parts = []
    for p in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(p.mountpoint)
            used_gb = usage.used / (1024**3)
            total_gb = usage.total / (1024**3)
            free_gb = usage.free / (1024**3)
            drive_name = p.device.rstrip("\\")
            parts.append(f"{drive_name} {used_gb:.1f}/{total_gb:.1f} GB ({usage.percent:.0f}%, {free_gb:.1f} GB free)")
        except Exception:
            continue
    return "Disk Space: " + ", ".join(parts) if parts else "Unable to read disk usage."


def _ans_wifi(m, text: str) -> str:
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":", 1)[-1].strip()
                return f"You're connected to '{ssid}'."
        return "Not connected to any Wi-Fi network."
    except Exception:
        return "Can't read Wi-Fi info right now."


def _ans_math_add(m, text: str) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    result = a + b
    return f"{a:g} + {b:g} = {result:g}"


def _ans_math_sub(m, text: str) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    return f"{a:g} - {b:g} = {a - b:g}"


def _ans_math_mul(m, text: str) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    return f"{a:g} × {b:g} = {a * b:g}"


def _ans_math_div(m, text: str) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    if b == 0:
        return "Can't divide by zero."
    return f"{a:g} ÷ {b:g} = {a / b:g}"


def _ans_help(m, text: str) -> str:
    return (
        "I can: open and close apps, control volume, take screenshots, "
        "lock your screen, check battery/CPU/RAM, tell you the time and date, "
        "set reminders, answer questions via Gemini when online, "
        "and hear you out even when you just need to think aloud."
    )


def _ans_greeting(m, text: str) -> str:
    user_name = ""
    try:
        import memory
        user_name = memory.get_fact("user_name", "")
    except Exception:
        pass
    if not user_name:
        try:
            from config import USER_NAME
            if USER_NAME and USER_NAME.lower() not in ("user", "developer"):
                user_name = USER_NAME
        except Exception:
            pass

    greeting = f"Hey {user_name}!" if user_name else "Hey there!"
    options = [
        f"{greeting} What do you need?",
        "Hi! I'm here.",
        "Hello! Go ahead.",
    ]
    return random.choice(options)


def _ans_thanks(m, text: str) -> str:
    return "Anytime."


# Internal pattern table
_PATTERNS: list[tuple[str, Callable]] = [
    (r"\btime\b|\bwhat time\b|\bcurrent time\b", _ans_time),
    (r"\bdate\b|\btoday\b|\bwhat day\b|\bday today\b", _ans_date),
    (r"\bbattery\b|\bcharge\b", _ans_battery),
    (r"\bcpu\b|\bprocessor\b", _ans_cpu),
    (r"\bgpu\b|\bgraphics\b|\bvram\b|\bnvidia\b|\brtx\b", _ans_gpu),
    (r"\bram\b|\bmemory\b|\bram usage\b", _ans_ram),
    (r"\bdisk\b|\bstorage\b|\bdrive space\b|\bhard drive\b|\bssd\b", _ans_disk),
    (r"\bwifi\b|\bwi-?fi\b|\bnetwork\b", _ans_wifi),
    (r"(\d+\.?\d*)\s*\+\s*(\d+\.?\d*)", _ans_math_add),
    (r"(\d+\.?\d*)\s*\*\s*(\d+\.?\d*)", _ans_math_mul),
    (r"(\d+\.?\d*)\s*/\s*(\d+\.?\d*)", _ans_math_div),
    (r"(\d+\.?\d*)\s*-\s*(\d+\.?\d*)", _ans_math_sub),
    (r"what can (you|u) do|what do (you|u) do|what can disha do|features|capabilities|help me", _ans_help),
    (r"\bhi\b|\bhello\b|\bhey\b", _ans_greeting),
    (r"\bthank(s| you)\b", _ans_thanks),
]


def try_answer(text: str) -> Optional[str]:
    """
    Try to answer text locally. Returns answer string or None (caller falls through to Gemini).
    Never raises. Never blocks for more than 2 seconds.
    """
    lowered = text.strip().lower()

    for pattern, handler in _PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            try:
                return handler(m, text)
            except Exception:
                return None
    return None
