# DISHA — Master Architecture Blueprint
## Complete Technical Plan for Agent Execution

> **Status:** Canonical reference — every implementation decision is made here.  
> **Hardware:** Lenovo 83GS · Intel i5-12450HX (8C/12T) · 16GB RAM · Windows 11  
> **Python:** 3.10 (project venv) · venv at `d:\PROJECTS\disha\venv`  
> **Goal:** A personal virtual assistant that works online + offline, by voice + text, on laptop + USB drive, accessible locally + remotely — interactive, intuitive, and creative.

---

## ⚠️ AGENT OPERATING RULES — READ BEFORE EVERY SESSION

> [!IMPORTANT]
> These rules override any default agent behaviour. Violating any rule is a failure.

1. **Never invent a library.** Only use packages confirmed in the venv's `site-packages` or explicitly added in `requirements.txt` in this document.
2. **Never use absolute paths** in source code. Always use `BASE_DIR = Path(__file__).resolve().parent` from `config.py`.
3. **Never block the Tk main thread.** Every I/O call → `threading.Thread(target=..., daemon=True).start()`.
4. **Never call Gemini without `is_online()` returning True first.**
5. **Never let an STT session start while TTS is playing** — always call `voice.wait_for_tts()` first.
6. **Every feature must have an offline path.** If the feature requires internet, it must degrade gracefully (not crash or hang).
7. **Never hardcode credentials.** All secrets come from `.env` via `config.py`.
8. **Preserve all existing docstrings and comments** unless the line being replaced makes them wrong.
9. **After every phase, run the acceptance test** listed at the end of that phase. Do not proceed to the next phase if any test fails.
10. **The goal sentence** — repeat this every session: *"DISHA must always respond usefully — voice or text, online or offline, on laptop or USB — without hanging, crashing, or going silent."*

---

## PART A — CONFIRMED ENVIRONMENT STATE

### A.1 — Packages ALREADY in venv (confirmed by site-packages scan)

| Package | Available | Notes |
|---------|-----------|-------|
| `vosk` | ✅ | Offline STT — model at `d:\PROJECTS\disha\model\` |
| `sounddevice` | ✅ | Mic input |
| `pyttsx3` | ✅ | Fallback TTS |
| `win32com` / `pywin32` | ✅ | Windows SAPI5 TTS (primary) |
| `numpy` | ✅ | v2.2.6 — audio RMS calculations |
| `PIL` (Pillow) | ✅ | Icon generation + screenshots |
| `pystray` | ✅ | System tray icon |
| `pynput` | ✅ | Global hotkeys |
| `google-generativeai` | ✅ | v0.8.6 — Gemini API |
| `requests` | ✅ | HTTP calls |
| `websockets` | ✅ | WebSocket server (remote access) |
| `cryptography` | ✅ | USB token verification |
| `pydantic` | ✅ | Data validation |
| `tqdm` | ✅ | Progress bars |

### A.2 — Packages NOT in venv — MUST INSTALL

| Package | Why | Install Command |
|---------|-----|----------------|
| `flask` | Remote web interface | `pip install flask>=3.0.0` |
| `psutil` | Battery, CPU, RAM queries | `pip install psutil>=6.0.0` |
| `pyperclip` | Clipboard access | `pip install pyperclip>=1.9.0` |
| `fuzzywuzzy` + `python-Levenshtein` | Fuzzy app matching | `pip install fuzzywuzzy python-Levenshtein` |
| `schedule` | Background cron-style reminders | `pip install schedule>=1.2.0` |
| `comtypes` | Already present (pywin32 dep) | — |

> [!NOTE]
> Ollama is NOT installed. Local offline LLM is Phase 4. All phases before it use Gemini (online) + rule-based local brain (offline). Do NOT attempt Ollama until Phase 4 is explicitly started.

### A.3 — Vosk Model State
- Model is present at `d:\PROJECTS\disha\model\`
- Contains: `am/final.mdl` (15.9MB), `graph/Gr.fst` (24MB), `graph/HCLr.fst` (22.4MB), `ivector/`
- This is the full `vosk-model-en-us` model — good accuracy
- **Do NOT re-download or replace it**

---

## PART B — FINAL TARGET ARCHITECTURE

```
disha/
├── main.py                  ← Entry point: UI + hotkeys + tray + routing
├── config.py                ← All settings, loaded from .env
├── voice.py                 ← STT (Vosk) + TTS (SAPI5/pyttsx3) + wake word
├── gemini_client.py         ← Online AI (Gemini) with online/offline routing
├── local_brain.py           ← NEW: Offline rule-based answers
├── app_launcher.py          ← Local app open/close + system commands
├── memory.py                ← Rolling log + structured fact store
├── scheduler.py             ← NEW: Reminder + timed task engine
├── web_interface.py         ← NEW: Flask remote access server
├── usb_guard.py             ← NEW: Portable mode detection + verification
├── .env                     ← Secrets (never commit)
├── .env.example             ← Template
├── requirements.txt         ← Pinned dependencies
├── setup_startup.bat        ← Windows Task Scheduler auto-start
├── DISHA_Launcher.bat       ← NEW: USB portable launcher
├── memory_log.jsonl         ← Rolling conversation log (auto-managed)
├── facts.json               ← NEW: Persistent user facts
├── reminders.json           ← NEW: Pending reminders
├── model/                   ← Vosk model (DO NOT TOUCH)
│   ├── am/
│   ├── conf/
│   ├── graph/
│   └── ivector/
├── assets/
│   └── icon.png             ← Auto-generated if missing
└── venv/                    ← Python virtual environment
```

---

## PART C — MODULE SPECIFICATIONS

> [!NOTE]
> Each module spec defines: purpose, all public functions with exact signatures, all internal state, all imports, and all contracts (what it promises, what it never does).

---

### C.1 — `config.py` (MODIFY EXISTING)

**Purpose:** Single source of all runtime configuration. Loaded once at import time.

**Exact content after modification:**

```python
"""
DISHA — Configuration v2
All settings load from .env. Never hardcode values here.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── AI / Online ────────────────────────────────────────────────────────────
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL       = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")      # FIXED (was gemini-3.1-flash-lite)

# ── Hotkeys ─────────────────────────────────────────────────────────────────
HOTKEY             = os.getenv("DISHA_HOTKEY", "<ctrl>+<alt>+d")
VOICE_HOTKEY       = os.getenv("DISHA_VOICE_HOTKEY", "<ctrl>+<alt>+v")

# ── Voice / STT ─────────────────────────────────────────────────────────────
VOSK_MODEL_PATH    = os.getenv("VOSK_MODEL_PATH", str(BASE_DIR / "model"))
TTS_ENABLED        = os.getenv("DISHA_TTS_ENABLED", "true").lower() == "true"
TTS_RATE           = int(os.getenv("DISHA_TTS_RATE", "175"))
TTS_VOICE_GENDER   = os.getenv("DISHA_TTS_VOICE", "female")
SILENCE_STOP_SECONDS = float(os.getenv("DISHA_SILENCE_STOP", "1.4"))

# ── Wake Word ────────────────────────────────────────────────────────────────
WAKE_WORD_ENABLED  = os.getenv("DISHA_WAKE_WORD", "false").lower() == "true"
WAKE_WORD          = os.getenv("DISHA_WAKE_PHRASE", "hey disha").lower()

# ── Memory ───────────────────────────────────────────────────────────────────
MEMORY_FILE        = BASE_DIR / "memory_log.jsonl"
FACTS_FILE         = BASE_DIR / "facts.json"
REMINDERS_FILE     = BASE_DIR / "reminders.json"
MEMORY_MAX_ENTRIES = int(os.getenv("DISHA_MEMORY_MAX", "20"))

# ── Remote Web Interface ─────────────────────────────────────────────────────
WEB_ENABLED        = os.getenv("DISHA_WEB_ENABLED", "false").lower() == "true"
WEB_PORT           = int(os.getenv("DISHA_WEB_PORT", "5000"))
WEB_TOKEN          = os.getenv("DISHA_WEB_TOKEN", "")

# ── USB Portable Mode ────────────────────────────────────────────────────────
USB_MODE           = os.getenv("DISHA_USB_MODE", "false").lower() == "true"
DEVICE_ID_FILE     = BASE_DIR / "device_id.txt"

# ── App Launcher ─────────────────────────────────────────────────────────────
APP_COMMANDS: dict[str, str] = {
    "vscode": "code", "vs code": "code", "visual studio code": "code",
    "chrome": "chrome", "google chrome": "chrome",
    "firefox": "firefox",
    "notepad": "notepad", "notepad++": "notepad++",
    "calculator": "calc", "calc": "calc",
    "file explorer": "explorer", "explorer": "explorer", "files": "explorer",
    "terminal": "wt", "windows terminal": "wt",
    "command prompt": "cmd", "cmd": "cmd",
    "task manager": "taskmgr",
    "settings": "ms-settings:", "windows settings": "ms-settings:",
    "paint": "mspaint",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "spotify": "spotify",
    "discord": "discord",
    "zoom": "zoom",
}

# ── Personality ───────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are DISHA, a personal desktop companion for the developer.
Keep replies SHORT — 2 sentences max unless asked to elaborate.
You sit quietly in the background and only speak when asked.
Be direct, warm, and never waste time. No corporate tone.
If ambiguous, make a reasonable assumption and answer immediately.
Reference the user's name occasionally but not always.
Never say 'I cannot' — always find a way or suggest the closest alternative."""

