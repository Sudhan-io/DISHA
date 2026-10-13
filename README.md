# 🌟 DISHA — Desktop Intelligent System for Hybrid Assistance

> **D.I.S.H.A.** — **D**esktop **I**ntelligent **S**ystem for **H**ybrid **A**ssistance  
> *In Sanskrit, **Disha** (दिशा) signifies **"Direction"** or **"Guiding Path"** — a lightweight, hybrid personal companion designed to navigate desktop workflows with zero friction across online, offline, and portable states.*

> **"DISHA must always respond usefully — by voice or text, online or offline, on the laptop or from a USB drive — without hanging, crashing, or going silent."**

**DISHA** is an event-driven, multi-tier personal virtual assistant designed for Windows 11. It idles silently in the system tray and wakes instantly via global hotkeys, floating desktop widget, or hands-free wake word.

---

## ⚡ Key Highlights & Architecture

- **Multi-Tier Hybrid Brain:**
  1. **Tier 1 (Instant Local Commands <1ms):** Controls Windows system features (volume, mute, sleep, lock, screenshot, clipboard reading, special folders) and opens any of 139+ Start Menu applications via fuzzy matching.
  2. **Tier 2 (Scheduler & Reminders <2ms):** Parses natural language timers and persistent reminders (`"remind me in 15 minutes to take a break"`).
  3. **Tier 3 (Deterministic Offline Brain <5ms):** Instantly answers system questions (battery %, charging state, RAM usage, CPU load, date, time, math expressions).
  4. **Tier 4 (Online AI — Gemini 2.5 Flash):** High-speed streaming AI with contextual personalization from your saved facts.
  5. **Tier 5 (Offline Local LLM — Meta Llama 3.2 3B):** Automatic failover when offline. Runs locally via Ollama with NVIDIA GPU acceleration and automatic memory release when idle.
- **Accurate Speech-to-Text (`faster-whisper`):**
  Uses CTranslate2 INT8 quantization on 6 CPU threads (~500ms latency) with full punctuation and capitalization. Vosk provides background wake word detection (`"hey disha"`) and live partials.
- **Windows SAPI5 Voice Output:**
  Clean, reliable text-to-speech with collision prevention (never listens while speaking).
- **Portable USB Mode:**
  Runs self-contained from any USB drive via `DISHA_Launcher.bat`. Enforces a 6-character hardware PIN guard with a 30-second lockout timer.
- **Mobile Remote Web Access:**
  Built-in Flask server on your local LAN with a mobile-optimized dark-mode chat UI and Bearer token security. Access DISHA from your phone on the same Wi-Fi.

---

## 🏗️ System Architecture

```
User Input (Voice / Hotkey / Widget / Web)
                  │
                  ▼
         main.py (Central Router)
                  │
  ┌───────────────┼───────────────┬─────────────────┐
  │               │               │                 │
  ▼               ▼               ▼                 ▼
Tier 1          Tier 2          Tier 3            Tier 4 & 5
app_launcher    scheduler       local_brain       AI Reasoning
- 139+ Apps     - Timers        - Time / Date     - Online: Gemini 2.5 Flash
- System Ctrl   - Reminders     - Battery / RAM   - Offline: Llama 3.2 3B
- Clipboard     - reminders.json- Math (<5ms)       (Ollama GPU @ D:\Ollama)
```

---

## 💻 Hardware Compatibility & Benchmarks

