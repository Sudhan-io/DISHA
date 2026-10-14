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
GEMINI_MODEL       = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# ── Local LLM (Ollama) ─────────────────────────────────────────────────────
OLLAMA_URL         = os.getenv("DISHA_OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL       = os.getenv("DISHA_OLLAMA_MODEL", "llama3.2:3b")

# ── Hotkeys ─────────────────────────────────────────────────────────────────
HOTKEY             = os.getenv("DISHA_HOTKEY", "<ctrl>+<alt>+d")
VOICE_HOTKEY       = os.getenv("DISHA_VOICE_HOTKEY", "<ctrl>+<alt>+v")

# ── Voice / STT ─────────────────────────────────────────────────────────────
STT_ENGINE         = os.getenv("DISHA_STT_ENGINE", "whisper").lower() # "whisper" or "vosk"
WHISPER_MODEL_SIZE = os.getenv("DISHA_WHISPER_MODEL", "base.en")     # "tiny.en", "base.en", "small.en", "medium.en"
WHISPER_BEAM_SIZE  = int(os.getenv("DISHA_WHISPER_BEAM", "1"))        # 1 for fast greedy decoding, 5 for beam search
VOSK_MODEL_PATH    = os.getenv("VOSK_MODEL_PATH", str(BASE_DIR / "model"))
TTS_ENABLED        = os.getenv("DISHA_TTS_ENABLED", "true").lower() == "true"
TTS_ENGINE         = os.getenv("DISHA_TTS_ENGINE", "neural").lower() # "neural" (Edge-TTS) or "sapi"
TTS_NEURAL_VOICE   = os.getenv("DISHA_TTS_NEURAL_VOICE", "en-US-AnaNeural") # anime / e-girl neural character voice
TTS_RATE           = int(os.getenv("DISHA_TTS_RATE", "175"))
TTS_VOICE_GENDER   = os.getenv("DISHA_TTS_VOICE", "female")
SILENCE_STOP_SECONDS = float(os.getenv("DISHA_SILENCE_STOP", "0.75"))

# ── Voice Model Personas ─────────────────────────────────────────────────────
VOICES_DIR         = BASE_DIR / "models" / "voices"
VOICE_PROFILE      = os.getenv("DISHA_VOICE_PROFILE", "egirl").lower()

VOICE_PROFILES: dict[str, dict] = {
    "egirl": {
        "id": "egirl",
        "name": "💖 E-Girl Persona (egirl.pth / Anime Character)",
        "short_name": "💖 E-Girl",
        "engine": "neural",
        "neural_voice": "en-US-AnaNeural",
        "gender": "female",
        "model_file": "egirl.pth",
    },
    "jenny": {
        "id": "jenny",
        "name": "✨ Jenny Neural (Natural Expressive Female)",
        "short_name": "✨ Jenny",
        "engine": "neural",
        "neural_voice": "en-US-JennyNeural",
        "gender": "female",
        "model_file": None,
    },
    "guy": {
        "id": "guy",
        "name": "🎙️ Guy Neural (Deep Natural Male)",
        "short_name": "🎙️ Guy",
        "engine": "neural",
        "neural_voice": "en-US-GuyNeural",
        "gender": "male",
        "model_file": None,
    },
    "aria": {
        "id": "aria",
        "name": "🌟 Aria Neural (Polished Assistant)",
        "short_name": "🌟 Aria",
        "engine": "neural",
        "neural_voice": "en-US-AriaNeural",
        "gender": "female",
        "model_file": None,
    },
    "zira": {
        "id": "zira",
        "name": "💻 Windows Zira (Offline SAPI5 Female)",
        "short_name": "💻 Zira",
        "engine": "sapi",
        "neural_voice": "",
        "gender": "female",
        "model_file": None,
    },
    "david": {
        "id": "david",
        "name": "💻 Windows David (Offline SAPI5 Male)",
        "short_name": "💻 David",
        "engine": "sapi",
        "neural_voice": "",
        "gender": "male",
        "model_file": None,
    },
}

# Sync initial TTS parameters with selected voice profile if valid
if VOICE_PROFILE in VOICE_PROFILES:
    _cur_prof = VOICE_PROFILES[VOICE_PROFILE]
    TTS_ENGINE = os.getenv("DISHA_TTS_ENGINE", _cur_prof["engine"]).lower()
    if _cur_prof.get("neural_voice"):
        TTS_NEURAL_VOICE = os.getenv("DISHA_TTS_NEURAL_VOICE", _cur_prof["neural_voice"])
    if _cur_prof.get("gender"):
        TTS_VOICE_GENDER = os.getenv("DISHA_TTS_VOICE", _cur_prof["gender"])


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
WEB_HOST           = os.getenv("DISHA_WEB_HOST", "0.0.0.0")
WEB_PORT           = int(os.getenv("DISHA_WEB_PORT", "5000"))
WEB_TOKEN          = os.getenv("DISHA_WEB_TOKEN", "")

# ── USB Portable Mode ────────────────────────────────────────────────────────
USB_MODE           = os.getenv("DISHA_USB_MODE", "false").lower() == "true"
DEVICE_ID_FILE     = BASE_DIR / "device_id.txt"

# ── App Launcher ─────────────────────────────────────────────────────────────
APP_COMMANDS: dict[str, str] = {
    "vscode": "code", "vs code": "code", "visual studio code": "code",
    "chrome": "chrome", "google chrome": "chrome",
    "brave": "brave", "brave browser": "brave",
    "edge": "msedge", "microsoft edge": "msedge", "msedge": "msedge",
    "firefox": "firefox",
    "notepad": "notepad", "notepad++": "notepad++",
    "calculator": "calc", "calc": "calc",
    "file explorer": "explorer", "explorer": "explorer", "files": "explorer",
    "terminal": "wt", "windows terminal": "wt",
    "command prompt": "cmd", "cmd": "cmd",
    "task manager": "taskmgr",
    "settings": "ms-settings:", "windows settings": "ms-settings:",
    "bluetooth": "ms-settings:bluetooth", "bluetooth settings": "ms-settings:bluetooth",
    "wifi settings": "ms-settings:network-wifi", "network settings": "ms-settings:network",
    "sound settings": "ms-settings:sound", "display settings": "ms-settings:display",
    "paint": "mspaint",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "spotify": "spotify",
    "discord": "discord",
    "zoom": "zoom",
}

# ── User Profile & Personality ───────────────────────────────────────────────
USER_NAME = os.getenv("USER_NAME", "Sudhan")

SYSTEM_PROMPT = f"""You are DISHA, a personal desktop companion for {USER_NAME}.
Keep replies SHORT — 2 sentences max unless asked to elaborate.
You sit quietly in the background and only speak when asked.
Be direct, warm, and never waste time. No corporate tone.
If ambiguous, make a reasonable assumption and answer immediately.
Reference the user's name occasionally but not always.
Never say 'I cannot' — always find a way or suggest the closest alternative."""

# ── App metadata ──────────────────────────────────────────────────────────────
APP_NAME       = "DISHA"
APP_FULL_NAME  = "Desktop Intelligent System for Hybrid Assistance"
ICON_PATH      = BASE_DIR / "assets" / "icon.png"