# ── App metadata ──────────────────────────────────────────────────────────────
APP_NAME  = "DISHA"
ICON_PATH = BASE_DIR / "assets" / "icon.png"
```

**`.env` additions needed:**
```
GEMINI_MODEL=gemini-2.5-flash
DISHA_VOICE_HOTKEY=<ctrl>+<alt>+v
DISHA_WAKE_WORD=false
DISHA_WAKE_PHRASE=hey disha
DISHA_WEB_ENABLED=false
DISHA_WEB_PORT=5000
DISHA_WEB_TOKEN=changeme123
DISHA_USB_MODE=false
```

---

### C.2 — `main.py` (MODIFY EXISTING — Fix Bug + Upgrade UI)

**Critical bug to fix first:** `start_listening()` is nested inside `focus_text_input()` at line 212. Must be un-indented to be a proper class method.

**UI Upgrade:** Replace single `Label` (current) with scrollable `tk.Text` widget that shows the full chat history.

**Public interface (unchanged):**
- `main()` — entry point
- `open_or_focus_assistant(root, mode: str)` — opens overlay
- `route_request(user_input: str) -> str` — routes to local brain or Gemini

**Class `DishaAssistantWindow` — methods after fix:**
```python
class DishaAssistantWindow:
    def __init__(self, root): ...
    def _build_ui(self): ...
    def _start_drag(self, event): ...
    def _do_drag(self, event): ...
    def focus_text_input(self): ...          # ← was incorrectly containing start_listening
    def start_listening(self): ...           # ← MOVED OUT — now a proper method
    def submit_text(self): ...
    def append_message(self, role: str, text: str): ...   # NEW — adds to chat log
    def set_status(self, text: str): ...     # NEW — updates status bar
    def close(self): ...
```

**`append_message` contract:**
- `role` is `"You"`, `"DISHA"`, or `"System"`
- Appends formatted line `[HH:MM] Role: text\n` to the `tk.Text` widget
- Scrolls to bottom automatically
- Colors: You=`#89b4fa`, DISHA=`#a6e3a1`, System=`#fab387`
- Widget is `state=DISABLED` by default (read-only), enabled briefly to insert, disabled again

**`route_request` upgrade:**
```python
def route_request(user_input: str) -> str:
    # 1. Try local command (app open/close, system controls) — always offline
    local_response = app_launcher.try_local_command(user_input)
    if local_response is not None:
        memory.log_exchange(user_input, local_response)
        return local_response
    
    # 2. Try scheduler commands (reminders) — always offline
    sched_response = scheduler.try_schedule_command(user_input)
    if sched_response is not None:
        memory.log_exchange(user_input, sched_response)
        return sched_response

    # 3. Try local brain (date, time, battery, math) — always offline
    brain_response = local_brain.try_answer(user_input)
    if brain_response is not None:
        memory.log_exchange(user_input, brain_response)
        return brain_response

    # 4. Gemini (online) or graceful offline message
    context = memory.get_recent_context()
    answer = gemini_client.ask(user_input, context)
    memory.log_exchange(user_input, answer)
    return answer
```

---

### C.3 — `voice.py` (MODIFY EXISTING — Confidence + Wake Word)

**Changes to existing tunables:**
```python
MIN_AVG_CONF      = getattr(_cfg, "VOICE_MIN_AVG_CONF", 0.80)      # was 0.70 — raise it
SINGLE_WORD_CONF  = getattr(_cfg, "VOICE_SINGLE_WORD_CONF", 0.92)  # was 0.90 — raise it
NO_SPEECH_TIMEOUT = getattr(_cfg, "VOICE_NO_SPEECH_TIMEOUT", 4.0)  # was 6.0 — faster
```

**New public function to ADD:**
```python
def listen_for_wake_word(callback: Callable[[], None], stop_event: threading.Event) -> None:
    """
    Continuously monitor microphone for WAKE_WORD (from config).
    When heard with confidence >= 0.85, calls callback() on the main thread.
    Runs until stop_event.is_set().
    
    Contract:
    - Never raises exceptions (catches all internally)
    - Never blocks forever — loops with 0.1s sleep between checks
    - Does NOT acquire _listen_lock (it uses a separate recognizer instance)
    - Does NOT call speak() or any TTS
    - callback is called via root.after() — must be set via set_root(root) first
    """
```

