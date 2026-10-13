# DISHA — Conversation Knowledge Log
## Session: 2026-10-13 (Founding Design Session)

> This file captures all decisions, discoveries, reasoning, and conclusions
> from the founding design conversation. It is the "why" behind every choice
> in this codebase. Any agent or developer should read this before changing
> anything to understand the full thinking behind the design.

---

## 1. Who Is This For

**Owner:** Developer  
**Machine:** Windows 11 Laptop, Intel i5 (8 cores / 12 threads), 16 GB RAM  
**Use context:** A developer who wants a personal assistant running silently in the background of their laptop — always available, not intrusive.

---

## 2. The Goal (Exact Words From Owner)

> *"The goal is to create a Virtual assistant that helps me from my laptop and is very useful to monitor and makes tasks easier and increasing the productivity which should also work online and offline, able to do stuff on my laptop on my command, should be able to listen to my commands or do when I type a query, should be able to work remotely and even if I port it in an external drive it should work independently in my PC and should be integrated as soon as I plug in after some verification. The assistant should meet the criteria to be called as a virtual assistant that makes it interactive, intuitive and creative."*

### Goal broken into requirements:
| Requirement | Priority |
|-------------|----------|
| Voice input (speak to DISHA) | Critical |
| Text input (type to DISHA) | Critical |
| Works online (Gemini AI) | Critical |
| Works offline (no internet fallback) | Critical |
| Control laptop apps by command | Critical |
| System controls (volume, screenshot, lock) | High |
| USB drive portable mode — plug in and it works | High |
| Verification/PIN before starting from USB | High |
| Remote access (from phone/another device) | High |
| Persistent memory across sessions | High |
| Wake word (hands-free trigger) | Medium |
| Interactive/creative UI | Medium |
| File and clipboard awareness | Medium |
| Screen awareness | Low (Phase 4) |
| Local LLM for offline AI reasoning | Low (Phase 4) |

---

## 3. What Was Found In The Repo (Audit Findings)

### 3.1 — Project Structure (at time of audit)
```
disha/
├── main.py          (14,214 bytes) — UI, tray, hotkeys, routing
├── voice.py         (13,113 bytes) — STT (Vosk) + TTS (SAPI5/pyttsx3)
├── config.py        (2,616 bytes)  — Settings from .env
├── gemini_client.py (1,864 bytes)  — Gemini API wrapper
├── memory.py        (1,913 bytes)  — Rolling JSONL conversation log
├── app_launcher.py  (2,180 bytes)  — Open/close apps offline
├── requirements.txt (147 bytes)    — 8 packages listed
├── setup_startup.bat               — Task Scheduler auto-start
├── model/                          — Vosk full English model (~70MB total)
│   ├── am/final.mdl (15.9MB)
│   ├── graph/Gr.fst (24MB)
│   ├── graph/HCLr.fst (22.4MB)
│   └── ivector/
├── assets/                         — Empty (no icon.png)
└── memory_log.jsonl                — Actual usage history (21 entries)
```

### 3.2 — Packages Confirmed In venv (Python 3.10)
Confirmed by scanning `venv/Lib/site-packages/`:
```
vosk, sounddevice, pyttsx3, pywin32 (win32com), numpy (2.2.6),
Pillow, pystray, pynput, google-generativeai (0.8.6), requests,
websockets, cryptography, pydantic, comtypes, tqdm, colorama,
cffi, annotated_types, typing_extensions
```

### 3.3 — Packages NOT In venv (must install before using)
```
flask, psutil, pyperclip, fuzzywuzzy, python-Levenshtein, schedule
```

### 3.4 — System Python vs venv
- venv Python: **3.10** (at `venv/Scripts/python.exe`)
- System Python: **3.12** (installed separately)
- **Rule: Always use the venv Python. Never use system Python for this project.**

### 3.5 — Ollama Status
- Ollama is **NOT installed** on this machine
- The `ollama` Python package is present in system Python but the Ollama server CLI is not installed
- Phase 4 (local LLM) cannot start until Ollama is installed: https://ollama.ai/download

---

## 4. Bugs Found (Confirmed During Audit)

