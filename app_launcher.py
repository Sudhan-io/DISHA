"""
DISHA - Local App Launcher & System Controls
Fully offline command routing. Checked BEFORE Gemini is ever called, so
app launches and system actions are instant and work with no internet.
Only unrecognized input falls through to Gemini.
"""

import os
import re
import ctypes
import subprocess
import datetime
from pathlib import Path
from typing import Optional, Callable

import psutil
import pyperclip
from PIL import ImageGrab
from fuzzywuzzy import process, fuzz

from config import APP_COMMANDS

_discovered_apps: Optional[dict[str, str]] = None

OPEN_TRIGGERS = ("open ", "launch ", "start ")
CLOSE_TRIGGERS = ("close ", "quit ", "kill ")


# ── System Command Handlers ───────────────────────────────────────────────────

def _cmd_set_volume(match) -> str:
    level = int(match.group(1))
    level = max(0, min(100, level))
    subprocess.run(
        [
            "powershell", "-Command",
            f"$obj = New-Object -ComObject WScript.Shell; "
            f"1..50 | ForEach-Object {{ $obj.SendKeys([char]174) }}; "
            f"$steps = [Math]::Round({level} / 2); "
            f"1..$steps | ForEach-Object {{ $obj.SendKeys([char]175) }}"
        ],
        capture_output=True,
        shell=False,
    )
    return f"Volume set to approximately {level}%."


def _cmd_volume_change(match) -> str:
    direction = match.group(1)
    key_char = 175 if direction == "up" else 174
    subprocess.run(
        [
            "powershell", "-Command",
            f"$obj = New-Object -ComObject WScript.Shell; "
            f"1..5 | ForEach-Object {{ $obj.SendKeys([char]{key_char}) }}"
        ],
        capture_output=True,
        shell=False,
    )
    return f"Volume turned {direction}."


def _cmd_mute_toggle(match) -> str:
    subprocess.run(
        [
            "powershell", "-Command",
            "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]173)"
        ],
        capture_output=True,
        shell=False,
    )
    return "Toggled mute."


def _cmd_screenshot(match) -> str:
    desktop = Path.home() / "Desktop"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = desktop / f"screenshot_{timestamp}.png"
    try:
        img = ImageGrab.grab()
        img.save(filepath)
        return f"Screenshot saved to Desktop: {filepath.name}."
    except Exception as e:
        ps_cmd = (
            f"Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            f"$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            f"$b = New-Object System.Drawing.Bitmap $s.Width, $s.Height; "
            f"$g = [System.Drawing.Graphics]::FromImage($b); "
            f"$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size); "
            f"$b.Save('{filepath}'); "
            f"$g.Dispose(); $b.Dispose()"
        )
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
        if filepath.exists():
            return f"Screenshot saved to Desktop: {filepath.name}."
        return f"Couldn't take screenshot: {e}"


def _cmd_lock_screen(match) -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Screen locked."


def _cmd_shutdown(match) -> str:
    subprocess.run(["shutdown", "/s", "/t", "60"])
    return "Shutdown scheduled in 60 seconds. Say 'abort shutdown' to cancel."


def _cmd_abort_shutdown(match) -> str:
    subprocess.run(["shutdown", "/a"])
    return "Shutdown cancelled."


def _cmd_restart(match) -> str:
    subprocess.run(["shutdown", "/r", "/t", "60"])
    return "Restart scheduled in 60 seconds. Say 'abort shutdown' to cancel."


def _cmd_sleep(match) -> str:
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Putting computer to sleep."


def _cmd_battery(match) -> str:
    batt = psutil.sensors_battery()
    if batt is None:
        return "Can't read battery status."
    pct = int(batt.percent)
    state = "charging" if batt.power_plugged else "on battery"
    return f"Battery is at {pct}%, {state}."


def _cmd_read_clipboard(match) -> str:
    try:
        content = pyperclip.paste().strip()
        if not content:
            return "Clipboard is empty."
        if len(content) > 120:
            content = content[:117] + "..."
        return f"Clipboard: {content}"
    except Exception as e:
        return f"Couldn't read clipboard: {e}"


def _cmd_cpu_usage(match) -> str:
    pct = psutil.cpu_percent(interval=0.5)
    return f"CPU usage is at {pct:.0f}%."


def _cmd_ram_usage(match) -> str:
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024**3)
    total_gb = mem.total / (1024**3)
    return f"RAM: {used_gb:.1f} GB used of {total_gb:.1f} GB ({mem.percent:.0f}%)."


def _cmd_wifi_name(match) -> str:
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":", 1)[-1].strip()
                return f"Connected to Wi-Fi '{ssid}'."
        return "Not connected to any Wi-Fi network."
    except Exception:
        return "Can't read Wi-Fi info right now."


def _cmd_open_downloads(match) -> str:
    os.startfile(Path.home() / "Downloads")
    return "Opening Downloads."


def _cmd_open_documents(match) -> str:
    os.startfile(Path.home() / "Documents")
    return "Opening Documents."


def _cmd_open_desktop(match) -> str:
    os.startfile(Path.home() / "Desktop")
    return "Opening Desktop."


def _cmd_empty_bin(match) -> str:
    try:
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7)
        return "Recycle bin emptied."
    except Exception as e:
        return f"Couldn't empty recycle bin: {e}"


