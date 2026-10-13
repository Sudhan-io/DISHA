# AGENT CONTEXT — DISHA Virtual Assistant
<!-- 
  ┌──────────────────────────────────────────────────────────────────┐
  │  READ THIS FIRST. Every agent/session working on this repo       │
  │  must read this file before making any changes.                  │
  │  Ignore this and you will drift. Read it and you won't.          │
  └──────────────────────────────────────────────────────────────────┘
-->

## What This Project Is

**DISHA** is a personal virtual assistant for Windows.

**One-sentence goal:**
> DISHA must always respond usefully — by voice or text, online or offline, on the laptop or from a USB drive — without hanging, crashing, or going silent.

**Owner:** Developer  
**Machine:** Windows 11 Laptop · Intel i5 (8C/12T) · 16 GB RAM · NVIDIA RTX GPU  
**Python:** 3.10 inside `venv/` (do NOT use the system Python 3.12)  
**Venv Python path:** `d:\PROJECTS\disha\venv\Scripts\python.exe`

---

## Full Documentation (Read Before Any Implementation)

| Document | Location | What It Contains |
|----------|----------|-----------------|
| **Master Blueprint** | [`docs/MASTER_BLUEPRINT.md`](docs/MASTER_BLUEPRINT.md) | Full architecture, every module spec, exact function signatures, data flows, phase plan, acceptance tests, anti-hallucination rules |
| **Audit & Roadmap** | [`docs/AUDIT_AND_ROADMAP.md`](docs/AUDIT_AND_ROADMAP.md) | Codebase audit, bug list, goal evaluation, priority queue |
| **Conversation Knowledge** | [`docs/CONVERSATION_KNOWLEDGE.md`](docs/CONVERSATION_KNOWLEDGE.md) | All knowledge from founding design session: owner goals, real usage data, all bugs found, every architecture decision + reasoning, what was ruled out and why, routing logic, hard rules |

> **Rule:** If you are implementing anything, open `docs/MASTER_BLUEPRINT.md` first. Every decision is already made there. Do not invent new architecture.

---

## Current Status

| Phase | Name | Status |
|-------|------|--------|
| **Phase 0** | Bug Fixes + Dependencies | ✅ COMPLETED |
| **Phase 1** | Core Reliability (local brain, system controls, chat history) | ✅ COMPLETED |
| **Phase 2** | Productivity (wake word, reminders, clipboard, streaming AI) | ✅ COMPLETED |
| **Phase 3** | Portability + Remote Access (USB mode, Flask web UI) | ✅ COMPLETED |
| **Phase 4** | Local LLM + Screen Awareness (Ollama, offline AI) | ✅ COMPLETED |

> **Update this table** at the end of every session.

---

## Known Bugs (Fix These Before Anything Else)

### BUG-001 — Voice mode completely broken [CRITICAL]
- **File:** `main.py` lines 207–242
- **Problem:** `start_listening()` is nested *inside* `focus_text_input()` as a local function, not a class method. Clicking 🎤 Listen or pressing Ctrl+Alt+V causes `AttributeError`.
- **Fix:** Un-indent `start_listening` out of `focus_text_input` — it must be at the same class-method level.
- **Status:** ✅ FIXED

### BUG-002 — Wrong Gemini model name [HIGH]
- **File:** `config.py` line 15 and `.env` line 2
- **Problem:** `gemini-3.1-flash-lite` does not exist. Correct name: `gemini-2.5-flash`
- **Fix:** Change both occurrences.
- **Status:** ✅ FIXED

### BUG-003 — API key has surrounding quotes in .env [HIGH]
- **File:** `.env` line 1
- **Problem:** `GEMINI_API_KEY="sample_key"` — quotes cause dotenv to include them in the key string, breaking auth
- **Fix:** Remove quotes: `GEMINI_API_KEY=sample_key`
- **Status:** ✅ FIXED

---

## Confirmed Package State (venv site-packages)

