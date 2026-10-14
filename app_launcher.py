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

def _set_volume_pycaw(level: int) -> bool:
    try:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        if speakers and hasattr(speakers, "volume_percent"):
            speakers.volume_percent = float(level)
            return True
        elif speakers and hasattr(speakers, "EndpointVolume"):
            speakers.EndpointVolume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return True
    except Exception:
        pass
    return False


def _cmd_set_volume(match) -> str:
    level = int(match.group(1))
    level = max(0, min(100, level))
    if _set_volume_pycaw(level):
        return f"Volume set to {level}%."
    # Fast fallback: VK_VOLUME keys
    steps = int(level / 2)
    for _ in range(50):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
    return f"Volume set to approximately {level}%."


def _cmd_volume_change(match) -> str:
    direction = match.group(1)
    delta = 10 if direction == "up" else -10
    try:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        if speakers and hasattr(speakers, "volume_percent"):
            curr = speakers.volume_percent
            target = max(0.0, min(100.0, curr + delta))
            speakers.volume_percent = target
            return f"Volume turned {direction} to {int(target)}%."
    except Exception:
        pass
    # Fast fallback: 5 key taps via ctypes
    vk = 0xAF if direction == "up" else 0xAE
    for _ in range(5):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    return f"Volume turned {direction}."


def _cmd_mute_toggle(match) -> str:
    try:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        if speakers and hasattr(speakers, "EndpointVolume"):
            is_muted = speakers.EndpointVolume.GetMute()
            speakers.EndpointVolume.SetMute(0 if is_muted else 1, None)
            return "Unmuted volume." if is_muted else "Muted volume."
    except Exception:
        pass
    # Fast fallback: VK_VOLUME_MUTE
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
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


_last_wifi_check = 0.0
_cached_wifi_str = ""


def _cmd_cpu_usage(match) -> str:
    pct = psutil.cpu_percent(interval=None)
    return f"CPU usage is at {pct:.0f}%."


def _cmd_ram_usage(match) -> str:
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024**3)
    total_gb = mem.total / (1024**3)
    return f"RAM: {used_gb:.1f} GB used of {total_gb:.1f} GB ({mem.percent:.0f}%)."


def _cmd_wifi_name(match) -> str:
    global _last_wifi_check, _cached_wifi_str
    import time
    now = time.monotonic()
    if _cached_wifi_str and (now - _last_wifi_check) < 5.0:
        return _cached_wifi_str

    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                ssid = line.split(":", 1)[-1].strip()
                _cached_wifi_str = f"Connected to Wi-Fi '{ssid}'."
                _last_wifi_check = now
                return _cached_wifi_str
        _cached_wifi_str = "Not connected to any Wi-Fi network."
        _last_wifi_check = now
        return _cached_wifi_str
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


BUILTIN_PROTOCOLS: dict[str, str] = {
    "calculator": "calculator:",
    "calc": "calculator:",
    "paint": "ms-paint:",
    "mspaint": "ms-paint:",
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
    "bluetooth": "ms-settings:bluetooth",
    "bluetooth settings": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "wifi settings": "ms-settings:network-wifi",
    "network settings": "ms-settings:network",
    "sound settings": "ms-settings:sound",
    "display settings": "ms-settings:display",
    "store": "ms-windows-store:",
    "windows store": "ms-windows-store:",
    "microsoft store": "ms-windows-store:",
    "spotify": "spotify:",
}

COMMON_WEBSITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://www.github.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "whatsapp": "https://web.whatsapp.com",
    "leetcode": "https://leetcode.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "wikipedia": "https://www.wikipedia.org",
    "browser": "https://www.google.com",
    "web browser": "https://www.google.com",
}

APP_ALIASES: dict[str, str] = {
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "google chrome": "chrome",
    "command prompt": "cmd",
    "windows terminal": "wt",
    "terminal": "wt",
    "file explorer": "explorer",
    "files": "explorer",
    "task manager": "taskmgr",
    "microsoft edge": "msedge",
    "edge": "msedge",
    "brave browser": "brave",
}