**New module-level state:**
```python
_root_ref = None  # set by set_root() so wake word can schedule on Tk thread

def set_root(root) -> None:
    """Store Tk root reference for thread-safe callbacks."""
    global _root_ref
    _root_ref = root
```

**Unchanged public functions:** `speak()`, `listen()`, `is_listening()`, `list_input_devices()`

---

### C.4 — `gemini_client.py` (MODIFY EXISTING — Fix Model Name)

**Only change:** Fix `GEMINI_MODEL` default (already fixed in config.py — gemini_client reads from config, so it picks up the fix automatically).

**Add streaming support for future use (Phase 2+):**
```python
def ask_streaming(prompt: str, context: str = "", on_chunk: Callable[[str], None] = None) -> str:
    """
    Like ask(), but calls on_chunk(partial_text) as tokens arrive.
    Falls back to non-streaming ask() if on_chunk is None.
    Returns full response as string.
    """
```

**No other changes to this file in Phase 0 or Phase 1.**

---

### C.5 — `app_launcher.py` (MODIFY EXISTING — Add System Commands)

**Add a new section for system commands BEFORE the existing app logic:**

```python
# ── System command patterns ───────────────────────────────────────────────────
# Each entry: (regex_pattern, handler_function)
# handler_function(match) -> str response

import re
import ctypes
import subprocess
import psutil         # must be installed
from PIL import ImageGrab
from pathlib import Path
import datetime

SYSTEM_PATTERNS: list[tuple[str, Callable]] = [
    # Volume
    (r"set volume to (\d+)", _cmd_set_volume),
    (r"volume (up|down)", _cmd_volume_change),
    (r"(mute|unmute)", _cmd_mute_toggle),
    # Screen
    (r"(take|grab) (a )?screenshot", _cmd_screenshot),
    (r"lock (my )?(screen|computer|pc)", _cmd_lock_screen),
    # Power
    (r"(shutdown|shut down|turn off)", _cmd_shutdown),
    (r"restart|reboot", _cmd_restart),
    (r"(sleep|hibernate)", _cmd_sleep),
    # Battery
    (r"(battery|charge|power)", _cmd_battery),
    # Clipboard
    (r"what did i (just )?copy|clipboard", _cmd_read_clipboard),
    # System info
    (r"(cpu|processor) usage", _cmd_cpu_usage),
    (r"(ram|memory) usage", _cmd_ram_usage),
    (r"(wifi|network|internet) (name|ssid)", _cmd_wifi_name),
    # Files
    (r"open (my )?downloads", _cmd_open_downloads),
    (r"open (my )?documents", _cmd_open_documents),
    (r"open (my )?desktop", _cmd_open_desktop),
    # Recycle Bin
    (r"empty (recycle )?bin", _cmd_empty_bin),
]
```

**Handler function signatures (all must exist):**
```python
def _cmd_set_volume(match) -> str:    # uses nircmd or PowerShell
def _cmd_volume_change(match) -> str: # up = +10, down = -10
def _cmd_mute_toggle(match) -> str:   # mute or unmute
def _cmd_screenshot(match) -> str:    # saves to Desktop, returns filename
def _cmd_lock_screen(match) -> str:   # ctypes.windll.user32.LockWorkStation()
def _cmd_shutdown(match) -> str:      # shows confirmation dialog first
def _cmd_restart(match) -> str:       # shows confirmation dialog first
def _cmd_sleep(match) -> str:         # subprocess.run(["rundll32","powrprof.dll,SetSuspendState 0,1,0"])
def _cmd_battery(match) -> str:       # psutil.sensors_battery()
def _cmd_read_clipboard(match) -> str:# pyperclip.paste()
def _cmd_cpu_usage(match) -> str:     # psutil.cpu_percent(interval=1)
def _cmd_ram_usage(match) -> str:     # psutil.virtual_memory()
def _cmd_wifi_name(match) -> str:     # subprocess netsh wlan show interfaces
def _cmd_open_downloads(match) -> str:# os.startfile(Path.home() / "Downloads")
def _cmd_open_documents(match) -> str:# os.startfile(Path.home() / "Documents")
def _cmd_open_desktop(match) -> str:  # os.startfile(Path.home() / "Desktop")
def _cmd_empty_bin(match) -> str:     # ctypes winshell call
```

**Modified `try_local_command`:**
```python
def try_local_command(text: str) -> Optional[str]:
    lowered = text.strip().lower()
    
    # Check system commands FIRST (higher priority than app names)
    for pattern, handler in SYSTEM_PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            try:
                return handler(m)
            except Exception as e:
                return f"Couldn't do that: {e}"
    
    # Then check app open/close triggers (existing logic, unchanged)
    for trigger in OPEN_TRIGGERS:
        if lowered.startswith(trigger):
            app_name = lowered[len(trigger):].strip()
            return _launch_app(app_name)
    
    for trigger in CLOSE_TRIGGERS:
        if lowered.startswith(trigger):
            app_name = lowered[len(trigger):].strip()
            return _close_app(app_name)
    
    return None
```

**Volume control implementation** (uses PowerShell, no external tool needed):
```python
def _cmd_set_volume(match) -> str:
    level = int(match.group(1))
    level = max(0, min(100, level))
    script = f"(New-Object -ComObject WScript.Shell).SendKeys([char]174 * 50); " \
             f"$vol = {level}; " \
             f"$wsh = New-Object -ComObject WScript.Shell"
    # Better approach: use win32com audio
    # from comtypes import CLSCTX_ALL
    # from pycaw.audio_utilities import AudioUtilities  ← NOT available
    # Use PowerShell nircmd approach:
    subprocess.run(
        ["powershell", "-Command",
         f"$obj = New-Object -ComObject WScript.Shell; "
         f"1..50 | ForEach-Object {{ $obj.SendKeys([char]174) }}; "
         f"$steps = [Math]::Round({level} / 2); "
         f"1..$steps | ForEach-Object {{ $obj.SendKeys([char]175) }}"],
        capture_output=True, shell=False
    )
    return f"Volume set to approximately {level}%."
```

> [!WARNING]
> `pycaw` is not in the venv. Use the PowerShell WScript.Shell key-send approach for volume. It's approximate but works on all Windows 10/11 without additional installs.

---

### C.6 — `local_brain.py` (NEW FILE)

**Purpose:** Answer common questions completely offline without Gemini. Fast, deterministic, zero network.

**Full module specification:**

