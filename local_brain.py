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


_last_gpu_check = 0.0
_cached_gpu_str = ""

_last_wifi_check = 0.0
_cached_wifi_str = ""


def _ans_cpu(m, text: str) -> str:
    pct = psutil.cpu_percent(interval=None)
    return f"CPU is at {pct:.0f}% right now."


def _ans_ram(m, text: str) -> str:
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024**3)
    total_gb = mem.total / (1024**3)
    return f"RAM: {used_gb:.1f} GB used of {total_gb:.1f} GB ({mem.percent:.0f}%)."


def _ans_gpu(m, text: str) -> str:
    global _last_gpu_check, _cached_gpu_str
    import time
    now = time.monotonic()
    if _cached_gpu_str and (now - _last_gpu_check) < 10.0:
        return _cached_gpu_str

    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0 and res.stdout.strip():
            lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
            reports = []
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    util, mem_used, mem_total, temp, name = parts[0], parts[1], parts[2], parts[3], parts[4]
                    reports.append(f"{name}: {util}% utilization ({temp}°C, VRAM: {mem_used} MB of {mem_total} MB used).")
            if reports:
                _cached_gpu_str = " ".join(reports)
                _last_gpu_check = now
                return _cached_gpu_str
    except Exception:
        pass

    # Windows CIM fallback for non-NVIDIA or sleeping dGPUs
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0 and res.stdout.strip():
            gpus = [g.strip() for g in res.stdout.strip().splitlines() if g.strip()]
            _cached_gpu_str = "Active GPUs: " + ", ".join(gpus) + " (Hardware sensors idle)."
            _last_gpu_check = now
            return _cached_gpu_str
    except Exception:
        pass

    _cached_gpu_str = "GPU metrics could not be retrieved from hardware sensors."
    _last_gpu_check = now
    return _cached_gpu_str


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
    global _last_wifi_check, _cached_wifi_str
    import time
    now = time.monotonic()
    if _cached_wifi_str and (now - _last_wifi_check) < 10.0:
        return _cached_wifi_str

    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":", 1)[-1].strip()
                _cached_wifi_str = f"You're connected to '{ssid}'."
                _last_wifi_check = now
                return _cached_wifi_str
        _cached_wifi_str = "Not connected to any Wi-Fi network."
        _last_wifi_check = now
        return _cached_wifi_str
    except Exception:
        return "Can't read Wi-Fi info right now."


def _ans_clipboard(m, text: str) -> str:
    try:
        import pyperclip
        content = pyperclip.paste().strip()
        if not content:
            return "Clipboard is empty."
        if len(content) > 120:
            content = content[:117] + "..."
        return f"Clipboard: {content}"
    except Exception:
        return "Clipboard is empty."


def _ans_smart_math(m, text: str) -> str:
    """Evaluate arithmetic, percentages, square roots, and powers safely via SymPy and math."""
    import re
    cleaned = text.lower().strip()

    # Check for square root: "square root of X" or "sqrt of X"
    sqrt_m = re.search(r"(?:square root of|square root|sqrt of|sqrt)\s+(\d+\.?\d*)", cleaned)
    if sqrt_m:
        num = float(sqrt_m.group(1))
        val = math.sqrt(num)
        return f"The square root of {sqrt_m.group(1)} is {val:g}"

    # Check for percentage: "X % of Y" or "X percent of Y"
    pct_m = re.search(r"(\d+\.?\d*)\s*(?:%|percent)\s+of\s+(\d+\.?\d*)", cleaned)
    if pct_m:
        val = (float(pct_m.group(1)) / 100.0) * float(pct_m.group(2))
        return f"{pct_m.group(1)}% of {pct_m.group(2)} = {val:g}"

    calc_expr = cleaned
    for prefix in ["what is", "calculate", "solve", "math", "what's"]:
        if calc_expr.startswith(prefix):
            calc_expr = calc_expr[len(prefix):].strip()
    calc_expr = calc_expr.rstrip("?").strip()
    calc_expr = calc_expr.replace("×", "*").replace("x", "*").replace("÷", "/").replace("^", "**")

    try:
        import sympy
        if re.match(r"^[0-9\.\+\-\*\/\(\)\s\^\,sqrt]+$", calc_expr):
            res = sympy.sympify(calc_expr).evalf()
            res_float = float(res)
            return f"{calc_expr} = {res_float:g}"
    except Exception:
        pass

    # Basic fallback
    if m and len(m.groups()) >= 2:
        try:
            a, b = float(m.group(1)), float(m.group(2))
            if "+" in cleaned: return f"{a:g} + {b:g} = {a+b:g}"
            if "-" in cleaned: return f"{a:g} - {b:g} = {a-b:g}"
            if "*" in cleaned or "×" in cleaned: return f"{a:g} × {b:g} = {a*b:g}"
            if "/" in cleaned or "÷" in cleaned: return "Can't divide by zero." if b == 0 else f"{a:g} ÷ {b:g} = {a/b:g}"
        except Exception:
            pass
    return "Could not compute math expression."