### BUG-001 — `start_listening` is broken [CRITICAL]
- **File:** `main.py`, lines 207–242
- **Root cause:** `start_listening(self)` is defined with a `def` statement *inside* `focus_text_input(self)`, making it a nested function rather than a class method
- **Effect:** Clicking the 🎤 Listen button, pressing Ctrl+Alt+V, or clicking the floating widget all call `self.start_listening()` which raises `AttributeError: 'DishaAssistantWindow' object has no attribute 'start_listening'`
- **Voice mode is 100% broken because of this bug**
- **Fix:** Un-indent `start_listening` by one level so it's at the same indentation as `focus_text_input` — a class method, not a nested function

### BUG-002 — Wrong Gemini model name [HIGH]
- **File:** `config.py` line 15, `.env` line 2
- **Current:** `gemini-3.1-flash-lite` (does not exist)
- **Correct:** `gemini-2.5-flash`
- **Effect:** All Gemini calls fail with a model-not-found error

### BUG-003 — API key quoted in .env [HIGH]
- **File:** `.env` line 1
- **Current:** `GEMINI_API_KEY="sample_key"`
- **Problem:** python-dotenv includes the surrounding quote characters as part of the key value, so the actual key sent to Google includes `"` at the start and end — this breaks authentication
- **Fix:** `GEMINI_API_KEY=sample_key` (no quotes)

### BUG-004 — requirements.txt missing packages [MEDIUM]
- `numpy` is used in `voice.py` but not listed in `requirements.txt`
- `pywin32` is used in `voice.py` but not listed in `requirements.txt`
- **Effect:** Fresh install from requirements.txt would fail at runtime

---

## 5. Real Usage Data (From memory_log.jsonl)

These are actual commands used during early testing:

| Command | Worked? | Issue |
|---------|---------|-------|
| "open vscode" | ✅ Yes | — |
| "open google chrome" | ✅ Yes | — |
| "open settings" | ✅ Yes | — |
| "open filemanager" | ✅ Yes | mapped to "explorer" |
| "open Google Classroom" | ✅ Yes | — |
| "what shall i eat now im hungry" | ✅ Yes (online) | — |
| "hi" | ✅ Yes | — |
| Casual conversation | ⚠️ Partial | Voice transcription very garbled in many entries |
| Trying to set 7AM reminder | ❌ No | DISHA understood but couldn't actually set a reminder |
| Most queries while offline | ❌ No | All returned "I'm offline right now" |

### Key insight from usage data:
- The STT (Vosk) was producing very garbled text: e.g. *"that against it okay"*, *"the people a laptop though and ladder i use name my tonight and"*, *"i'm staying news h one day to get have to outdo that a state hello how are you want to buy it i'm back"*
- This means the microphone input was very noisy OR the confidence thresholds were too low
- The offline failures were very frequent — the user was often offline and got no useful response
- The app was actually being used and is meaningful — it's not abandoned

---

## 6. Architecture Decisions Made

### 6.1 — Why Keep Tkinter (Not Switch to a Better UI Framework)
- Tkinter is already working, ships with Python, no installation needed
- The upgrade is to switch from a single `Label` to a `Text` widget for chat history — this gives full chat history without changing the framework
- A more elaborate UI (Electron, PyQt) would require significant new dependencies and rewriting working code. Not worth it at this stage.
- **Decision: Keep Tkinter. Upgrade the chat display widget only.**

### 6.2 — Why Not Use Whisper for STT Instead of Vosk
- Vosk is already installed and working, model is already downloaded
- Whisper requires ~150MB+ models and is significantly heavier on CPU
- The full Vosk model already in the repo is good quality
- The problem isn't Vosk — it's that confidence thresholds were set too low (0.70 avg, 0.90 single word)
- **Decision: Keep Vosk. Raise confidence thresholds to 0.80 avg / 0.92 single word.**

### 6.3 — Why Local Brain Before Gemini
- The memory_log shows the user was frequently offline and got zero useful response
- Common questions (time, date, battery, CPU, wifi) don't need AI — they're pure Python
- Local brain answers instantly (< 5ms) vs Gemini (1–3 seconds)
- **Decision: Create `local_brain.py` that handles deterministic questions offline, Gemini only for creative/knowledge queries.**

### 6.4 — Why Flask for Remote Access (Not WebSockets)
- Flask is simple, already in system Python, familiar
- `websockets` package is already in the venv but building a full UI over raw WebSockets is harder
- Flask gives a browser-accessible chat UI that works on any device (phone, tablet) without installing anything
- **Decision: Flask REST API + simple HTML page served at localhost:5000**