# ── System command patterns ───────────────────────────────────────────────────
SYSTEM_PATTERNS: list[tuple[str, Callable]] = [
    (r"abort shutdown|cancel shutdown", _cmd_abort_shutdown),
    (r"set volume to (\d+)", _cmd_set_volume),
    (r"volume (up|down)", _cmd_volume_change),
    (r"\b(mute|unmute)\b", _cmd_mute_toggle),
    (r"(take|grab) (a )?screenshot", _cmd_screenshot),
    (r"lock (my )?(screen|computer|pc)", _cmd_lock_screen),
    (r"(shutdown|shut down|turn off)", _cmd_shutdown),
    (r"\b(restart|reboot)\b", _cmd_restart),
    (r"\b(sleep|hibernate)\b", _cmd_sleep),
    (r"\b(battery|charge|power status)\b", _cmd_battery),
    (r"what did i (just )?copy|clipboard", _cmd_read_clipboard),
    (r"(cpu|processor) usage", _cmd_cpu_usage),
    (r"(ram|memory) usage", _cmd_ram_usage),
    (r"(wifi|network|internet) (name|ssid)", _cmd_wifi_name),
    (r"open (my )?downloads", _cmd_open_downloads),
    (r"open (my )?documents", _cmd_open_documents),
    (r"open (my )?desktop", _cmd_open_desktop),
    (r"empty (recycle )?bin", _cmd_empty_bin),
]


def try_local_command(text: str) -> Optional[str]:
    """
    If `text` matches a system action or known local app, execute it
    and return a confirmation string. Returns None if nothing matched.
    """
    lowered = text.strip().lower()

    # Check system commands FIRST (higher priority than generic app names)
    for pattern, handler in SYSTEM_PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            try:
                return handler(m)
            except Exception as e:
                return f"Couldn't do that: {e}"

    # Then check app open/close triggers
    for trigger in OPEN_TRIGGERS:
        if lowered.startswith(trigger):
            app_name = lowered[len(trigger):].strip()
            return _launch_app(app_name)

    for trigger in CLOSE_TRIGGERS:
        if lowered.startswith(trigger):
            app_name = lowered[len(trigger):].strip()
            return _close_app(app_name)

    return None


def _discover_installed_apps() -> dict[str, str]:
    """
    Scan Windows Start Menu directories for .lnk shortcuts.
    Returns mapping of lowercase app name -> path to .lnk file.
    Cached after first run.
    """
    global _discovered_apps
    if _discovered_apps is not None:
        return _discovered_apps

    apps: dict[str, str] = {}
    search_dirs = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" if os.environ.get("APPDATA") else None,
    ]

    for s_dir in search_dirs:
        if s_dir and s_dir.exists():
            try:
                for lnk in s_dir.rglob("*.lnk"):
                    stem_name = lnk.stem.lower().strip()
                    if "uninstall" in stem_name or "remove" in stem_name:
                        continue
                    apps[stem_name] = str(lnk.resolve())
            except Exception:
                pass

    _discovered_apps = apps
    return _discovered_apps


def _launch_app(app_name: str) -> Optional[str]:
    # 1. Curated APP_COMMANDS first
    command = APP_COMMANDS.get(app_name)
    if command:
        try:
            subprocess.Popen(command, shell=True)
            return f"Opening {app_name}."
        except OSError as e:
            return f"Couldn't open {app_name}: {e}"

    # 2. Dynamic discovered apps (exact match)
    discovered = _discover_installed_apps()
    if app_name in discovered:
        target = discovered[app_name]
        try:
            os.startfile(target)
            return f"Opening {app_name}."
        except Exception as e:
            return f"Couldn't open {app_name}: {e}"

    # 3. Fuzzy matching across discovered apps + curated commands
    all_candidates = list(APP_COMMANDS.keys()) + list(discovered.keys())
    if all_candidates:
        match, score = process.extractOne(app_name, all_candidates, scorer=fuzz.ratio)
        if score >= 75:
            if match in APP_COMMANDS:
                cmd = APP_COMMANDS[match]
                try:
                    subprocess.Popen(cmd, shell=True)
                    return f"Opening {match}."
                except OSError as e:
                    return f"Couldn't open {match}: {e}"
            elif match in discovered:
                target = discovered[match]
                try:
                    os.startfile(target)
                    return f"Opening {match}."
                except Exception as e:
                    return f"Couldn't open {match}: {e}"

    return None


def _close_app(app_name: str) -> Optional[str]:
    command = APP_COMMANDS.get(app_name)
    exe_guess = None
    if command:
        exe_guess = command if command.endswith(".exe") else f"{command}.exe"
    else:
        # Check discovered apps
        discovered = _discover_installed_apps()
        if app_name in discovered:
            exe_guess = f"{Path(discovered[app_name]).stem}.exe"
        else:
            all_candidates = list(APP_COMMANDS.keys()) + list(discovered.keys())
            if all_candidates:
                match, score = process.extractOne(app_name, all_candidates, scorer=fuzz.ratio)
                if score >= 75:
                    if match in APP_COMMANDS:
                        c = APP_COMMANDS[match]
                        exe_guess = c if c.endswith(".exe") else f"{c}.exe"
                    elif match in discovered:
                        exe_guess = f"{Path(discovered[match]).stem}.exe"

    if not exe_guess:
        return None

    try:
        subprocess.run(
            ["taskkill", "/IM", exe_guess, "/F"],
            shell=False,
            capture_output=True,
        )
        return f"Closed {app_name}."
    except OSError as e:
        return f"Couldn't close {app_name}: {e}"