PROCESS_ALIASES: dict[str, list[str]] = {
    "calculator": ["CalculatorApp.exe", "calc.exe"],
    "calc": ["CalculatorApp.exe", "calc.exe"],
    "notepad": ["Notepad.exe", "notepad.exe"],
    "paint": ["mspaint.exe", "PaintApp.exe"],
    "terminal": ["WindowsTerminal.exe", "wt.exe"],
    "windows terminal": ["WindowsTerminal.exe", "wt.exe"],
    "command prompt": ["cmd.exe"],
    "cmd": ["cmd.exe"],
    "vscode": ["Code.exe"],
    "vs code": ["Code.exe"],
    "visual studio code": ["Code.exe"],
    "code": ["Code.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "brave": ["brave.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "discord": ["Discord.exe"],
    "spotify": ["Spotify.exe"],
    "word": ["WINWORD.EXE"],
    "excel": ["EXCEL.EXE"],
    "powerpoint": ["POWERPNT.EXE"],
}

PROTECTED_PROCESSES = {
    "explorer.exe", "svchost.exe", "csrss.exe", "lsass.exe",
    "smss.exe", "winlogon.exe", "services.exe", "system.exe", "idle.exe"
}


def _discover_installed_apps() -> dict[str, str]:
    """
    Comprehensive app discovery across Windows:
    1. Start Menu shortcuts (.lnk) in ProgramData and AppData
    2. Desktop shortcuts (.lnk) in User and Public Desktop
    3. Windows Registry App Paths (HKLM and HKCU)
    4. System PATH fallback binaries
    Returns dictionary mapping lowercase app name -> launchable target.
    """
    global _discovered_apps
    if _discovered_apps is not None:
        return _discovered_apps

    apps: dict[str, str] = {}

    # 1. Start menu & Desktop shortcuts (.lnk)
    search_dirs = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" if os.environ.get("APPDATA") else None,
        Path(os.environ.get("USERPROFILE", "")) / "Desktop" if os.environ.get("USERPROFILE") else None,
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]

    # Helper to resolve shortcut target via WScript.Shell
    wscript = None
    try:
        import win32com.client
        wscript = win32com.client.Dispatch("WScript.Shell")
    except Exception:
        pass

    for s_dir in search_dirs:
        if s_dir and s_dir.exists():
            try:
                for lnk in s_dir.rglob("*.lnk"):
                    stem = lnk.stem.lower().strip()
                    if "uninstall" in stem or "remove" in stem:
                        continue
                    lnk_path = str(lnk.resolve())
                    apps[stem] = lnk_path

                    # Also inspect real target .exe if possible
                    target_exe = None
                    if wscript:
                        try:
                            sc = wscript.CreateShortcut(lnk_path)
                            if sc.TargetPath and os.path.exists(sc.TargetPath):
                                target_exe = sc.TargetPath
                                exe_name = Path(target_exe).name.lower()
                                exe_stem = Path(target_exe).stem.lower()
                                apps[exe_stem] = lnk_path
                                # Register process alias for closing
                                if stem not in PROCESS_ALIASES:
                                    PROCESS_ALIASES[stem] = [exe_name]
                        except Exception:
                            pass

                    # 1. Clean parenthesized noise: "Sekiro (ArtBook and OST)" -> "Sekiro"
                    clean_stem = re.sub(r"\s*\([^)]*\)", "", stem).strip()
                    if clean_stem:
                        apps[clean_stem] = lnk_path

                    # 2. Strip technical bitness: "PotPlayer 64 bit" -> "PotPlayer"
                    no_bits = re.sub(r"\s*(?:64[\s-]*bit|32[\s-]*bit|x64|x86|\(x64\)|\(x86\))\b", "", clean_stem, flags=re.I).strip()
                    if no_bits:
                        apps[no_bits] = lnk_path

                    # 3. Strip generic suffixes: "Epic Games Launcher" -> "Epic Games"
                    no_launcher = re.sub(r"\s*(?:launcher|client|edition|game|app)\b", "", no_bits, flags=re.I).strip()
                    if no_launcher:
                        apps[no_launcher] = lnk_path
                        if no_launcher == "epic games":
                            apps["epic"] = lnk_path

                    # 4. Split subtitles after hyphen / colon: "Sekiro - Shadows Die Twice" -> "Sekiro"
                    main_title = re.split(r"[-:–—]", no_launcher)[0].strip()
                    if main_title and len(main_title) >= 3:
                        apps[main_title] = lnk_path

                    # 5. Common multi-word stems: "MSI Afterburner" -> "Afterburner"
                    if " " in no_bits:
                        last_word = no_bits.split()[-1]
                        if len(last_word) >= 4 and last_word not in apps:
                            apps[last_word] = lnk_path
            except Exception:
                pass

    # 2. Windows Registry App Paths (HKCU and HKLM)
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                    subkeys, _, _ = winreg.QueryInfoKey(key)
                    for i in range(subkeys):
                        name = winreg.EnumKey(key, i)
                        try:
                            with winreg.OpenKey(key, name) as subkey:
                                val, _ = winreg.QueryValueEx(subkey, "")
                                if val and (os.path.exists(val) or Path(val).exists()):
                                    clean = name.lower().strip()
                                    apps[clean] = val
                                    if clean.endswith(".exe"):
                                        apps[clean[:-4]] = val
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

    # 3. System PATH fallback binaries
    import shutil
    for sys_bin in ("calc", "notepad", "cmd", "explorer", "taskmgr", "wt", "code", "powershell"):
        which = shutil.which(sys_bin) or shutil.which(f"{sys_bin}.exe")
        if which and sys_bin not in apps:
            apps[sys_bin] = which

    _discovered_apps = apps
    return _discovered_apps