def _ans_help(m, text: str) -> str:
    return (
        "I can: open and close apps, control volume, take screenshots, "
        "lock your screen, check battery/CPU/RAM/GPU, read clipboard, tell you time and date, "
        "set reminders, answer questions via Gemini or local Ollama, "
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


def _ans_set_name(m, text: str) -> str:
    """Acknowledge when user states their name, persist to memory, and update runtime."""
    try:
        import memory
        import config
        start, end = m.span(1)
        raw_name = text[start:end].strip().rstrip(".,!?")
        words = raw_name.split()
        if any(w.lower() in getattr(memory, "COMMON_NON_NAMES", set()) for w in words) or len(raw_name) < 2:
            return "Hello! What can I help you with today?"
        name = raw_name.title()
        memory.save_fact("user_name", name)
        config.USER_NAME = name
        return f"Nice to meet you, {name}! I've saved your name."
    except Exception:
        return "Got it! I've saved your name."


def _ans_get_name(m, text: str) -> str:
    """Report the user's name from memory facts or config."""
    try:
        import memory
        import config
        name = memory.get_fact("user_name", "") or getattr(config, "USER_NAME", "")
        if name and name.lower() not in ("user", "developer"):
            return f"Your name is {name}."
        return "I don't know your name yet. You can tell me by saying 'my name is [your name]'."
    except Exception:
        return "I don't know your name yet."


# Internal pattern table
_PATTERNS: list[tuple[str, Callable]] = [
    (r"(?:my name is|call me|you can call me|i am called)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", _ans_set_name),
    (r"\b(?:what is|what's|do you know)\s+(?:my|my own)\s+name\b|\bwho am i\b", _ans_get_name),
    (r"\b(?:what time is it(?: right now)?|what(?:'s| is) (?:the )?(?:current )?time(?: right now)?|tell me the time|current time|time right now)\b|^\s*time\s*$", _ans_time),
    (r"\b(?:what(?:'s| is) (?:the |today(?:'s)? )?date|what(?:'s| is) today(?:'s)?(?: date)?|what day is (?:it|today)|today(?:'s)? date|tell me the date|current date)\b|^\s*(?:date|today)\s*$", _ans_date),
    (r"\bbattery\b|\bcharge\b", _ans_battery),
    (r"\bcpu\b|\bprocessor\b", _ans_cpu),
    (r"\bgpu\b|\bgraphics\b|\bvram\b|\bnvidia\b|\brtx\b", _ans_gpu),
    (r"\bram\b|\bmemory\b|\bram usage\b", _ans_ram),
    (r"\bdisk\b|\bstorage\b|\bdrive space\b|\bhard drive\b|\bssd\b", _ans_disk),
    (r"\bwifi\b|\bwi-?fi\b|\bnetwork\b", _ans_wifi),
    (r"what did i (just )?copy|clipboard", _ans_clipboard),
    (r"(?:square root|sqrt)\s*(?:of)?\s*\d+", _ans_smart_math),
    (r"(\d+\.?\d*)\s*(?:%|percent)\s+of\s+(\d+\.?\d*)", _ans_smart_math),
    (r"(\d+\.?\d*)\s*[\+\-\*\/]\s*(\d+\.?\d*)", _ans_smart_math),
    (r"(?:calculate|solve|what is|what's)\s+[0-9\.\+\-\*\/\(\)\s\^\%]+", _ans_smart_math),
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