```python
"""
DISHA — Local Brain (offline rule-based answers)
Handles: time, date, battery, CPU/RAM, Wi-Fi, math, unit conversion,
         weather cache reads, and general "what can you do" queries.
Never imports gemini_client. Never makes network calls.
"""

import re
import datetime
import math
import psutil
import subprocess
from typing import Optional

# Public function — the only one called from main.py/route_request
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

# Internal pattern table
_PATTERNS: list[tuple[str, Callable]] = [
    (r"\btime\b|\bwhat time\b|\bcurrent time\b",    _ans_time),
    (r"\bdate\b|\btoday\b|\bwhat day\b|\bday today\b", _ans_date),
    (r"\bbattery\b|\bcharge\b",                     _ans_battery),
    (r"\bcpu\b|\bprocessor\b",                      _ans_cpu),
    (r"\bram\b|\bmemory\b|\bram usage\b",           _ans_ram),
    (r"\bwifi\b|\bwi-?fi\b|\bnetwork\b",            _ans_wifi),
    (r"(\d+\.?\d*)\s*\+\s*(\d+\.?\d*)",            _ans_math_add),
    (r"(\d+\.?\d*)\s*\*\s*(\d+\.?\d*)",            _ans_math_mul),
    (r"(\d+\.?\d*)\s*/\s*(\d+\.?\d*)",             _ans_math_div),
    (r"(\d+\.?\d*)\s*-\s*(\d+\.?\d*)",             _ans_math_sub),
    (r"what can you do|your features|help me",      _ans_help),
    (r"\bhi\b|\bhello\b|\bhey\b",                   _ans_greeting),
    (r"\bthank(s| you)\b",                          _ans_thanks),
]
```

**Handler implementations:**
```python
def _ans_time(m, text) -> str:
    now = datetime.datetime.now()
    return f"It's {now.strftime('%I:%M %p')} right now."

def _ans_date(m, text) -> str:
    now = datetime.datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}."

def _ans_battery(m, text) -> str:
    batt = psutil.sensors_battery()
    if batt is None:
        return "Can't read battery — are you on a desktop?"
    pct = int(batt.percent)
    charging = "charging" if batt.power_plugged else "on battery"
    return f"Battery is at {pct}%, {charging}."

def _ans_cpu(m, text) -> str:
    pct = psutil.cpu_percent(interval=0.5)
    return f"CPU is at {pct:.0f}% right now."

def _ans_ram(m, text) -> str:
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024**3)
    total_gb = mem.total / (1024**3)
    return f"RAM: {used_gb:.1f} GB used of {total_gb:.1f} GB ({mem.percent:.0f}%)."

def _ans_wifi(m, text) -> str:
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

def _ans_math_add(m, text) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    result = a + b
    return f"{a} + {b} = {result:g}"

def _ans_math_sub(m, text) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    return f"{a} - {b} = {a - b:g}"

def _ans_math_mul(m, text) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    return f"{a} × {b} = {a * b:g}"

def _ans_math_div(m, text) -> str:
    a, b = float(m.group(1)), float(m.group(2))
    if b == 0:
        return "Can't divide by zero."
    return f"{a} ÷ {b} = {a / b:g}"

def _ans_help(m, text) -> str:
    return (
        "I can: open and close apps, control volume, take screenshots, "
        "lock your screen, check battery/CPU/RAM, tell you the time and date, "
        "set reminders, answer questions via Gemini when online, "
        "and hear you out even when you just need to think aloud."
    )

def _ans_greeting(m, text) -> str:
    import random
    options = [
        "Hey there! What do you need?",
        "Hi! I'm here.",
        "Hello! Go ahead.",
    ]
    return random.choice(options)

def _ans_thanks(m, text) -> str:
    return "Anytime."
```

---

### C.7 — `memory.py` (MODIFY EXISTING — Add Facts Tier)

**Existing functions: UNCHANGED** (`log_exchange`, `get_recent_context`, `_trim_log`)

**New functions to ADD:**

```python
import json
from pathlib import Path
from config import FACTS_FILE

# ── Fact Store ────────────────────────────────────────────────────────────────

def save_fact(key: str, value: str) -> None:
    """
    Persist a user fact (e.g. "user_name" -> "Alice").
    Creates facts.json if absent. Thread-safe via try/except.
    key: lowercase snake_case string
    value: string
    """
    facts = load_all_facts()
    facts[key] = value
    try:
        FACTS_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

def get_fact(key: str, default: str = "") -> str:
    """Return a stored fact or default. Never raises."""
    return load_all_facts().get(key, default)

def load_all_facts() -> dict:
    """Load all facts from facts.json. Returns {} if file missing/corrupt."""
    if not FACTS_FILE.exists():
        return {}
    try:
        return json.loads(FACTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

# ── Fact Extraction (called from route_request before AI) ─────────────────────

_FACT_PATTERNS = [
    # "my name is X" / "I'm X" / "call me X"
    (r"my name is ([A-Za-z]+)", "user_name"),
    (r"call me ([A-Za-z]+)", "user_name"),
    (r"i(?:'m| am) ([A-Za-z]+)", "user_name"),
    # "remember that X"
    (r"remember (?:that )?(.+)", "memory_note"),
]

def extract_and_store_facts(text: str) -> None:
    """
    Scan text for learnable facts and persist them.
    Called before routing to Gemini so facts are captured even from AI queries.
    Never modifies the text — side-effect only.
    """
    import re
    lowered = text.strip().lower()
    for pattern, key in _FACT_PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            value = m.group(1).strip().title() if key == "user_name" else m.group(1).strip()
            save_fact(key, value)
```

**Fact store file format (`facts.json`):**
```json
{
  "user_name": "Alice",
  "preferred_editor": "vscode",
  "memory_note": "last note the user asked to remember"
}
```

---

### C.8 — `scheduler.py` (NEW FILE)

**Purpose:** Parse reminder commands, persist them, trigger them at the right time, show popup + speak.