def _launch_target(target: str) -> bool:
    """
    Launch target via native Windows ShellExecute (os.startfile) or cmd.exe start with elevation fallback.
    Guarantees elevated apps (e.g. MSI Afterburner), shortcuts (.lnk), URLs, and protocols launch reliably.
    """
    try:
        os.startfile(target)
        return True
    except Exception:
        pass

    # Subprocess fallback via cmd /c start (handles UAC elevation prompts & .lnk execution)
    try:
        subprocess.Popen(f'cmd.exe /c start "" "{target}"', shell=True)
        return True
    except Exception:
        pass

    try:
        if Path(target).exists():
            subprocess.Popen([target], shell=False)
            return True
    except Exception:
        pass

    return False


def _clean_input(text: str) -> str:
    """Normalize speech-to-text artifacts: strip commas, quotes, hyphens, colons, and wake words."""
    cleaned = re.sub(r"[,;:\-\"'`~]", " ", text).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(".!? ")
    # Strip leading assistant names / wake words
    cleaned = re.sub(r"^(?:hey\s+disha|disha|ok\s+disha|okay\s+disha)\s*", "", cleaned).strip()
    return cleaned


def _extract_app_action(text: str) -> Optional[tuple[str, str]]:
    """
    Extract action ('open' or 'close') and target app from natural phrasing.
    Resilient to Whisper commas, punctuation, and speech artifacts.
    Supports prefixes like 'can you open', 'please open', 'go to', 'open up', 'fire up', etc.
    """
    cleaned = _clean_input(text)

    # 1. Open action pattern
    open_regex = re.compile(
        r"^(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+)?"
        r"(?:open|launch|start|run|bring\s+up|fire\s+up|go\s+to|goto|go)"
        r"(?:\s+up|\s+the|\s+my|\s+app|\s+application)*\s+"
        r"(.+?)"
        r"(?:\s+please|\s+for\s+me|\s+now|\s+app|\s+application)*$",
        re.IGNORECASE
    )
    m_open = open_regex.match(cleaned)
    if m_open:
        target = m_open.group(1).strip()
        target = re.sub(r"^(?:the|my|up|app)\s+", "", target).strip()
        target = re.sub(r"[,;:\-\"'`~.!?]", "", target).strip()
        if target:
            return ("open", target)

    # 2. Close action pattern
    close_regex = re.compile(
        r"^(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+)?"
        r"(?:close|quit|kill|exit|terminate|shut\s+down)"
        r"(?:\s+the|\s+my|\s+app|\s+application)*\s+"
        r"(.+?)"
        r"(?:\s+please|\s+for\s+me|\s+now|\s+app|\s+application)*$",
        re.IGNORECASE
    )
    m_close = close_regex.match(cleaned)
    if m_close:
        target = m_close.group(1).strip()
        target = re.sub(r"^(?:the|my|app)\s+", "", target).strip()
        target = re.sub(r"[,;:\-\"'`~.!?]", "", target).strip()
        if target:
            return ("close", target)

    return None