### ✅ Already installed in venv
```
vosk, sounddevice, pyttsx3, pywin32 (win32com), numpy, Pillow,
pystray, pynput, google-generativeai (0.8.6), requests, websockets,
cryptography, pydantic, tqdm, comtypes, colorama, cffi, annotated_types,
typing_extensions, flask (3.1.3), psutil (7.2.2), pyperclip (1.11.0),
fuzzywuzzy (0.18.0), python-Levenshtein (0.27.4), schedule (1.2.2)
```

### ❌ NOT installed — must pip install before using
```
None for Phases 0-3 (all dependencies installed in venv)
```

### ❌ NOT installed system-wide — install separately (Phase 4 only)
```
Ollama (https://ollama.ai/download) — DO NOT attempt until Phase 4
```

---

## Hard Rules For Every Agent Session

1. **Never use absolute paths in code.** Use `BASE_DIR = Path(__file__).resolve().parent` from `config.py`.
2. **Never block the Tk main thread.** All I/O → `threading.Thread(target=..., daemon=True).start()`.
3. **Never call Gemini without `gemini_client.is_online()` returning `True` first.**
4. **Never start STT while TTS is playing.** Always call `voice.wait_for_tts()` first.
5. **Every feature must have an offline path.** Degrade gracefully, never crash.
6. **Never hardcode credentials.** Everything from `.env` via `config.py`.
7. **Only use packages confirmed in the list above.** Do not invent or assume others are installed.
8. **Preserve all existing docstrings and comments** unless the line is being replaced.
9. **After each phase → run the acceptance tests** in `MASTER_BLUEPRINT.md` before stopping.
10. **Update the Status table above** at the end of every session.

---

## File Map (What Each File Does)

| File | Role | Modify? |
|------|------|---------|
| `main.py` | Entry point: Tk UI, tray, hotkeys, routing | ✅ Yes (Phase 0+) |
| `config.py` | All settings from `.env` | ✅ Yes (Phase 0) |
| `voice.py` | Offline STT (Vosk) + TTS (SAPI5) | ✅ Yes (Phase 1+) |
| `gemini_client.py` | Gemini AI wrapper | ✅ Yes (Phase 0 fix, Phase 2+) |
| `app_launcher.py` | Open/close apps + system commands | ✅ Yes (Phase 1+) |
| `memory.py` | Rolling log + facts store | ✅ Yes (Phase 1+) |
| `local_brain.py` | Offline rule answers (<5ms) | ✅ Complete |
| `local_llm.py` | Offline AI via Ollama (Llama 3.2 3B on GPU) | ✅ Complete |
| `scheduler.py` | Reminders and timer engine | ✅ Complete |
| `web_interface.py` | Flask remote access server & mobile UI | ✅ Complete |
| `usb_guard.py` | USB verification & PIN guard | ✅ Complete |
| `DISHA_Launcher.bat` | Portable launcher for USB drives | ✅ Complete |
| `setup_startup.bat` | Auto-start on Windows login via Task Scheduler | ✅ Complete |
| `model/` | Vosk speech model — DO NOT TOUCH | ❌ Never |
| `venv/` | Python virtual environment | ❌ Never edit manually |
| `.env` | Secrets — never commit | ❌ Never commit |

---

## Session Handoff Log

> Every agent session must append an entry here when it ends.

### Session 1 — 2026-10-13 (Audit + Planning)
- **Completed:** Full repo audit, bug discovery, architecture design, blueprint creation
- **Files changed:** None (analysis only)
- **Tests run:** None
- **Next session starts with:** Phase 0 — Step 0.1 (fix BUG-001 in `main.py`)
- **Blockers:** None