```python
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

# Callbacks injected by main.py at startup
_on_trigger: Callable[[str], None] = None   # called with reminder text when due

def init(on_trigger: Callable[[str], None]) -> None:
    """
    Call this from main.py after building the Tk root.
    on_trigger: function that shows popup + speaks the reminder text.
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
      - "remind me in N minutes to X"
      - "remind me in N hours to X"
      - "remind me at H:MM [AM/PM] to X"
      - "set a timer for N minutes"
    """
    lowered = text.strip().lower()
    
    # Pattern: "remind me in N minutes/hours to X"
    m = re.search(r"remind me in (\d+) (minute|hour)s? (?:to |about )(.+)", lowered)
    if m:
        n, unit, msg = int(m.group(1)), m.group(2), m.group(3).strip()
        seconds = n * 60 if unit == "minute" else n * 3600
        due = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        _add_reminder(msg, due)
        return f"I'll remind you about '{msg}' in {n} {unit}{'s' if n > 1 else ''}."
    
    # Pattern: "set a timer for N minutes"
    m = re.search(r"(?:set a )?timer (?:for )?(\d+) (minute|hour|second)s?", lowered)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        seconds = n * (60 if unit == "minute" else 3600 if unit == "hour" else 1)
        due = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        _add_reminder(f"Timer: {n} {unit}{'s' if n > 1 else ''} up!", due)
        return f"Timer set for {n} {unit}{'s' if n > 1 else ''}."
    
    # Pattern: "remind me at H:MM [AM/PM] to X"
    m = re.search(r"remind me at (\d{1,2}):(\d{2})\s*(am|pm)?\s*(?:to |about )(.+)", lowered)
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
    """Background thread: checks every 30s, fires due reminders."""
    while True:
        try:
            _check_due()
        except Exception:
            pass
        time.sleep(30)

def _check_due() -> None:
    reminders = _load()
    now = datetime.datetime.now()
    changed = False
    for r in reminders:
        if r["triggered"]:
            continue
        due = datetime.datetime.fromisoformat(r["due"])
        if now >= due:
            r["triggered"] = True
            changed = True
            if _on_trigger:
                _on_trigger(r["message"])
    if changed:
        _save(reminders)
    # Purge triggered reminders older than 24 hours
    cutoff = now - datetime.timedelta(hours=24)
    reminders = [r for r in reminders
                 if not r["triggered"] or datetime.datetime.fromisoformat(r["due"]) > cutoff]
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
```

**Integration in `main.py`:**
```python
# In main() after building root:
import scheduler
scheduler.init(on_trigger=lambda msg: _fire_reminder(msg, root))

def _fire_reminder(msg: str, root):
    """Called from scheduler background thread — must use root.after()."""
    def show():
        if _assistant_window:
            _assistant_window.append_message("System", f"⏰ Reminder: {msg}")
        voice.speak(f"Reminder: {msg}", wait=False)
    root.after(0, show)
```

---

### C.9 — `web_interface.py` (NEW FILE)

**Purpose:** Flask server for remote access from phone/tablet on same Wi-Fi. Disabled by default (`WEB_ENABLED=false`).

```python
"""
DISHA — Remote Web Interface
Runs on 0.0.0.0:WEB_PORT when DISHA_WEB_ENABLED=true.
Provides a simple HTML chat UI + REST API.
Secured by bearer token (DISHA_WEB_TOKEN in .env).
"""
from flask import Flask, request, jsonify, render_template_string, abort
import threading
from config import WEB_PORT, WEB_TOKEN, WEB_ENABLED

_app = Flask(__name__)
_route_fn = None   # injected: callable(str) -> str

def init(route_fn) -> None:
    """
    Call from main.py. route_fn is the same route_request() from main.py.
    Starts the Flask server in a daemon thread if WEB_ENABLED=true.
    """
    global _route_fn
    _route_fn = route_fn
    if WEB_ENABLED:
        t = threading.Thread(target=lambda: _app.run(host="0.0.0.0", port=WEB_PORT, debug=False), daemon=True)
        t.start()

def _check_auth():
    if WEB_TOKEN:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token != WEB_TOKEN:
            abort(401)

@_app.route("/")
def index():
    return render_template_string("""... (HTML chat UI) ...""")

@_app.route("/api/ask", methods=["POST"])
def api_ask():
    _check_auth()
    data = request.get_json(force=True, silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "empty query"}), 400
    response = _route_fn(query)
    return jsonify({"response": response})

@_app.route("/api/status")
def api_status():
    _check_auth()
    import psutil, datetime
    batt = psutil.sensors_battery()
    return jsonify({
        "battery": int(batt.percent) if batt else None,
        "charging": batt.power_plugged if batt else None,
        "time": datetime.datetime.now().isoformat(),
    })
```

**HTML UI template** (inline, minimal, mobile-friendly):
- Single input box + Send button
- Chat log area (scrollable)
- Shows DISHA online status
- Works on mobile browser without any app install
- No JavaScript framework — vanilla JS only

---

### C.10 — `usb_guard.py` (NEW FILE)

**Purpose:** Handle USB portable mode detection and PIN/token verification.

```python
"""
DISHA — USB Guard
When USB_MODE=true in .env, enforces device identity verification.
Generates a device_id.txt on first run. On subsequent runs from USB,
shows a PIN prompt before allowing DISHA to start.
"""
import os
import uuid
import hashlib
import tkinter as tk
from pathlib import Path
from config import USB_MODE, DEVICE_ID_FILE, BASE_DIR

def check_and_verify() -> bool:
    """
    Returns True if OK to proceed, False to abort startup.
    If USB_MODE=false, always returns True immediately.
    If device_id.txt doesn't exist, creates it (first run).
    If it exists, shows PIN prompt — 3 attempts, then 30s lockout.
    PIN is the last 6 chars of the device_id (shown on first run).
    """
    if not USB_MODE:
        return True
    
    if not DEVICE_ID_FILE.exists():
        device_id = str(uuid.uuid4()).replace("-", "").upper()
        DEVICE_ID_FILE.write_text(device_id, encoding="utf-8")
        _show_first_run_dialog(device_id)
        return True
    
    device_id = DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
    pin = device_id[-6:].upper()
    return _show_pin_prompt(pin)

def _show_first_run_dialog(device_id: str) -> None:
    """Show the device ID so the user can note their PIN."""
    root = tk.Tk()
    root.withdraw()
    msg = (f"DISHA Portable Mode — First Run\n\n"
           f"Your PIN is: {device_id[-6:].upper()}\n\n"
           f"You'll need this every time DISHA starts from this drive.\n"
           f"Write it down!")
    tk.messagebox.showinfo("DISHA — First Run", msg)
    root.destroy()

def _show_pin_prompt(correct_pin: str) -> bool:
    """Show PIN entry. 3 attempts. Returns True on success."""
    ...  # Tk Entry dialog, 3 tries, 30s lockout on failure
```

**`DISHA_Launcher.bat` — USB launcher:**
```batch
@echo off
REM DISHA Portable Launcher
REM Detects its own drive letter and launches DISHA from there.

set DRIVE=%~d0
set DISHA_DIR=%DRIVE%\DISHA
set PYTHONW=%DISHA_DIR%\venv\Scripts\pythonw.exe
set MAIN=%DISHA_DIR%\main.py

if not exist "%PYTHONW%" (
    echo DISHA venv not found at %DISHA_DIR%\venv\
    pause
    exit /b 1
)

set DISHA_USB_MODE=true
"%PYTHONW%" "%MAIN%"
```

---

## PART D — DATA FLOWS

### D.1 — Voice Command Flow (Fixed & Complete)