DISHA is tuned and benchmarked on modern Windows 11 systems:
- **Benchmark Platform:** Windows 11 Laptop · Intel Core i5 (8C/12T) · 16 GB RAM · NVIDIA GeForce RTX GPU.
- **Speech Transcription:** ~500 ms on CPU (`faster-whisper base.en`).
- **Offline Rule Answers:** < 0.2 ms (`local_brain.py`).
- **Offline LLM Inference:** ~55–65 tokens/sec (`llama3.2:3b` on CUDA0).
- **VRAM Footprint:** ~2.5 GB total in use; frees automatically after 5 minutes of inactivity.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Windows 10 or 11 (64-bit)**
- **Python 3.10** (recommended inside a virtual environment `venv/`)
- A **Gemini API Key** from [Google AI Studio](https://aistudio.google.com/apikey)

### 2. Installation
Clone the repository and install the dependencies:
```powershell
cd disha
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Speech Model Setup (Vosk)
Ensure the Vosk wake word model is located at `model/`:
```
disha/
└── model/
    ├── am/final.mdl
    ├── conf/
    ├── graph/
    └── ivector/
```

### 4. Local LLM Setup (Ollama on D: Drive)
Ollama and its models are stored directly on the `D:` drive to preserve SSD capacity on `C:`:
- **Ollama Binaries:** `D:\Ollama\ollama.exe`
- **Model Storage:** `D:\Ollama\models`
- **Environment Variable:** `OLLAMA_MODELS = D:\Ollama\models`
- Model pulled: `llama3.2:3b` (2.0 GB).

### 5. Configuration (`.env`)
Copy `.env.example` to `.env` in the project root:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

DISHA_HOTKEY=<ctrl>+<alt>+d
DISHA_VOICE_HOTKEY=<ctrl>+<alt>+v
DISHA_STT_ENGINE=whisper
DISHA_WHISPER_MODEL=base.en

DISHA_WAKE_WORD=false
DISHA_WAKE_PHRASE=hey disha

USER_NAME=YourName

DISHA_WEB_ENABLED=false
DISHA_WEB_HOST=0.0.0.0
DISHA_WEB_PORT=5000
DISHA_WEB_TOKEN=your_secure_bearer_token_here

DISHA_USB_MODE=false
DISHA_OLLAMA_MODEL=llama3.2:3b
DISHA_OLLAMA_URL=http://localhost:11434/api/generate
```

---

## 🎮 How to Use

### Launching
- **Console Mode (Testing):**
  ```powershell
  venv\Scripts\python.exe main.py
  ```
- **Silent Background Mode:**
  ```powershell
  venv\Scripts\pythonw.exe main.py
  ```
- **USB Portable Mode:**
  Double-click `DISHA_Launcher.bat` from any drive letter.

### Controls & Shortcuts
| Action | Shortcut / Trigger |
|---|---|
| **Voice Query** | Press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>V</kbd> |
| **Text Overlay** | Press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>D</kbd> |
| **Floating Logo** | Left-click the draggable green **D** widget on your desktop |
| **Tray Icon** | Right-click tray icon to open voice, text, or copy mobile URL |
| **Dismiss Window** | Press <kbd>Esc</kbd> or say/type `"exit"`, `"bye"`, `"close"` |

---

## 📱 Mobile Remote Access

When `DISHA_WEB_ENABLED=true`:
1. DISHA starts a background daemon on port `5000`.
2. Find your local IP in the system tray tooltip (e.g. `http://<your-local-ip>:5000` or `http://192.168.1.100:5000`).
3. Open the URL in your phone's browser on the same Wi-Fi network.
4. Enter your `DISHA_WEB_TOKEN` when prompted to unlock live querying and telemetry.

---

## 🗂️ Project Structure

```
disha/
├── main.py              # Main Tkinter UI, system tray, hotkeys, and master router
├── config.py            # Environment configuration loader
├── voice.py             # faster-whisper STT, Vosk wake word, and SAPI5 TTS
├── gemini_client.py     # Gemini 2.5 Flash streaming AI & screen awareness
├── local_brain.py       # Offline deterministic answers (<5ms)
├── local_llm.py         # Local offline LLM wrapper (Ollama + Llama 3.2 3B)
├── app_launcher.py      # Dynamic 139+ app discovery & system controls
├── memory.py            # Persistent fact store (facts.json) & rolling history
├── scheduler.py         # Natural language timer and reminder engine
├── usb_guard.py         # Hardware device PIN verification & security lockout
├── web_interface.py     # Flask daemon server & mobile chat UI
├── DISHA_Launcher.bat   # Portable USB launcher
├── requirements.txt     # Pinned Python dependencies
└── model/               # Vosk offline acoustic model
```

---

## 🛡️ Hard Architectural Rules

1. **Path Relativity:** Every file path is relative to `BASE_DIR`. Zero absolute paths exist.
2. **Non-Blocking UI:** All I/O, AI calls, and audio operations run in daemon threads.
3. **No Self-Hearing:** Microphone never opens while speech synthesizer is speaking.
4. **Offline Resilience:** Every single command degrades gracefully when internet is unavailable.
5. **Memory Economy:** Local models auto-unload from GPU VRAM after 5 minutes of idle time.