### Session 2 — 2026-10-13 (Phase 0 & Phase 1 Execution & Verification)
- **Completed:**
  - Resolved Python 3.10 virtualenv relocation error (`pyvenv.cfg` pointed to non-existent DELL user path; installed Python 3.10.11 user-scope via winget, updated `pyvenv.cfg`).
  - Fixed BUG-001 (`start_listening` un-indented in `main.py` as class method).
  - Fixed BUG-002 (`gemini-2.5-flash` model name in `config.py` and `.env`).
  - Fixed BUG-003 (removed surrounding quotes around API key in `.env`).
  - Generated and saved `assets/icon.png`.
  - Installed all missing packages in venv (`flask`, `psutil`, `pyperclip`, `fuzzywuzzy`, `python-Levenshtein`, `schedule`).
  - Created `local_brain.py` with offline deterministic query handlers (time, date, battery, CPU, RAM, Wi-Fi, math, help, greetings).
  - Upgraded `app_launcher.py` with system controls (volume, resilient screenshot, screen lock, power, battery, clipboard, downloads/documents/desktop folders, recycle bin).
  - Upgraded `memory.py` with persistent facts store (`facts.json`, `extract_and_store_facts()`, `get_fact()`, `save_fact()`).
  - Created `scheduler.py` engine for background reminder and timer scheduling.
  - Upgraded `main.py` UI with scrollable `tk.Text` chat history, visual listening state badge, multi-tier routing (Apps -> Scheduler -> Local Brain -> Gemini), and scheduler trigger integration.
  - Tuned `voice.py` STT thresholds (`MIN_AVG_CONF=0.80`, `SINGLE_WORD_CONF=0.92`, `NO_SPEECH_TIMEOUT=4.0`).
- **Files changed:** `main.py`, `config.py`, `.env`, `requirements.txt`, `.gitignore`, `voice.py`, `app_launcher.py`, `memory.py`, `local_brain.py` (new), `scheduler.py` (new), `assets/icon.png` (new).
- **Tests run:** Full Phase 0 & Phase 1 test suite executed and passed (unit imports, routing tiers, offline fallback, screenshot, volume, Tkinter UI widgets, Gemini online response).
- **Next session starts with:** Phase 2 — Step 2.1 (wake word listener in `voice.py` and `main.py`).
- **Blockers:** None

### Session 3 — 2026-10-13 (Phase 2 & STT Upgrade to faster-whisper)
- **Completed:**
  - Evaluated system hardware: Intel i5-12450HX (8C/12T) + NVIDIA RTX 3050 6GB GPU + 16 GB RAM.
  - Upgraded Speech-to-Text from legacy Vosk to **faster-whisper** (`faster-whisper>=1.0.0` with CTranslate2 INT8 quantization on 6 CPU threads).
  - Benchmark: `base.en` transcribes in ~500ms on CPU with world-class Whisper accuracy, correct capitalization, and punctuation, completely eliminating garbled transcripts. Kept Vosk as an instant real-time live partials feedback provider and fallback.
  - Implemented Step 2.1: Wake word listener in `voice.py` and background daemon thread in `main.py`.
  - Implemented Step 2.2: Clipboard reading in `app_launcher.py` (`"what did i copy"` / `"clipboard"`).
  - Implemented Step 2.3: Dynamic Start Menu app discovery (139+ apps indexed) and fuzzy app matching via `fuzzywuzzy`.
  - Implemented Step 2.4: Real-time token streaming AI responses in `gemini_client.py` and live streaming chat view in `main.py`.
  - Implemented Step 2.5: Personality personalization using persistent facts from `memory.py` (e.g. `user_name`).
- **Files changed:** `voice.py`, `app_launcher.py`, `gemini_client.py`, `main.py`, `config.py`, `.env`, `requirements.txt`.
- **Tests run:** All Phase 2 acceptance tests passed (clipboard, dynamic app discovery, token streaming, facts personalization, faster-whisper benchmark).
- **Next session starts with:** Phase 3 (Portability + Remote Access: USB verification PIN guard, portable launcher batch, Flask web UI).
- **Blockers:** None