```
User presses Ctrl+Alt+V
        │
        ▼
open_or_focus_assistant(root, mode="voice")
        │
        ▼
DishaAssistantWindow.start_listening()    ← BUG FIXED HERE
        │
        ├─ voice.is_listening() == True? → return (ignore re-trigger)
        │
        ▼
threading.Thread(target=worker, daemon=True).start()
        │
        ▼
voice.listen(on_partial=on_partial_callback)
        │
        ├─ wait_for_tts() first (SAPI speaks before mic opens)
        ├─ adaptive noise gate
        ├─ per-word confidence filter (≥0.80 avg, ≥0.92 single)
        └─ returns transcribed text (or "" if nothing heard)
        │
        ▼
is_exit_command(text)?
    YES → speak("Goodbye!") → close()
        │
       NO
        ▼
route_request(text)
        │
        ├─ app_launcher.try_local_command()  → instant (no network)
        ├─ scheduler.try_schedule_command()  → instant (no network)
        ├─ local_brain.try_answer()          → instant (no network)
        └─ gemini_client.ask()              → network (with is_online() check)
        │
        ▼
append_message("DISHA", answer)    ← updates Text widget
        │
        ▼
voice.speak(answer, wait=False)    ← TTS on background thread
```

### D.2 — Text Command Flow

```
User types query + presses Enter (or clicks Send)
        │
        ▼
DishaAssistantWindow.submit_text()
        │
        ▼
memory.extract_and_store_facts(query)   ← side-effect: learn user facts
        │
        ▼
threading.Thread(target=worker, daemon=True).start()
        │
        ▼
route_request(query)    ← same routing logic as voice
        │
        ▼
append_message("You", query)
append_message("DISHA", answer)
        │
        ▼
voice.speak(answer, wait=False)
```

### D.3 — Wake Word Flow (Phase 2 — when enabled)

```
App starts → WAKE_WORD_ENABLED=true
        │
        ▼
threading.Thread(target=_wake_word_loop, daemon=True).start()
        │
        ▼
_wake_word_loop():
    while not stop_event.is_set():
        open mic (separate Vosk instance, no _listen_lock)
        check partial results for WAKE_WORD text
        confidence >= 0.85?
            YES → root.after(0, lambda: open_or_focus_assistant(root, "voice"))
                  sleep(3.0)  # cooldown — don't re-trigger for 3s
            NO  → continue
```

### D.4 — Reminder Flow

```
App starts → scheduler.init(on_trigger=_fire_reminder)
        │
        ▼
_checker_loop() thread: checks every 30 seconds
        │
        ▼
User says "remind me in 5 minutes to check email"
        │
        ▼
route_request() → scheduler.try_schedule_command() matches
        │
        ▼
_add_reminder("check email", due=now+5min)
→ saved to reminders.json
→ returns "I'll remind you in 5 minutes."
        │
        ▼
[5 minutes later] _checker_loop fires
        │
        ▼
_on_trigger("check email") → root.after(0, show)
        │
        ├─ append_message("System", "⏰ Reminder: check email")
        └─ voice.speak("Reminder: check email")
```

---

## PART E — PHASE EXECUTION PLAN

> [!IMPORTANT]
> Phases are ordered by impact. Do NOT skip or reorder. Each phase ends with acceptance tests — all must pass before the next phase starts.

---

### PHASE 0 — Bugs + Dependencies (Target: 1 session, ~2 hours)

**Goal:** Make the existing app actually run correctly without errors.

#### Step 0.1 — Fix `start_listening` indentation bug in `main.py`
- File: `main.py`
- Action: Move `start_listening` method body out of `focus_text_input` — it should be at the same indent level as `focus_text_input` (class method, not nested function)
- Lines affected: 207–242
- **Do not change any logic** — only fix the indentation/nesting

#### Step 0.2 — Fix Gemini model name
- File: `config.py` line 15
- Change: `"gemini-3.1-flash-lite"` → `"gemini-2.5-flash"`
- Also update `.env`: `GEMINI_MODEL=gemini-2.5-flash`

#### Step 0.3 — Fix `.env` format (remove surrounding quotes from API key)
- File: `.env` line 1
- Current: `GEMINI_API_KEY="sample_key"` (has quotes — causes parse issue)
- Fix: `GEMINI_API_KEY=sample_key` (no quotes)

#### Step 0.4 — Update `requirements.txt` with all needed packages
```
google-generativeai>=0.8.0
python-dotenv>=1.0.0
pystray>=0.19.5
Pillow>=10.0.0
pynput>=1.7.6
vosk>=0.3.45
sounddevice>=0.4.6
pyttsx3>=2.90
numpy>=1.24.0
pywin32>=306
requests>=2.31.0
flask>=3.0.0
psutil>=6.0.0
pyperclip>=1.9.0
fuzzywuzzy>=0.18.0
python-Levenshtein>=0.21.0
schedule>=1.2.0
```

#### Step 0.5 — Install missing packages into venv
```
d:\PROJECTS\disha\venv\Scripts\pip.exe install flask>=3.0.0 psutil>=6.0.0 pyperclip>=1.9.0 fuzzywuzzy python-Levenshtein schedule
```

#### Step 0.6 — Auto-generate icon if missing
- File: `main.py` function `make_icon_image()`
- Already handles missing icon gracefully (line 353–360) ✅ No change needed

#### Step 0.7 — Fix `.gitignore`
```
# Current content:
# .env

# Add these:
venv/
__pycache__/
*.pyc
memory_log.jsonl
facts.json
reminders.json
device_id.txt
assets/icon.png
```

**Phase 0 Acceptance Tests:**
```
✓ TEST 0.A: Run `d:\PROJECTS\disha\venv\Scripts\python.exe main.py` — no Python errors on startup
✓ TEST 0.B: Tray icon appears in system tray
✓ TEST 0.C: Press Ctrl+Alt+D → overlay window appears with text entry
✓ TEST 0.D: Type "hi" in text box + press Enter → DISHA responds (text shown in window)
✓ TEST 0.E: Press Ctrl+Alt+V → 🎤 Listen button activates (no AttributeError)
✓ TEST 0.F: Floating D widget appears on screen
```

---

### PHASE 1 — Core Reliability (Target: 1–2 sessions, ~6 hours)

**Goal:** Chat history persists in session, offline answers work, system controls work.

#### Step 1.1 — Scrollable chat history UI
- File: `main.py` — `_build_ui()` method
- Replace the single `display_label` with a `tk.Text` widget
- Add `append_message(role, text)` method
- Update `start_listening()` worker and `submit_text()` worker to call `append_message` instead of `status_var.set`
- Window size: expand from `500x320` to `520x480`

#### Step 1.2 — Create `local_brain.py`
- New file: `d:\PROJECTS\disha\local_brain.py`
- Full implementation as specified in C.6 above
- Import `psutil` — confirm it was installed in Step 0.5