def _launch_app(app_name: str) -> Optional[str]:
    """
    Resolve and launch an application, shortcut, system protocol, or website.
    """
    clean_name = app_name.strip().lower().rstrip(".!?")
    if not clean_name:
        return None

    # 1. Direct Web URLs
    if clean_name.startswith("http://") or clean_name.startswith("https://"):
        if _launch_target(clean_name):
            return f"Opening {clean_name}."
    elif clean_name.startswith("www.") or any(clean_name.endswith(tld) for tld in (".com", ".org", ".net", ".io", ".co", ".app", ".dev", ".edu", ".in")):
        url = f"https://{clean_name}"
        if _launch_target(url):
            return f"Opening {clean_name}."

    # 2. Built-in Protocols (Calculator, Settings, Paint, Spotify)
    proto = BUILTIN_PROTOCOLS.get(clean_name)
    if proto and _launch_target(proto):
        return f"Opening {app_name}."

    # 3. Common Websites
    site = COMMON_WEBSITES.get(clean_name)
    if site and _launch_target(site):
        return f"Opening {clean_name.title()}."

    # 4. Aliased match
    aliased = APP_ALIASES.get(clean_name, clean_name)
    if aliased != clean_name:
        proto = BUILTIN_PROTOCOLS.get(aliased)
        if proto and _launch_target(proto):
            return f"Opening {app_name}."
        site = COMMON_WEBSITES.get(aliased)
        if site and _launch_target(site):
            return f"Opening {aliased.title()}."

    # 5. Discovered Apps (Registry App Paths + Start Menu + Desktop + PATH)
    discovered = _discover_installed_apps()
    for candidate_key in (clean_name, aliased):
        if candidate_key in discovered:
            target = discovered[candidate_key]
            if _launch_target(target):
                return f"Opening {app_name}."

    # 6. Curated APP_COMMANDS
    cmd = APP_COMMANDS.get(clean_name) or APP_COMMANDS.get(aliased)
    if cmd:
        if cmd in BUILTIN_PROTOCOLS and _launch_target(BUILTIN_PROTOCOLS[cmd]):
            return f"Opening {app_name}."
        if _launch_target(cmd):
            return f"Opening {app_name}."

    # 7. Fuzzy matching against all candidate keys (token_set_ratio + ratio)
    all_candidates = list(discovered.keys()) + list(COMMON_WEBSITES.keys()) + list(BUILTIN_PROTOCOLS.keys()) + list(APP_ALIASES.keys())
    if all_candidates:
        # Check token_set_ratio first (e.g. "potplayer" matches "potplayer 64 bit", "epic" matches "epic games launcher")
        best_token = process.extractOne(clean_name, all_candidates, scorer=fuzz.token_set_ratio)
        best_ratio = process.extractOne(clean_name, all_candidates, scorer=fuzz.ratio)

        match = None
        if best_token and best_token[1] >= 80:
            match = best_token[0]
        elif best_ratio and best_ratio[1] >= 70:
            match = best_ratio[0]

        if match:
            if match in BUILTIN_PROTOCOLS and _launch_target(BUILTIN_PROTOCOLS[match]):
                return f"Opening {match}."
            if match in COMMON_WEBSITES and _launch_target(COMMON_WEBSITES[match]):
                return f"Opening {match.title()}."
            if match in discovered and _launch_target(discovered[match]):
                return f"Opening {match}."
            if match in APP_ALIASES:
                sub = APP_ALIASES[match]
                if sub in discovered and _launch_target(discovered[sub]):
                    return f"Opening {match}."

    # 8. Final PATH fallback
    import shutil
    single_word = clean_name.split()[0]
    which = shutil.which(single_word) or shutil.which(f"{single_word}.exe")
    if which and _launch_target(which):
        return f"Opening {app_name}."

    return None


