"""
DISHA - Settings & AI Configuration Modal
Allows managing and switching Google Gemini API keys, active AI models,
and voice synthesis (TTS) preferences directly from the Desktop UI.
Persists changes safely to .env and reloads runtime configurations live.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable
from pathlib import Path

import config
import gemini_client
import voice


def update_env_file(key: str, value: str) -> bool:
    """Safely updates or inserts a key=value pair into .env file."""
    env_path = config.BASE_DIR / ".env"
    if not env_path.exists():
        try:
            env_path.write_text(f"{key}={value}\n", encoding="utf-8")
            return True
        except Exception:
            return False

    try:
        content = env_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


class DishaSettingsDialog:
    """
    Sleek obsidian settings dialog for API key management, model selection,
    and voice output configuration.
    """

    def __init__(self, parent: tk.Toplevel, on_close: Optional[Callable] = None):
        self.parent = parent
        self.on_close = on_close
        self.win = tk.Toplevel(parent)
        self.win.title("DISHA Settings")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#0b0d14")

        # Center over parent
        w, h = 520, 560
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = max(10, px + (pw - w) // 2)
        y = max(10, py + (ph - h) // 2)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        self._show_key = False
        self._build_ui()

    def _build_ui(self):
        # 1px Neon Border Frame
        outer = tk.Frame(self.win, bg="#20263b", padx=1, pady=1)
        outer.pack(fill="both", expand=True)

        main = tk.Frame(outer, bg="#0d0f17")
        main.pack(fill="both", expand=True, padx=1, pady=1)

        # ── Header Bar ────────────────────────────────────────────────────────
        header = tk.Frame(main, bg="#131622", height=44)
        header.pack(fill="x", side="top")

        title_lbl = tk.Label(
            header,
            text="⚙️ DISHA Settings & AI Config",
            bg="#131622",
            fg="#f8fafc",
            font=("Segoe UI", 11, "bold"),
            padx=16,
            pady=10,
        )
        title_lbl.pack(side="left")

        close_btn = tk.Label(
            header,
            text=" ✕ ",
            bg="#131622",
            fg="#94a3b8",
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            padx=14,
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self.close())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg="#f43f5e"))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg="#94a3b8"))

        # Scrollable / Body Container
        body = tk.Frame(main, bg="#0d0f17", padx=20, pady=16)
        body.pack(fill="both", expand=True)

        # ── Section 1: Gemini API Key ─────────────────────────────────────────
        sec1_lbl = tk.Label(
            body,
            text="GOOGLE GEMINI API KEY",
            bg="#0d0f17",
            fg="#00d2ff",
            font=("Segoe UI", 9, "bold"),
        )
        sec1_lbl.pack(anchor="w", pady=(0, 4))

        key_box = tk.Frame(body, bg="#141826", bd=1, relief="solid")
        key_box.pack(fill="x", pady=(0, 6))

        self.key_var = tk.StringVar(value=config.GEMINI_API_KEY)
        self.key_entry = tk.Entry(
            key_box,
            textvariable=self.key_var,
            show="●",
            bg="#141826",
            fg="#f8fafc",
            insertbackground="#00d2ff",
            font=("Consolas", 10),
            relief="flat",
            bd=6,
        )
        self.key_entry.pack(side="left", fill="x", expand=True)

        self.eye_btn = tk.Label(
            key_box,
            text="👁️",
            bg="#141826",
            fg="#94a3b8",
            font=("Segoe UI", 10),
            cursor="hand2",
            padx=8,
        )
        self.eye_btn.pack(side="right")
        self.eye_btn.bind("<Button-1>", lambda e: self._toggle_show_key())

        # Key Action Buttons
        key_actions = tk.Frame(body, bg="#0d0f17")
        key_actions.pack(fill="x", pady=(0, 14))

        self.test_btn = tk.Button(
            key_actions,
            text="🧪 Test Key",
            command=self._test_key,
            bg="#1e293b",
            fg="#38bdf8",
            activebackground="#0284c7",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.test_btn.pack(side="left", padx=(0, 8))

        self.save_key_btn = tk.Button(
            key_actions,
            text="💾 Save Key",
            command=self._save_key,
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.save_key_btn.pack(side="left")

        self.key_status_lbl = tk.Label(
            key_actions,
            text="",
            bg="#0d0f17",
            fg="#94a3b8",
            font=("Segoe UI", 8),
        )
        self.key_status_lbl.pack(side="left", padx=10)

        # ── Section 2: Active AI Model Engine ─────────────────────────────────
        sec2_lbl = tk.Label(
            body,
            text="PRIMARY AI ENGINE & MODEL",
            bg="#0d0f17",
            fg="#a855f7",
            font=("Segoe UI", 9, "bold"),
        )
        sec2_lbl.pack(anchor="w", pady=(8, 6))

        self.model_var = tk.StringVar(value=config.GEMINI_MODEL)
        models = [
            ("gemini-3.5-flash-lite", "⚡ Gemini 3.5 Flash Lite (Fastest & Active Quota)"),
            ("gemini-3.8-flash", "🧠 Gemini 3.8 Flash (Advanced Reasoning)"),
            ("local-ollama", "🛡️ Local Ollama Llama 3.2 3B (100% Offline GPU)"),
        ]

        for mod_id, mod_name in models:
            rb = tk.Radiobutton(
                body,
                text=mod_name,
                value=mod_id,
                variable=self.model_var,
                command=self._on_model_change,
                bg="#0d0f17",
                fg="#f1f5f9",
                selectcolor="#1e1b4b",
                activebackground="#0d0f17",
                activeforeground="#a855f7",
                font=("Segoe UI", 9),
            )
            rb.pack(anchor="w", pady=2)

        # ── Section 3: Voice & Speech Engine ──────────────────────────────────
        sec3_lbl = tk.Label(
            body,
            text="VOICE SYNTHESIS (TTS) PREFERENCES",
            bg="#0d0f17",
            fg="#34d399",
            font=("Segoe UI", 9, "bold"),
        )
        sec3_lbl.pack(anchor="w", pady=(14, 6))

        voice_row = tk.Frame(body, bg="#0d0f17")
        voice_row.pack(fill="x", pady=2)

        self.tts_enabled_var = tk.BooleanVar(value=config.TTS_ENABLED)
        cb_tts = tk.Checkbutton(
            voice_row,
            text="Enable Voice Output (Spoken Replies)",
            variable=self.tts_enabled_var,
            command=self._on_tts_toggle,
            bg="#0d0f17",
            fg="#f1f5f9",
            selectcolor="#064e3b",
            activebackground="#0d0f17",
            activeforeground="#34d399",
            font=("Segoe UI", 9),
        )
        cb_tts.pack(side="left")

        # Active Voice Model Selector
        selector_row = tk.Frame(body, bg="#0d0f17")
        selector_row.pack(fill="x", pady=(6, 2))

        tk.Label(
            selector_row,
            text="Active Voice Model:",
            bg="#0d0f17",
            fg="#94a3b8",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 8))

        active_profile = voice.get_active_voice_profile()
        profile_names = [p["name"] for p in config.VOICE_PROFILES.values()]
        self.voice_var = tk.StringVar(value=active_profile.get("name", profile_names[0]))

        self.voice_combo = ttk.Combobox(
            selector_row,
            textvariable=self.voice_var,
            values=profile_names,
            state="readonly",
            font=("Segoe UI", 9),
            width=36,
        )
        self.voice_combo.pack(side="left", fill="x", expand=True)
        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_profile_change)

        test_voice_btn = tk.Button(
            selector_row,
            text="🔊 Test Voice",
            command=self._test_voice,
            bg="#1e293b",
            fg="#34d399",
            activebackground="#059669",
            activeforeground="#ffffff",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=10,
            pady=2,
            cursor="hand2",
        )
        test_voice_btn.pack(side="left", padx=(8, 0))

        # Model Details Badge
        self.voice_desc_lbl = tk.Label(
            body,
            text="",
            bg="#0d0f17",
            fg="#38bdf8",
            font=("Segoe UI", 8),
        )
        self.voice_desc_lbl.pack(anchor="w", pady=(2, 6))
        self._update_voice_desc()

        # ── Bottom Bar: Done / Close ──────────────────────────────────────────
        bottom_bar = tk.Frame(main, bg="#131622", height=44)
        bottom_bar.pack(fill="x", side="bottom")

        done_btn = tk.Button(
            bottom_bar,
            text="Done",
            command=self.close,
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=20,
            pady=5,
            cursor="hand2",
        )
        done_btn.pack(side="right", padx=16, pady=8)

        self.win.bind("<Escape>", lambda e: self.close())

    def _toggle_show_key(self):
        self._show_key = not self._show_key
        if self._show_key:
            self.key_entry.configure(show="")
            self.eye_btn.configure(fg="#00d2ff")
        else:
            self.key_entry.configure(show="●")
            self.eye_btn.configure(fg="#94a3b8")

    def _save_key(self):
        new_key = self.key_var.get().strip()
        if not new_key:
            self.key_status_lbl.configure(text="Key cannot be empty.", fg="#f43f5e")
            return

        config.GEMINI_API_KEY = new_key
        gemini_client.GEMINI_API_KEY = new_key
        gemini_client._model = None
        ok = update_env_file("GEMINI_API_KEY", new_key)
        if ok:
            self.key_status_lbl.configure(text="✓ Saved to .env!", fg="#34d399")
        else:
            self.key_status_lbl.configure(text="Failed to write .env", fg="#f43f5e")

    def _test_key(self):
        test_key = self.key_var.get().strip()
        if not test_key:
            self.key_status_lbl.configure(text="Enter key to test.", fg="#f43f5e")
            return

        self.key_status_lbl.configure(text="Testing with Google...", fg="#38bdf8")
        self.test_btn.configure(state="disabled")

        def _worker():
            import google.generativeai as genai
            try:
                genai.configure(api_key=test_key)
                m = genai.GenerativeModel("gemini-3.5-flash-lite")
                resp = m.generate_content("ping")
                if resp and resp.text:
                    self.win.after(0, lambda: (
                        self.key_status_lbl.configure(text="✓ Key Active & Verified!", fg="#34d399"),
                        self.test_btn.configure(state="normal")
                    ))
                    return
            except Exception as e:
                err = str(e)
                if "429" in err:
                    msg = "429 Rate Limit (Free tier daily cap)"
                elif "API_KEY_INVALID" in err or "400" in err:
                    msg = "Invalid API Key"
                else:
                    msg = "Connection failed"
                self.win.after(0, lambda: (
                    self.key_status_lbl.configure(text=f"✕ {msg}", fg="#f43f5e"),
                    self.test_btn.configure(state="normal")
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_model_change(self):
        selected = self.model_var.get()
        config.GEMINI_MODEL = selected
        gemini_client.GEMINI_MODEL = selected
        gemini_client._model = None
        update_env_file("GEMINI_MODEL", selected)

    def _on_tts_toggle(self):
        val = self.tts_enabled_var.get()
        config.TTS_ENABLED = val
        voice.TTS_ENABLED = val
        update_env_file("DISHA_TTS_ENABLED", "true" if val else "false")

    def _update_voice_desc(self):
        profile = voice.get_active_voice_profile()
        eng = "In-Memory Neural (Edge-TTS)" if profile.get("engine") == "neural" else "Windows SAPI5 (Offline Local)"
        model_str = f" • Local Weights: {profile['model_file']}" if profile.get("model_file") else ""
        self.voice_desc_lbl.configure(
            text=f"Engine: {eng}{model_str}",
            fg="#38bdf8",
        )

    def _on_voice_profile_change(self, event=None):
        selected_name = self.voice_var.get()
        matched_id = "egirl"
        for p_id, p_info in config.VOICE_PROFILES.items():
            if p_info["name"] == selected_name or p_id == selected_name:
                matched_id = p_id
                break

        voice.set_voice_profile(matched_id)
        update_env_file("DISHA_VOICE_PROFILE", matched_id)
        update_env_file("DISHA_TTS_ENGINE", config.TTS_ENGINE)
        if config.TTS_NEURAL_VOICE:
            update_env_file("DISHA_TTS_NEURAL_VOICE", config.TTS_NEURAL_VOICE)
        update_env_file("DISHA_TTS_VOICE", config.TTS_VOICE_GENDER)
        self._update_voice_desc()

    def _test_voice(self):
        profile = voice.get_active_voice_profile()
        p_id = profile.get("id", "egirl")
        user = getattr(config, "USER_NAME", "Sudhan")

        def _speak():
            if p_id == "egirl":
                sample = f"Hey {user}! The E-Girl voice model is active. How do I sound?"
            elif p_id == "jenny":
                sample = f"Hello {user}, Jenny Neural is configured and ready to assist you."
            elif p_id == "guy":
                sample = f"Hey {user}, Guy Neural is configured and ready."
            elif p_id == "aria":
                sample = f"Hello {user}, Aria Neural assistant voice is online."
            elif p_id == "zira":
                sample = f"Hello {user}, Windows Zira offline voice is active."
            elif p_id == "david":
                sample = f"Hello {user}, Windows David offline voice is active."
            else:
                sample = f"Hello {user}, your voice settings are working properly."
            voice.speak(sample, wait=False)

        threading.Thread(target=_speak, daemon=True).start()

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass


def open_settings_dialog(parent: tk.Toplevel, on_close: Optional[Callable] = None) -> DishaSettingsDialog:
    """Helper to open the modal settings dialog."""
    return DishaSettingsDialog(parent, on_close=on_close)