### 6.5 — Why PIN Verification for USB Mode (Not Biometrics)
- Windows Hello biometrics requires system-level access and is complex to integrate
- A simple 6-character PIN derived from the device UUID is:
  - Fast to implement
  - Works without internet
  - Portable (the PIN doesn't change)
  - Sufficient for personal security
- **Decision: UUID-based 6-char PIN stored in `device_id.txt` on the USB drive**

### 6.6 — Why Ollama + phi3.5 for Phase 4 Local LLM
- Machine has 16GB RAM — phi3.5 (2.7GB) fits comfortably
- phi3.5 is Microsoft's model, optimized for instruction-following tasks like assistant work
- Ollama provides a simple HTTP API (`POST /api/generate`) that mirrors the Gemini interface
- Alternative considered: llama.cpp directly — rejected because Ollama is simpler to install and manage
- **Decision: Ollama with phi3.5 model for Phase 4. Do not attempt until Phases 0–3 are complete.**

### 6.7 — Why `schedule` Library for Reminders (Not `threading.Timer`)
- `threading.Timer` doesn't survive app restarts (timers are in-memory only)
- `schedule` library provides a clean recurring-check pattern
- But reminders still need to be persisted to `reminders.json` to survive restarts
- **Decision: Background thread checking every 30 seconds + `reminders.json` persistence.**

### 6.8 — Volume Control Without pycaw
- `pycaw` (Python Core Audio Windows) is the "right" way to set volume
- `pycaw` is not in the venv and adds complexity
- Alternative: PowerShell `WScript.Shell` with `SendKeys` for volume up/down keys
  - Works on all Windows 10/11
  - Approximate (not exact percentage) but functional
- **Decision: Use PowerShell WScript.Shell approach. Approximate volume is acceptable.**

---

## 7. What Was Explicitly Ruled Out

| Option | Why Ruled Out |
|--------|---------------|
| Electron/Node.js UI | Too heavy, different runtime, rewrite needed |
| FastAPI instead of Flask | Flask is simpler, already familiar, sufficient |
| ChromaDB for vector memory | Overkill for current usage volume; flat JSONL is fine until there's significant data |
| Always-on Whisper STT | Too CPU-heavy vs Vosk; Vosk model already downloaded |
| pycaw for volume | Not in venv; PowerShell approach is sufficient |
| GPT-4 instead of Gemini | Gemini API key already configured; switching breaks existing setup |
| Full rewrite | Foundation is solid; fix bugs and add features, don't rewrite |

---

## 8. Phase Plan Summary (Condensed)

### Phase 0 — Bugs + Dependencies (~2 hours)
Fix BUG-001, BUG-002, BUG-003, BUG-004. Install missing packages.
**Acceptance:** App starts, tray appears, Ctrl+Alt+D and Ctrl+Alt+V both work without errors.

### Phase 1 — Core Reliability (~6 hours)
- Scrollable chat history (replace single Label with Text widget)
- `local_brain.py`: answers time, date, battery, CPU, RAM, wifi, math offline
- System commands in `app_launcher.py`: volume, screenshot, lock screen, battery
- `scheduler.py`: reminder engine with persistence
- Raise STT confidence thresholds

**Acceptance:** DISHA useful offline. Reminders fire. Chat history scrolls. System commands work.

### Phase 2 — Productivity (~10 hours)
- Wake word detection ("hey disha")
- Clipboard reading ("what did I copy?")
- Dynamic app discovery (scan Start Menu)
- Streaming AI responses
- Facts stored from conversation ("remember that...")

**Acceptance:** Hands-free activation works. Clipboard accessible. Non-listed apps openable.

### Phase 3 — Portability + Remote (~6 hours)
- `usb_guard.py`: PIN verification on USB start
- `DISHA_Launcher.bat`: USB auto-launcher
- `web_interface.py`: Flask web UI on local network

**Acceptance:** USB launch with PIN works. Web UI accessible from phone on same Wi-Fi.

### Phase 4 — Intelligence (Month 2+)
- Install Ollama → pull phi3.5
- `local_llm.py`: offline AI reasoning via Ollama
- Screen awareness (screenshot + Gemini Vision)
- Morning briefing

**Prerequisite:** Phases 0–3 fully stable. Ollama manually installed.

---

## 9. Routing Logic (How DISHA Decides What To Do)

```
User says or types something
        ↓
1. app_launcher.try_local_command()
   → If matches system command or app open/close: execute + return
   → Else: continue
        ↓
2. scheduler.try_schedule_command()
   → If matches "remind me..." or "timer for...": store reminder + return
   → Else: continue
        ↓
3. local_brain.try_answer()
   → If matches time/date/battery/math/wifi/greeting: answer locally + return
   → Else: continue
        ↓
4. gemini_client.ask()
   → If online: call Gemini API → return answer
   → If offline: return graceful offline message
              (Phase 4: route to local_llm.ask_local() instead)
```

**This order matters. Never reorder it.** Local commands must always come before AI to avoid sending "open chrome" to Gemini.

---

## 10. Hard Rules Discovered During This Session

These were established through analysis and are non-negotiable:

1. **Never block the Tk main thread** — every network call, voice operation, or long computation goes in a `threading.Thread(target=..., daemon=True)`
2. **Never call Gemini without checking `is_online()` first** — the check is fast (< 2s timeout to 8.8.8.8:53)
3. **Never start microphone while TTS is playing** — `voice.wait_for_tts()` must always be called first to prevent DISHA from hearing herself
4. **Never hardcode absolute paths** — always use `BASE_DIR = Path(__file__).resolve().parent`; this is what makes USB portability possible
5. **Never commit `.env`** — API keys stay out of git
6. **Never invent a library** — only use packages confirmed in the venv site-packages list
7. **Never let voice mode silently fail** — if mic fails, show an error message in the UI and speak it
8. **Every feature needs an offline path** — if it requires internet, it must degrade gracefully

---

## 11. Scoring: Current vs Target

| Dimension | Score at Audit | Target After All Phases |
|-----------|---------------|------------------------|
| Voice input | 3/10 (broken bug) | 9/10 |
| Text input | 7/10 | 9/10 |
| Online AI | 8/10 | 9/10 |
| Offline capability | 1/10 | 7/10 (Phase 1), 9/10 (Phase 4) |
| System control | 2/10 | 8/10 |
| Memory | 4/10 | 8/10 |
| UI quality | 3/10 | 8/10 |
| USB portability | 0/10 | 8/10 |
| Remote access | 0/10 | 7/10 |
| **Overall** | **3/10** | **8/10** |

---

## 12. Questions Raised & Answered

**Q: Should we rewrite in a better framework?**  
A: No. Foundation is solid. Fix bugs, add features.

**Q: Is Vosk good enough for the STT?**  
A: Yes — the full model is already present and is high quality. The issue was low confidence thresholds accepting noise as speech. Raising thresholds fixes it.

**Q: Do we need a vector database for memory?**  
A: Not yet. Usage volume doesn't justify it. Flat JSONL is fine. Add a `facts.json` for user-specific persistent facts. Revisit after 3+ months of real usage.

**Q: Why is voice mode completely silent when it fails?**  
A: Because `start_listening` was nested inside `focus_text_input` — the method never got registered on the class. The button called `self.start_listening()` which doesn't exist. Fixed in Phase 0.

**Q: Can we install Ollama now for offline AI?**  
A: Not in current phases. Ollama needs to be installed separately (it's not a pip package). Phase 4 starts with that installation step.

**Q: Why not store the conversation transcript as-is in the repo?**  
A: The raw JSONL transcript is very large (~107KB), contains tool call noise, and is hard to read. This file distills the knowledge from it into a readable, searchable format that's directly useful to a developer or agent.

---

## 13. Files Created In This Session (Not In Original Repo)

| File | Created | Purpose |
|------|---------|---------|
| `AGENT_CONTEXT.md` | 2026-10-13 | Root-level guide for any agent/session working on this repo |
| `docs/MASTER_BLUEPRINT.md` | 2026-10-13 | Full technical architecture specification |
| `docs/AUDIT_AND_ROADMAP.md` | 2026-10-13 | Initial audit findings, bug report, roadmap |
| `docs/CONVERSATION_KNOWLEDGE.md` | 2026-10-13 | This file — all knowledge from founding design session |

---

## 14. How To Use This File

- **If you are an AI agent starting a new session:** Read this file to understand *why* decisions were made, not just what was decided. Then read `AGENT_CONTEXT.md` for current status and `docs/MASTER_BLUEPRINT.md` for implementation details.
- **If you are a developer returning after a break:** This gives you full context without re-reading the entire conversation.
- **If something seems wrong in the codebase:** Check here first — the rationale for every major choice is recorded. Don't change architecture without understanding why it was chosen.
- **Append a new section (Section 15, 16...) when a new major design session happens.** Never overwrite existing entries — always append.