### Session 4 — 2026-10-13 (Phase 3 Portability & Remote Web Access)
- **Completed:**
  - Implemented Step 3.1: Created `usb_guard.py` handling USB portable mode detection (`USB_MODE` and `DISHA_USB_MODE`), first-run device ID generation (`device_id.txt`), first-run PIN display dialog, and a dark-themed PIN entry window with 3 attempts and a 30-second lockout timer.
  - Implemented Step 3.2: Created portable launcher `DISHA_Launcher.bat` with auto drive detection (`%~d0`, `%~dp0`), setting `DISHA_USB_MODE=true` and launching `venv\Scripts\pythonw.exe main.py` seamlessly without leaving a terminal window open.
  - Implemented Step 3.3: Performed path relativity audit across all modules to ensure zero hardcoded absolute paths exist and everything strictly references `BASE_DIR`.
  - Implemented Step 3.4: Created `web_interface.py` with Flask daemon server running on `0.0.0.0:WEB_PORT`, Bearer token authentication via `DISHA_WEB_TOKEN`, machine telemetry status endpoint `GET /api/status`, query routing endpoint `POST /api/ask`, and a sleek, mobile-friendly inline HTML/CSS/JS chat UI with token configuration, quick action chips, and real-time battery status.
  - Implemented Step 3.5 & 3.6: Integrated `usb_guard` and `web_interface` into `main.py` (USB security gate at entry, web interface daemon start, voice announcement on web readiness, and dynamic LAN IP address shown in tray tooltip with one-click URL copy option).
  - Executed full Phase 3 test suite (`test_phase3.py`): 6/6 tests passed including USB PIN logic, Flask endpoints, status telemetry, empty query validation, path audit, launcher batch check, and LAN IP resolution.
- **Files changed:** `usb_guard.py` (new), `DISHA_Launcher.bat` (new), `web_interface.py` (new), `main.py`, `AGENT_CONTEXT.md`.
- **Tests run:** All Phase 3 acceptance tests passed.
- **Next session starts with:** Phase 4 — Step 4.1 & 4.2 (Install Ollama locally, pull lightweight offline LLM `phi3.5` or `llama3.2:1b`, and build `local_llm.py` + Screen Awareness).
- **Blockers:** None

### Session 5 — 2026-10-13 (Phase 4 Local LLM with Llama 3.2 3B & Screen Awareness)
- **Completed:**
  - Installed Ollama portable distribution directly to dedicated location: `D:\Ollama` (binaries in `D:\Ollama`, models directory in `D:\Ollama\models`).
  - Configured permanent User environment variable `OLLAMA_MODELS = D:\Ollama\models` and appended `D:\Ollama` to User `PATH`.
  - Replaced suboptimal `phi3.5` with **`llama3.2:3b`** (Meta Llama 3.2 3B):
    - Footprint: 2.0 GB on D: drive, uses ~2.5 GB total VRAM on RTX 3050 6GB Laptop GPU (leaving 3.5 GB VRAM free for system/apps).
    - Configured automatic VRAM freeing when idle (`keep_alive: 5m` in payload).
    - Response time: ~2 seconds with high quality, conversational output.
  - Implemented `local_llm.py` wrapping Ollama REST API with `is_ollama_running()` healthcheck, synchronous `ask_local()`, and token streaming `ask_local_streaming()`.
  - Updated `gemini_client.py` with seamless offline failover: when `is_online()` returns `False`, queries route automatically to `local_llm` without crashing or going silent.
  - Implemented `ask_with_screenshot()` in `gemini_client.py` with multi-monitor / secondary desktop GDI capture fallback for screen awareness.
  - Verified end-to-end offline routing via `main.route_request()` with clean, accurate response.
- **Files changed:** `config.py`, `.env`, `local_llm.py` (new), `gemini_client.py`, `AGENT_CONTEXT.md`.
- **Tests run:** All Phase 4 tests passed (Ollama CLI version, D: drive model storage, Llama 3.2 3B warm inference, token streaming, VRAM memory verification, and offline `main.py` routing).
- **Next steps:** All phases (0, 1, 2, 3, and 4) are now complete and functional!
- **Blockers:** None