#### Step 1.3 — Update `route_request` in `main.py`
- Add `import local_brain` and `import scheduler` at top
- Replace 4-line `route_request` with the expanded version in C.2
- Add `memory.extract_and_store_facts(user_input)` call before routing

#### Step 1.4 — Add system commands to `app_launcher.py`
- Add all system command handlers as specified in C.5
- Add `import psutil, re, ctypes, subprocess, pyperclip` at top
- Add `SYSTEM_PATTERNS` list
- Update `try_local_command()` to check system patterns first

#### Step 1.5 — Update `memory.py` — add facts tier
- Add `save_fact`, `get_fact`, `load_all_facts`, `extract_and_store_facts` functions
- Add `import re` and fact pattern list

#### Step 1.6 — Create `scheduler.py`
- New file: `d:\PROJECTS\disha\scheduler.py`
- Full implementation as specified in C.8

#### Step 1.7 — Wire scheduler into `main.py`
- Add `import scheduler` at top
- In `main()`, after `root = tk.Tk()`, add `scheduler.init(on_trigger=lambda msg: _fire_reminder(msg, root))`
- Add `_fire_reminder` function as specified in C.8 integration notes

#### Step 1.8 — Improve STT thresholds in `voice.py`
- Change `MIN_AVG_CONF` default from `0.70` to `0.80`
- Change `SINGLE_WORD_CONF` default from `0.90` to `0.92`
- Change `NO_SPEECH_TIMEOUT` default from `6.0` to `4.0`

#### Step 1.9 — Add visual listening indicator in `main.py`
- In `_build_ui()`: add a small `tk.Label(text="●", fg="#f38ba8")` status dot above the input box
- In `start_listening()`: before starting the thread, set dot visible and red; in the worker on completion, hide the dot
- Use `root.after(0, ...)` for all UI updates from the thread

**Phase 1 Acceptance Tests:**
```
✓ TEST 1.A: Type "what time is it" → local_brain answers with current time (no Gemini call)
✓ TEST 1.B: Type "battery" → shows battery percentage
✓ TEST 1.C: Type "what's my RAM usage" → shows GB used
✓ TEST 1.D: Send multiple messages → all appear in scrollable history
✓ TEST 1.E: Type "open chrome" → Chrome opens, message appears in history
✓ TEST 1.F: Type "take a screenshot" → screenshot saved to Desktop, path shown
✓ TEST 1.G: Type "remind me in 1 minute to test reminder" → confirmation shown, 60s later reminder fires
✓ TEST 1.H: Turn off Wi-Fi → type any question → DISHA responds with offline answer or graceful message (no hang)
```

---

### PHASE 2 — Productivity Features (Target: 2–3 sessions, ~10 hours)

**Goal:** Wake word, clipboard awareness, dynamic app discovery, streaming AI responses.

#### Step 2.1 — Wake word listener
- File: `voice.py` — add `listen_for_wake_word(callback, stop_event)` and `set_root(root)`
- File: `main.py` — add `_start_wake_word_thread(root)` function
- Only starts if `WAKE_WORD_ENABLED=true` in `.env`

#### Step 2.2 — Clipboard reading
- File: `app_launcher.py` — `_cmd_read_clipboard` uses `pyperclip.paste()`
- Add pattern `r"what did i (just )?copy|clipboard"` to `SYSTEM_PATTERNS`

#### Step 2.3 — Dynamic app discovery
- File: `app_launcher.py` — add `_discover_installed_apps() -> dict` function
- Scans `C:\ProgramData\Microsoft\Windows\Start Menu` and `%APPDATA%\Microsoft\Windows\Start Menu` for `.lnk` files
- Caches result in module variable `_discovered_apps: dict | None = None` (only scans once per session)
- `_launch_app` checks `APP_COMMANDS` first, then `_discovered_apps`, then uses fuzzy match via `fuzzywuzzy`

#### Step 2.4 — Streaming AI responses
- File: `gemini_client.py` — implement `ask_streaming(prompt, context, on_chunk)`
- File: `main.py` — in `start_listening()` worker: use `ask_streaming` with `on_chunk=lambda t: append_message_update(t)`
- Add `append_message_update(partial_text)` to `DishaAssistantWindow` — updates the last DISHA message in place as tokens stream in

#### Step 2.5 — Personality personalisation using facts
- File: `gemini_client.py` `ask()` — prepend known facts to system prompt:
```python
user_name = memory.get_fact("user_name", "")
fact_context = f"User's name: {user_name}. " if user_name else ""
full_system = fact_context + SYSTEM_PROMPT
```

**Phase 2 Acceptance Tests:**
```
✓ TEST 2.A: Set DISHA_WAKE_WORD=true, say "hey disha" → overlay opens without pressing hotkey
✓ TEST 2.B: Copy text to clipboard, say "what did I just copy" → DISHA reads it back
✓ TEST 2.C: Say "open spotify" (not in APP_COMMANDS) → DISHA finds it via dynamic discovery and opens it
✓ TEST 2.D: Ask a long question to Gemini → response text streams in word by word
✓ TEST 2.E: Say "my name is Alice" → facts.json updated; next greeting uses the name
```

---

### PHASE 3 — Portability + Remote Access (Target: 2 sessions, ~6 hours)

**Goal:** Works from USB drive with verification, accessible from phone.

#### Step 3.1 — Create `usb_guard.py`
- Full implementation as specified in C.10
- Tkinter PIN dialog: show `tk.Toplevel` with masked `Entry` widget, 3 attempts, then `time.sleep(30)` lockout

#### Step 3.2 — Create `DISHA_Launcher.bat`
- Root of the project: `d:\PROJECTS\disha\DISHA_Launcher.bat`
- Detects drive letter from `%~d0`
- Sets `DISHA_USB_MODE=true` as env var before launch
- Calls `venv\Scripts\pythonw.exe main.py`

#### Step 3.3 — Verify all paths are relative
- Audit every Path reference in all files — must all use `BASE_DIR` or `Path(__file__).resolve().parent`
- `model/`, `assets/`, `memory_log.jsonl`, `facts.json`, `reminders.json` — all relative to `BASE_DIR`

#### Step 3.4 — Create `web_interface.py`
- Full implementation as specified in C.9
- HTML template inlined as Python string (no external template files)
- Flask runs in daemon thread — does not block main Tk loop

#### Step 3.5 — Wire web interface into `main.py`
```python
# In main() after building route_request:
import web_interface
web_interface.init(route_fn=route_request)
```

#### Step 3.6 — Add startup notification of web URL
- If `WEB_ENABLED=true`: after Flask starts, `voice.speak(f"Web interface ready on port {WEB_PORT}.")`
- Show local IP in tray tooltip: use `socket.gethostbyname(socket.gethostname())`