def _close_app(app_name: str) -> Optional[str]:
    """
    Close an application cleanly via taskkill.
    """
    clean_name = app_name.strip().lower().rstrip(".!?")
    if not clean_name:
        return None

    if clean_name in PROTECTED_PROCESSES or f"{clean_name}.exe" in PROTECTED_PROCESSES:
        return f"For system stability, closing {app_name} is restricted."

    # Find candidates
    candidates = PROCESS_ALIASES.get(clean_name, [])
    if not candidates:
        aliased = APP_ALIASES.get(clean_name)
        if aliased and aliased in PROCESS_ALIASES:
            candidates = PROCESS_ALIASES[aliased]
        else:
            discovered = _discover_installed_apps()
            if clean_name in discovered:
                target_path = discovered[clean_name]
                candidates = [f"{Path(target_path).stem}.exe"]
            elif clean_name in APP_COMMANDS:
                cmd = APP_COMMANDS[clean_name]
                candidates = [cmd if cmd.endswith(".exe") else f"{cmd}.exe"]
            else:
                return None

    closed_any = False
    for exe in candidates:
        if exe.lower() in PROTECTED_PROCESSES:
            continue
        try:
            proc = subprocess.run(
                ["taskkill", "/IM", exe, "/F"],
                shell=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                closed_any = True
        except Exception:
            pass

    if closed_any:
        return f"Closed {app_name}."

    return f"{app_name} does not appear to be running."


def try_local_command(text: str) -> Optional[str]:
    """
    If `text` matches a system action, app open/close command, or known app/website,
    execute it immediately and return a confirmation string.
    Returns None if nothing matched (falls through to AI/brain).
    """
    cleaned = _clean_input(text)
    if not cleaned:
        return None

    # 1. System command patterns first (volume, screenshot, lock, sleep, etc.)
    for pattern, handler in SYSTEM_PATTERNS:
        m = re.search(pattern, cleaned)
        if m:
            try:
                return handler(m)
            except Exception as e:
                return f"Couldn't do that: {e}"

    # 2. Extract app launch or close intent
    action_info = _extract_app_action(text)
    if action_info:
        action, target = action_info
        if action == "open":
            return _launch_app(target)
        elif action == "close":
            return _close_app(target)

    # 3. Direct app name or website trigger (e.g. user just says "calculator", "chrome", "vscode")
    clean_single = re.sub(r"^(?:open|launch|start|run|goto|go\s+to|the|my|app)\s+", "", cleaned).strip()
    if clean_single:
        # Check against quick names, protocols, common websites, aliases, and discovered apps
        all_candidates = (
            set(BUILTIN_PROTOCOLS.keys()) |
            set(COMMON_WEBSITES.keys()) |
            set(APP_ALIASES.keys()) |
            set(APP_COMMANDS.keys()) |
            set(_discover_installed_apps().keys())
        )
        if clean_single in all_candidates:
            res = _launch_app(clean_single)
            if res:
                return res

    return None