**Phase 3 Acceptance Tests:**
```
✓ TEST 3.A: Set DISHA_USB_MODE=true, restart → PIN dialog appears before DISHA loads
✓ TEST 3.B: Enter wrong PIN 3 times → 30s lockout, then allowed to try again
✓ TEST 3.C: Set DISHA_WEB_ENABLED=true → open browser to http://localhost:5000 → chat UI loads
✓ TEST 3.D: POST to /api/ask with {"query": "what time is it"} → returns JSON with time
✓ TEST 3.E: Access /api/ask from phone on same Wi-Fi (using local IP) → works
✓ TEST 3.F: Copy entire disha folder to another path, change BASE_DIR, run → no path errors
```

---

### PHASE 4 — Local LLM + Intelligence (Month 2+, after Phases 0–3 stable)

> [!NOTE]
> Phase 4 requires installing Ollama separately. Do NOT start this phase until Phases 0–3 are fully tested and stable.

#### Step 4.1 — Install Ollama
- Download from https://ollama.ai/download (Windows installer)
- After install: `ollama pull phi3.5` (2.7GB — fits in 16GB RAM with headroom)
- Verify: `ollama run phi3.5 "Hello"` responds

#### Step 4.2 — Create `local_llm.py`
```python
"""
DISHA — Local LLM via Ollama
Wraps Ollama's REST API for offline AI reasoning.
Only used when is_online() returns False.
"""
import requests
from config import SYSTEM_PROMPT

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3.5"   # or "llama3.2:1b" for faster responses

def ask_local(prompt: str, context: str = "") -> str:
    """Call Ollama. Returns response text. Falls back to rule message on failure."""
    try:
        full_prompt = f"{SYSTEM_PROMPT}\n\n{context}\n\nUser: {prompt}\nDISHA:"
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 150}
        }, timeout=30)
        data = resp.json()
        return data.get("response", "").strip()
    except Exception:
        return "I'm offline and my local brain isn't available right now."
```

#### Step 4.3 — Update `gemini_client.py` to route offline to local LLM
```python
def ask(prompt: str, context: str = "") -> str:
    if not GEMINI_API_KEY:
        return "No API key configured."
    if not is_online():
        import local_llm
        return local_llm.ask_local(prompt, context)   # ← NEW offline path
    # ... existing Gemini call ...
```

#### Step 4.4 — Screen awareness (screenshot + Gemini Vision)
```python
def ask_with_screenshot(prompt: str) -> str:
    """Take screenshot, send to Gemini Vision with the prompt."""
    from PIL import ImageGrab
    img = ImageGrab.grab()
    # Convert to bytes and send via Gemini multimodal API
```

---

## PART F — COMPLETE `requirements.txt`

```
# DISHA v2 — complete dependency list
# Install: pip install -r requirements.txt

# Core AI
google-generativeai>=0.8.0

# Environment
python-dotenv>=1.0.0

# UI
pystray>=0.19.5
Pillow>=10.0.0
pynput>=1.7.6

# Voice
vosk>=0.3.45
sounddevice>=0.4.6
pyttsx3>=2.90

# System
pywin32>=306
numpy>=1.24.0
psutil>=6.0.0

# Utilities
requests>=2.31.0
pyperclip>=1.9.0
fuzzywuzzy>=0.18.0
python-Levenshtein>=0.21.0
schedule>=1.2.0

# Remote interface
flask>=3.0.0
```

---

## PART G — `.env` Complete Template

```env
# DISHA v2 — Environment Configuration
# Copy to .env and fill in your values

# ── AI ──────────────────────────────────
GEMINI_API_KEY=your_real_api_key_here_no_quotes
GEMINI_MODEL=gemini-2.5-flash

# ── Hotkeys ─────────────────────────────
DISHA_HOTKEY=<ctrl>+<alt>+d
DISHA_VOICE_HOTKEY=<ctrl>+<alt>+v

# ── Voice ───────────────────────────────
DISHA_TTS_ENABLED=true
DISHA_TTS_RATE=175
DISHA_TTS_VOICE=female
DISHA_SILENCE_STOP=1.4
DISHA_VOICE_DEBUG=0

# ── Wake Word (off by default) ───────────
DISHA_WAKE_WORD=false
DISHA_WAKE_PHRASE=hey disha

# ── Memory ──────────────────────────────
DISHA_MEMORY_MAX=20

# ── Remote Web (off by default) ──────────
DISHA_WEB_ENABLED=false
DISHA_WEB_PORT=5000
DISHA_WEB_TOKEN=changeme_set_a_strong_token

# ── USB Portable Mode (off by default) ───
DISHA_USB_MODE=false
```

---

## PART H — KNOWN CONSTRAINTS & LIMITS

| Constraint | Impact | Mitigation |
|-----------|--------|-----------|
| venv Python is 3.10 (system Python is 3.12) | Must use 3.10-compatible syntax | No walrus operator abuse, no 3.11+ features |
| No `pycaw` in venv | Exact volume control not available | Use PowerShell WScript.Shell key-send (approximate) |
| No `ollama` CLI installed | Phase 4 blocked | Phase 4 starts with Ollama install as prerequisite |
| Vosk model is full (not small) | ~70MB cold load time ~3–5s | Load model at startup (not on first voice press) |
| Tkinter single-threaded | All UI updates via `root.after(0, ...)` | Already enforced — never call widget methods from daemon threads |
| SAPI5 voice is robotic | Not fixable without SAPI5 alternative | Phase 4+: consider `edge-tts` (Microsoft Edge TTS via subprocess) |
| Gemini API rate limits | Free tier: 15 RPM | Rate limiter not needed for personal use |

---

## PART I — ANTI-DRIFT AGENT CHECKLIST

Run this checklist at the START of every coding session:

```
□ I have read the goal sentence (Part A, line 1 of the blueprint)
□ I know which phase I am implementing
□ I have confirmed the phase's prerequisite phase is complete
□ I am only modifying files listed in this phase's steps
□ I am not adding any library not listed in Part A or Part F
□ I am not using absolute paths (checking for BASE_DIR usage)
□ I am not blocking the Tk thread (checking for daemon=True threads)
□ All new functions have a docstring stating: purpose, returns, never-does
□ After implementing, I will run the phase's acceptance tests before stopping
```

---

## PART J — SESSION HANDOFF FORMAT

At the end of every coding session, the agent must write this summary:

```
SESSION SUMMARY — [Date] [Phase X]
Completed steps: [list step numbers]
Files modified: [list files]
Tests passed: [list test IDs]
Tests failed: [list with reason]
Next session must start with: [step number and file]
Open issues: [any blockers]
```

This ensures the next session doesn't duplicate work or drift from context.
