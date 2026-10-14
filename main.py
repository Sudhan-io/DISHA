"""
DISHA - Desktop Companion (v2)
Features:
- Floating Desktop Logo Widget (draggable anywhere on screen)
- Interactive Overlay Card with Scrollable Chat History
- Real-time Speech Transcription (shows live text as you speak)
- Streaming AI Responses (real-time token updates in chat)
- Voice Dismissal: Say or type "go", "exit", "bye", "close" to dismiss
- Wake Word Detection: Hands-free trigger ("hey disha")
- Dual Input Modes: Hotkey Ctrl+Alt+V (voice) / Ctrl+Alt+D (text) / Tray / Floating Widget click
- Dynamic Start Menu App Discovery + Fuzzy Matching
- Offline deterministic brain (time, date, battery, RAM, CPU, math, etc.)
- Reminders & timers scheduling engine
"""

import socket
import sys
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from typing import Optional, Callable

import pystray
from PIL import Image, ImageDraw, ImageTk, ImageOps
from pynput import keyboard

from config import APP_NAME, HOTKEY, VOICE_HOTKEY, ICON_PATH, WAKE_WORD_ENABLED, WEB_ENABLED, WEB_PORT
import gemini_client
import memory
import app_launcher
import local_brain
import scheduler
import voice
import usb_guard
import web_interface
import settings_dialog

# ---------------------------------------------------------------------------
# Single-instance guard with IPC activation
# ---------------------------------------------------------------------------
_LOCK_PORT = 54321
_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def acquire_single_instance_lock(on_activate: Optional[Callable] = None) -> bool:
    """
    Acquires single-instance lock on 127.0.0.1:54321.
    If another instance is already running, sends 'ACTIVATE' to wake and focus
    the existing assistant window, then returns False to let this instance exit.
    If this is the primary instance, listens for activation signals.
    """
    global _lock_socket
    try:
        _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
        _lock_socket.listen(5)

        if on_activate:
            def _listen_loop():
                while True:
                    try:
                        conn, _ = _lock_socket.accept()
                        data = conn.recv(1024).decode("utf-8", errors="ignore").strip()
                        conn.close()
                        if data == "ACTIVATE":
                            on_activate()
                    except Exception:
                        break

            threading.Thread(target=_listen_loop, daemon=True).start()

        return True
    except OSError:
        # Another instance is already holding the lock! Ping it to activate/show window.
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(1.5)
            client.connect(("127.0.0.1", _LOCK_PORT))
            client.sendall(b"ACTIVATE\n")
            client.close()
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Exit Triggers ("go", "bye", "exit", "close", etc.)
# ---------------------------------------------------------------------------
EXIT_WORDS = {
    "go", "go away", "bye", "goodbye", "exit", "close", "dismiss",
    "hide", "stop", "shut up", "bye bye", "see ya", "later", "quit", "minimize"
}

VOICE_STOP_PHRASES = (
    "stop voice", "exit voice", "disable voice", "turn off voice",
    "stop listening", "cancel voice", "quit voice", "end voice"
)


def is_exit_command(text: str) -> bool:
    cleaned = text.strip().lower().rstrip(".!")
    return cleaned in EXIT_WORDS


# ---------------------------------------------------------------------------
# Routing logic (Multi-tier: System/Apps -> Reminders -> Local Brain -> Vision -> Gemini)
# ---------------------------------------------------------------------------

def is_screen_query(text: str) -> bool:
    t = text.lower().strip()
    keywords = [
        "what's on my screen", "whats on my screen", "what is on my screen",
        "on my screen", "look at my screen", "see my screen", "read my screen",
        "check my screen", "analyze my screen", "describe my screen",
        "what am i looking at", "can you see my screen", "take a look at my screen",
        "screenshot", "what do you see", "what do u see", "what's open", "whats open"
    ]
    return any(k in t for k in keywords)


def route_request(user_input: str, on_chunk: Optional[Callable[[str], None]] = None) -> str:
    # 0. Extract and persist facts
    memory.extract_and_store_facts(user_input)

    # 1. Try local command (app open/close, system controls) — always offline
    local_response = app_launcher.try_local_command(user_input)
    if local_response is not None:
        memory.log_exchange(user_input, local_response)
        return local_response

    # 2. Try scheduler commands (reminders, timers) — always offline
    sched_response = scheduler.try_schedule_command(user_input)
    if sched_response is not None:
        memory.log_exchange(user_input, sched_response)
        return sched_response

    # 3. Try local brain (date, time, battery, math, wifi, ram, gpu, disk) — always offline
    brain_response = local_brain.try_answer(user_input)
    if brain_response is not None:
        memory.log_exchange(user_input, brain_response)
        return brain_response

    # 4. Check for screen awareness / vision queries (real desktop capture)
    if is_screen_query(user_input):
        vision_reply = gemini_client.ask_with_screenshot(user_input)
        memory.log_exchange(user_input, vision_reply)
        return vision_reply

    # 5. Gemini (online) with streaming or graceful offline message
    context = memory.get_recent_context()
    if on_chunk is not None:
        answer = gemini_client.ask_streaming(user_input, context, on_chunk=on_chunk)
    else:
        answer = gemini_client.ask(user_input, context)
    memory.log_exchange(user_input, answer)
    return answer


# ---------------------------------------------------------------------------
# Screen Helper
# ---------------------------------------------------------------------------

def center_window(win, width: int, height: int):
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 3)
    win.geometry(f"{width}x{height}+{x}+{y}")


# ---------------------------------------------------------------------------
# DISHA Interactive Overlay Window
# ---------------------------------------------------------------------------
_assistant_window = None


_assistant_window = None


def _load_circle_icon(size: tuple[int, int]) -> Optional[ImageTk.PhotoImage]:
    """Helper to load assets/icon.png with a clean anti-aliased circular alpha mask."""
    if not ICON_PATH.exists():
        return None
    try:
        im = Image.open(ICON_PATH).convert("RGBA")
        im_resized = im.resize(size, Image.Resampling.LANCZOS)
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size[0], size[1]), fill=255)
        im_circle = ImageOps.fit(im_resized, mask.size, centering=(0.5, 0.5))
        im_circle.putalpha(mask)
        return ImageTk.PhotoImage(im_circle)
    except Exception:
        return None


class DishaAssistantWindow:
    """
    Sleek, futuristic desktop companion window with dark obsidian glassmorphism,
    message card feed, audio visualizer, quick action chips, and custom dark scrollbars.
    """

    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.title("DISHA AI Companion")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#0b0d14")
        center_window(self.win, 560, 620)

        self._drag_data = {"x": 0, "y": 0}
        self._current_stream_mark = None
        self._animating_vis = False
        self._vis_phase = 0
        self._voice_mode_active = False
        self._is_maximized = False
        self._prev_geom = None

        self._init_styles()
        self._build_ui()
        self.win.bind("<Escape>", lambda e: self.close())

    def _init_styles(self):
        try:
            style = ttk.Style()
            style.theme_use("clam")
            style.configure(
                "Dark.Vertical.TScrollbar",
                gripcount=0,
                background="#1e2438",
                darkcolor="#0d0f17",
                lightcolor="#0d0f17",
                troughcolor="#090b12",
                bordercolor="#090b12",
                arrowcolor="#38bdf8",
            )
            style.map(
                "Dark.Vertical.TScrollbar",
                background=[("active", "#2d3752"), ("pressed", "#3b82f6")],
            )
        except Exception:
            pass

    def _build_ui(self):
        # 1px Neon Obsidian Outer Border
        outer_border = tk.Frame(self.win, bg="#20263b", padx=1, pady=1)
        outer_border.pack(fill="both", expand=True)

        main_container = tk.Frame(outer_border, bg="#0d0f17")
        main_container.pack(fill="both", expand=True)

        # ── Header Bar ────────────────────────────────────────────────────────
        header = tk.Frame(main_container, bg="#131622", height=48)
        header.pack(fill="x", side="top")

        # App Icon + Title
        left_group = tk.Frame(header, bg="#131622")
        left_group.pack(side="left", padx=14, pady=8)

        self.header_icon = _load_circle_icon((28, 28))
        if self.header_icon:
            icon_lbl = tk.Label(left_group, image=self.header_icon, bg="#131622")
            icon_lbl.pack(side="left", padx=(0, 10))

        brand_frame = tk.Frame(left_group, bg="#131622")
        brand_frame.pack(side="left")

        title_lbl = tk.Label(
            brand_frame,
            text="DISHA",
            bg="#131622",
            fg="#f8fafc",
            font=("Segoe UI", 12, "bold"),
        )
        title_lbl.pack(side="left")

        tag_lbl = tk.Label(
            brand_frame,
            text=" HYBRID AI",
            bg="#131622",
            fg="#00d2ff",
            font=("Segoe UI", 8, "bold"),
        )
        tag_lbl.pack(side="left", padx=(4, 0), pady=(3, 0))

        # Status Pill Badge in Header
        self.status_pill = tk.Label(
            header,
            text=" ● READY ",
            bg="#064e3b",
            fg="#34d399",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
            bd=0,
        )
        self.status_pill.pack(side="left", padx=12)

        # Voice Model Persona Badge in Header
        self.voice_badge = tk.Label(
            header,
            text=self._get_short_voice_name(),
            bg="#1e1b4b",
            fg="#c084fc",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
            bd=0,
            cursor="hand2",
        )
        self.voice_badge.pack(side="left", padx=(0, 8))
        self.voice_badge.bind("<Button-1>", lambda e: self.open_settings())
        self.voice_badge.bind("<Enter>", lambda e: self.voice_badge.configure(bg="#312e81"))
        self.voice_badge.bind("<Leave>", lambda e: self.voice_badge.configure(bg="#1e1b4b"))

        # ── Top-Right Header Controls ──────────────────────────────────────────
        # 1. Window Caption Buttons (Minimize, Maximize/Restore, Close)
        caption_controls = tk.Frame(header, bg="#131622")
        caption_controls.pack(side="right", fill="y", padx=0, pady=0)

        # Close Button (✕)
        self.close_btn = tk.Label(
            caption_controls,
            text=" ✕ ",
            bg="#131622",
            fg="#94a3b8",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=10,
            pady=8,
        )
        self.close_btn.pack(side="right", fill="y")
        self.close_btn.bind("<Button-1>", lambda e: self.close())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.configure(bg="#e11d48", fg="#ffffff"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.configure(bg="#131622", fg="#94a3b8"))

        # Maximize / Restore Button (🗖 / 🗗)
        self.max_btn = tk.Label(
            caption_controls,
            text=" 🗖 ",
            bg="#131622",
            fg="#94a3b8",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            padx=10,
            pady=8,
        )
        self.max_btn.pack(side="right", fill="y")
        self.max_btn.bind("<Button-1>", lambda e: self.toggle_maximize())
        self.max_btn.bind("<Enter>", lambda e: self.max_btn.configure(bg="#262b3d", fg="#f8fafc"))
        self.max_btn.bind("<Leave>", lambda e: self.max_btn.configure(bg="#131622", fg="#94a3b8"))

        # Minimize Button (─)
        self.min_btn = tk.Label(
            caption_controls,
            text=" ─ ",
            bg="#131622",
            fg="#94a3b8",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            padx=10,
            pady=8,
        )
        self.min_btn.pack(side="right", fill="y")
        self.min_btn.bind("<Button-1>", lambda e: self.minimize())
        self.min_btn.bind("<Enter>", lambda e: self.min_btn.configure(bg="#262b3d", fg="#f8fafc"))
        self.min_btn.bind("<Leave>", lambda e: self.min_btn.configure(bg="#131622", fg="#94a3b8"))

        # Divider between tools and caption controls
        divider = tk.Frame(header, bg="#20263b", width=1, height=18)
        divider.pack(side="right", padx=(8, 6), pady=8)

        # 2. Tools (Clear chat, Settings, Voice mode)
        tools_frame = tk.Frame(header, bg="#131622")
        tools_frame.pack(side="right", padx=(0, 4))

        # Clear Chat History Button
        clear_btn = tk.Label(
            tools_frame,
            text="🗑️",
            bg="#131622",
            fg="#64748b",
            font=("Segoe UI", 10),
            cursor="hand2",
            padx=4,
            pady=6,
        )
        clear_btn.pack(side="right", padx=(0, 4))
        clear_btn.bind("<Button-1>", lambda e: self.clear_chat())
        clear_btn.bind("<Enter>", lambda e: clear_btn.configure(fg="#f59e0b"))
        clear_btn.bind("<Leave>", lambda e: clear_btn.configure(fg="#64748b"))

        # Settings Dialog Button
        settings_btn = tk.Label(
            tools_frame,
            text="⚙️",
            bg="#131622",
            fg="#94a3b8",
            font=("Segoe UI", 10),
            cursor="hand2",
            padx=4,
            pady=6,
        )
        settings_btn.pack(side="right", padx=(0, 4))
        settings_btn.bind("<Button-1>", lambda e: self.open_settings())
        settings_btn.bind("<Enter>", lambda e: settings_btn.configure(fg="#38bdf8"))
        settings_btn.bind("<Leave>", lambda e: settings_btn.configure(fg="#94a3b8"))

        # Continuous Voice Mode Toggle Chip
        self.voice_mode_btn = tk.Label(
            tools_frame,
            text="🗣️ Voice Mode",
            bg="#1c1929",
            fg="#c084fc",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
            cursor="hand2",
            bd=0,
        )
        self.voice_mode_btn.pack(side="right", padx=(0, 6))
        self.voice_mode_btn.bind("<Button-1>", lambda e: self.toggle_voice_mode())
        self.voice_mode_btn.bind("<Enter>", lambda e: self.voice_mode_btn.configure(bg="#2e1065") if not self._voice_mode_active else None)
        self.voice_mode_btn.bind("<Leave>", lambda e: self.voice_mode_btn.configure(bg="#1c1929") if not self._voice_mode_active else None)

        # Drag bindings
        for widget in (header, left_group, brand_frame, title_lbl, tag_lbl):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)

        # ── Glowing Voice Waveform / Visualizer Line ──────────────────────────
        self.vis_canvas = tk.Canvas(main_container, height=4, bg="#131622", highlightthickness=0)
        self.vis_canvas.pack(fill="x")
        self._draw_visualizer(active=False)

        # ── Scrollable Chat Feed ──────────────────────────────────────────────
        chat_frame = tk.Frame(main_container, bg="#0d0f17")
        chat_frame.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        scrollbar = ttk.Scrollbar(chat_frame, orient="vertical", style="Dark.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")

        self.chat_text = tk.Text(
            chat_frame,
            bg="#0d0f17",
            fg="#e2e8f0",
            insertbackground="#00d2ff",
            selectbackground="#252c42",
            font=("Segoe UI", 10),
            wrap="word",
            padx=14,
            pady=12,
            bd=0,
            highlightthickness=0,
            yscrollcommand=scrollbar.set,
            state=tk.DISABLED,
        )
        self.chat_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.chat_text.yview)

        # Style tags for card bubbles
        self.chat_text.tag_configure("badge_user", foreground="#818cf8", font=("Segoe UI", 9, "bold"), lmargin1=10, lmargin2=10)
        self.chat_text.tag_configure("text_user", foreground="#f1f5f9", font=("Segoe UI", 10), lmargin1=10, lmargin2=10, rmargin=10)

        self.chat_text.tag_configure("badge_disha", foreground="#00d2ff", font=("Segoe UI", 9, "bold"), lmargin1=10, lmargin2=10)
        self.chat_text.tag_configure("text_disha", foreground="#e2e8f0", font=("Segoe UI", 10), lmargin1=10, lmargin2=10, rmargin=10)

        self.chat_text.tag_configure("badge_reminder", foreground="#f59e0b", font=("Segoe UI", 9, "bold"), lmargin1=10, lmargin2=10)
        self.chat_text.tag_configure("text_reminder", foreground="#fde68a", font=("Segoe UI", 9), lmargin1=10, lmargin2=10)

        self.chat_text.tag_configure("badge_system", foreground="#a78bfa", font=("Segoe UI", 9, "bold"), lmargin1=10, lmargin2=10)
        self.chat_text.tag_configure("text_system", foreground="#94a3b8", font=("Segoe UI", 9), lmargin1=10, lmargin2=10)

        self.chat_text.tag_configure("divider", foreground="#1e2438", font=("Segoe UI", 6))

        # Initial Welcome Message Card
        self.append_message(
            "System",
            "✨ DISHA is ready. Speak via 🎤 Listen, press Ctrl+Alt+V, or type below. Say 'bye' to exit."
        )

        # ── Quick Action Chips Ribbon ─────────────────────────────────────────
        chips_frame = tk.Frame(main_container, bg="#0d0f17")
        chips_frame.pack(fill="x", padx=12, pady=(0, 4))

        quick_actions = [
            ("🕒 Time", "what time is it"),
            ("🔋 Battery", "battery status"),
            ("💾 RAM", "how much ram is used"),
            ("📋 Clipboard", "what did i copy"),
            ("📸 Vision", "what's on my screen"),
            ("⏰ Reminders", "show my reminders"),
        ]

        for label, cmd in quick_actions:
            chip = tk.Button(
                chips_frame,
                text=label,
                bg="#161a29",
                fg="#94a3b8",
                activebackground="#20273d",
                activeforeground="#00d2ff",
                font=("Segoe UI", 8, "bold"),
                bd=0,
                padx=8,
                pady=3,
                cursor="hand2",
                command=lambda c=cmd: self.quick_submit(c),
            )
            chip.pack(side="left", padx=(0, 6))
            chip.bind("<Enter>", lambda e, b=chip: b.configure(bg="#1f253a", fg="#00d2ff"))
            chip.bind("<Leave>", lambda e, b=chip: b.configure(bg="#161a29", fg="#94a3b8"))

        # ── Status Bar & Hearing Indicator ────────────────────────────────────
        status_frame = tk.Frame(main_container, bg="#0d0f17")
        status_frame.pack(fill="x", padx=14, pady=(2, 6))

        self.status_var = tk.StringVar(value="Standby. Ready for query or voice command.")
        self.status_lbl = tk.Label(
            status_frame,
            textvariable=self.status_var,
            bg="#0d0f17",
            fg="#64748b",
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.status_lbl.pack(fill="x")

        # ── Input Dock Container ──────────────────────────────────────────────
        dock_outer = tk.Frame(main_container, bg="#1a2034", padx=1, pady=1)
        dock_outer.pack(fill="x", side="bottom", padx=12, pady=(0, 12))

        dock_inner = tk.Frame(dock_outer, bg="#131622", padx=6, pady=6)
        dock_inner.pack(fill="x")

        # Modern Entry Field
        self.placeholder_text = "Ask DISHA anything or click 🎙️..."
        self.entry = tk.Entry(
            dock_inner,
            bg="#181c2b",
            fg="#64748b",
            insertbackground="#00d2ff",
            font=("Segoe UI", 10),
            bd=0,
            relief="flat",
        )
        self.entry.insert(0, self.placeholder_text)
        self.entry.pack(side="left", fill="x", expand=True, padx=(4, 8), ipady=5)

        self.entry.bind("<FocusIn>", self._on_entry_focus_in)
        self.entry.bind("<FocusOut>", self._on_entry_focus_out)
        self.entry.bind("<Return>", lambda e: self.submit_text())

        # Glowing Mic Button
        self.mic_btn = tk.Button(
            dock_inner,
            text="🎙️ Listen",
            bg="#0ea5e9",
            fg="#ffffff",
            activebackground="#0284c7",
            font=("Segoe UI", 9, "bold"),
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.start_listening,
        )
        self.mic_btn.pack(side="left", padx=(0, 6))

        # Send Button
        send_btn = tk.Button(
            dock_inner,
            text="➤ Send",
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1d4ed8",
            font=("Segoe UI", 9, "bold"),
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.submit_text,
        )
        send_btn.pack(side="left")

    def _draw_visualizer(self, active: bool = False):
        self.vis_canvas.delete("all")
        w = self.vis_canvas.winfo_width() or 550
        if not active:
            self.vis_canvas.create_line(0, 2, w, 2, fill="#1e2438", width=2)
            self.vis_canvas.create_line(w // 2 - 40, 2, w // 2 + 40, 2, fill="#00d2ff", width=2)
        else:
            colors = ["#00d2ff", "#38bdf8", "#818cf8", "#a855f7", "#ec4899", "#38bdf8", "#00d2ff"]
            seg = w / len(colors)
            for i, col in enumerate(colors):
                h = 1 + (i % 3) * 1.5
                self.vis_canvas.create_line(i * seg, 2, (i + 1) * seg, 2, fill=col, width=int(h) + 1)

    def _on_entry_focus_in(self, event):
        if self.entry.get() == self.placeholder_text:
            self.entry.delete(0, tk.END)
            self.entry.configure(fg="#f8fafc")

    def _on_entry_focus_out(self, event):
        if not self.entry.get().strip():
            self.entry.insert(0, self.placeholder_text)
            self.entry.configure(fg="#64748b")

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_drag(self, event):
        deltax = event.x - self._drag_data["x"]
        deltay = event.y - self._drag_data["y"]
        x = self.win.winfo_x() + deltax
        y = self.win.winfo_y() + deltay
        self.win.geometry(f"+{x}+{y}")

    def append_message(self, role: str, text: str):
        """Append formatted card bubble into chat history."""
        self.chat_text.configure(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%I:%M %p")

        if role == "You":
            self.chat_text.insert(tk.END, f"👤 You  •  {timestamp}\n", "badge_user")
            self.chat_text.insert(tk.END, f"{text}\n\n", "text_user")
        elif role == "DISHA":
            self.chat_text.insert(tk.END, f"✨ DISHA  •  {timestamp}\n", "badge_disha")
            self.chat_text.insert(tk.END, f"{text}\n\n", "text_disha")
        elif "Reminder" in role or "Timer" in text:
            self.chat_text.insert(tk.END, f"🔔 REMINDER  •  {timestamp}\n", "badge_reminder")
            self.chat_text.insert(tk.END, f"{text}\n\n", "text_reminder")
        else:
            self.chat_text.insert(tk.END, f"ℹ️ System  •  {timestamp}\n", "badge_system")
            self.chat_text.insert(tk.END, f"{text}\n\n", "text_system")

        self.chat_text.insert(tk.END, "─" * 46 + "\n\n", "divider")
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def append_streaming_chunk(self, accumulated_text: str):
        """Stream response tokens into the chat widget in real time."""
        self.chat_text.configure(state=tk.NORMAL)
        if self._current_stream_mark is None:
            timestamp = datetime.now().strftime("%I:%M %p")
            self.chat_text.insert(tk.END, f"✨ DISHA  •  {timestamp}\n", "badge_disha")
            self.chat_text.mark_set("stream_mark", "end-1c")
            self.chat_text.mark_gravity("stream_mark", tk.LEFT)
            self._current_stream_mark = True

        self.chat_text.delete("stream_mark", "end-1c")
        self.chat_text.insert("stream_mark", accumulated_text, "text_disha")
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def finish_streaming(self):
        """Reset streaming marker and insert divider."""
        if self._current_stream_mark is not None:
            self.chat_text.configure(state=tk.NORMAL)
            self.chat_text.insert(tk.END, "\n\n")
            self.chat_text.insert(tk.END, "─" * 46 + "\n\n", "divider")
            self.chat_text.configure(state=tk.DISABLED)
            self.chat_text.see(tk.END)
        self._current_stream_mark = None

    def clear_chat(self):
        """Wipe conversation history and show clean welcome banner."""
        self.chat_text.configure(state=tk.NORMAL)
        self.chat_text.delete("1.0", tk.END)
        self.chat_text.configure(state=tk.DISABLED)
        self.append_message("System", "Chat history cleared. How can I help you?")

    def set_status(self, text: str):
        self.status_var.set(text)

    def set_listening_indicator(self, active: bool):
        if active:
            self.status_pill.configure(text=" ● LISTENING... ", bg="#881337", fg="#fb7185")
            self.mic_btn.configure(text="🔴 Listening...", bg="#f43f5e")
            self._draw_visualizer(active=True)
        else:
            self.status_pill.configure(text=" ● READY ", bg="#064e3b", fg="#34d399")
            self.mic_btn.configure(text="🎙️ Listen", bg="#0ea5e9")
            self._draw_visualizer(active=False)

    def focus_text_input(self):
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.entry.focus_set()
        if self.entry.get() == self.placeholder_text:
            self.entry.delete(0, tk.END)
            self.entry.configure(fg="#f8fafc")

    def quick_submit(self, query: str):
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.entry.delete(0, tk.END)
        self.entry.insert(0, query)
        self.entry.configure(fg="#f8fafc")
        self.submit_text()

    def start_listening(self):
        if voice.is_listening():
            return
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.set_listening_indicator(True)
        self.set_status("🎤 Listening for speech...")

        def on_partial(text):
            if text:
                self.root.after(0, lambda t=text: self.set_status(f"🎤 Hearing: {t}"))

        def worker():
            try:
                heard = voice.listen(on_partial=on_partial)
            except RuntimeError as e:
                self.root.after(0, lambda: (
                    self.set_listening_indicator(False),
                    self.set_status(f"Microphone error: {e}")
                ))
                return

            self.root.after(0, lambda: self.set_listening_indicator(False))

            if not heard:
                self.root.after(0, lambda: self.set_status("Didn't catch that. Click 🎙️ Listen or type above."))
                return

            if is_exit_command(heard):
                self.root.after(0, lambda: (
                    self.append_message("You", heard),
                    self.append_message("DISHA", "Goodbye!"),
                    self.set_status("Goodbye!")
                ))
                voice.speak("Goodbye!", wait=True)
                self.root.after(500, self.close)
                return

            self.root.after(0, lambda: (
                self.append_message("You", heard),
                self.set_status("Thinking...")
            ))

            streamed = [False]

            def on_stream(chunk_text):
                streamed[0] = True
                self.root.after(0, lambda t=chunk_text: self.append_streaming_chunk(t))

            answer = route_request(heard, on_chunk=on_stream)
            if not streamed[0]:
                self.root.after(0, lambda: self.append_message("DISHA", answer))
            else:
                self.root.after(0, self.finish_streaming)

            self.root.after(0, lambda: self.set_status("Ready."))
            voice.speak(answer, wait=False)

        threading.Thread(target=worker, daemon=True).start()

    def submit_text(self):
        query = self.entry.get().strip()
        if not query or query == self.placeholder_text:
            return
        self.entry.delete(0, tk.END)

        if is_exit_command(query):
            self.append_message("You", query)
            self.append_message("DISHA", "Goodbye!")
            self.set_status("Goodbye!")
            voice.speak("Goodbye!", wait=True)
            self.close()
            return

        self.append_message("You", query)
        self.status_pill.configure(text=" ● THINKING... ", bg="#3b0764", fg="#c084fc")
        self.set_status("Thinking...")

        def worker():
            streamed = [False]

            def on_stream(chunk_text):
                streamed[0] = True
                self.root.after(0, lambda t=chunk_text: self.append_streaming_chunk(t))

            answer = route_request(query, on_chunk=on_stream)
            if not streamed[0]:
                self.root.after(0, lambda: self.append_message("DISHA", answer))
            else:
                self.root.after(0, self.finish_streaming)

            self.root.after(0, lambda: (
                self.set_listening_indicator(False),
                self.set_status("Ready.")
            ))
            voice.speak(answer, wait=False)

        threading.Thread(target=worker, daemon=True).start()

    def _get_short_voice_name(self) -> str:
        """Return formatted voice persona name for header chip."""
        prof = voice.get_active_voice_profile()
        short = prof.get("short_name")
        if not short:
            short = prof.get("name", "Voice").split("(")[0].strip()
        return f"🔊 {short}"

    def _refresh_voice_badge(self):
        """Update header badge with current active voice persona."""
        if hasattr(self, "voice_badge"):
            self.voice_badge.configure(text=self._get_short_voice_name())

    def open_settings(self):
        """Open the interactive settings dialog to manage API keys, models, and voice."""
        settings_dialog.open_settings_dialog(self.win, on_close=self._refresh_voice_badge)

    def minimize(self):
        """Minimize assistant window to background tray and floating avatar."""
        self.win.withdraw()

    def toggle_maximize(self):
        """Toggle between centered 560x620 floating companion card and full screen."""
        if not self._is_maximized:
            self._prev_geom = self.win.geometry()
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()
            self.win.geometry(f"{sw}x{sh}+0+0")
            self._is_maximized = True
            self.max_btn.configure(text=" 🗗 ")
        else:
            if self._prev_geom:
                self.win.geometry(self._prev_geom)
            else:
                center_window(self.win, 560, 620)
            self._is_maximized = False
            self.max_btn.configure(text=" 🗖 ")

    def toggle_voice_mode(self):
        """Toggle hands-free continuous back-and-forth voice conversation mode."""
        if not self._voice_mode_active:
            self.start_voice_mode()
        else:
            self.stop_voice_mode()

    def start_voice_mode(self):
        """Start hands-free loop: listen -> answer -> speak -> auto-listen again."""
        if self._voice_mode_active:
            return
        self._voice_mode_active = True
        self.voice_mode_btn.configure(
            text="🔴 Live Voice: ON",
            bg="#86198f",
            fg="#fdf4ff",
        )
        self.status_pill.configure(
            text=" ● LIVE VOICE: LISTENING ",
            bg="#701a75",
            fg="#f472b6",
        )
        self.mic_btn.configure(text="🔴 Listening...", bg="#f43f5e")
        self._draw_visualizer(active=True)
        self.set_status("🎤 Live Voice active — listening...")
        self.append_message("System", "🎙️ Continuous Voice Mode started. Speak naturally, or say 'exit voice mode' to stop.")
        voice.speak("Voice mode started. I'm listening.", wait=False)

        def _voice_loop():
            while self._voice_mode_active:
                self.root.after(0, lambda: (
                    self.status_pill.configure(text=" ● LIVE VOICE: LISTENING ", bg="#701a75", fg="#f472b6"),
                    self.set_status("🎤 Listening... speak anytime."),
                    self.mic_btn.configure(text="🔴 Listening...", bg="#f43f5e"),
                    self._draw_visualizer(active=True)
                ))

                def on_partial(text):
                    if self._voice_mode_active and text:
                        self.root.after(0, lambda t=text: self.set_status(f"🎤 Hearing: {t}"))

                try:
                    heard = voice.listen(on_partial=on_partial)
                except Exception:
                    break

                if not self._voice_mode_active:
                    break

                # If no speech was detected in this cycle, stay smoothly in listening state without flickering
                if not heard:
                    continue

                if is_exit_command(heard) or any(p in heard.lower() for p in VOICE_STOP_PHRASES):
                    self.root.after(0, lambda: (
                        self.append_message("You", heard),
                        self.append_message("DISHA", "Exiting voice mode. Have a great day!"),
                        self.stop_voice_mode()
                    ))
                    voice.speak("Exiting voice mode.", wait=True)
                    break

                self.root.after(0, lambda: (
                    self.append_message("You", heard),
                    self.status_pill.configure(text=" ● THINKING... ", bg="#3b0764", fg="#c084fc"),
                    self.set_status("Thinking...")
                ))

                streamed = [False]

                def on_stream(chunk_text):
                    streamed[0] = True
                    self.root.after(0, lambda t=chunk_text: self.append_streaming_chunk(t))

                answer = route_request(heard, on_chunk=on_stream)
                if not streamed[0]:
                    self.root.after(0, lambda: self.append_message("DISHA", answer))
                else:
                    self.root.after(0, self.finish_streaming)

                self.root.after(0, lambda: (
                    self.status_pill.configure(text=" ● LIVE VOICE: SPEAKING ", bg="#86198f", fg="#fdf4ff"),
                    self.set_status("Speaking reply...")
                ))
                # Crucial: wait=True ensures DISHA finishes speaking before listening again!
                voice.speak(answer, wait=True)
                self.root.after(0, lambda: self.set_status("Listening for follow-up..."))

        threading.Thread(target=_voice_loop, daemon=True).start()

    def stop_voice_mode(self):
        """Halt continuous voice loop and restore standard ready state."""
        self._voice_mode_active = False
        voice.cancel_listen()
        self.voice_mode_btn.configure(
            text="🗣️ Voice Mode",
            bg="#1c1929",
            fg="#c084fc",
        )
        self.set_listening_indicator(False)
        self.set_status("Ready.")

    def minimize(self):
        """Minimize companion window cleanly to system tray."""
        try:
            self.win.withdraw()
        except Exception:
            pass

    def toggle_maximize(self):
        """Toggle between centered companion window and maximized desktop work area."""
        if not self._is_maximized:
            self._prev_geom = (
                self.win.winfo_x(),
                self.win.winfo_y(),
                self.win.winfo_width(),
                self.win.winfo_height(),
            )
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()
            # Maximize leaving space for taskbar
            self.win.geometry(f"{sw}x{sh - 48}+0+0")
            self._is_maximized = True
            if hasattr(self, "max_btn"):
                self.max_btn.configure(text=" 🗗 ")
        else:
            if self._prev_geom and self._prev_geom[2] > 100:
                x, y, w, h = self._prev_geom
                self.win.geometry(f"{w}x{h}+{x}+{y}")
            else:
                center_window(self.win, 560, 620)
            self._is_maximized = False
            if hasattr(self, "max_btn"):
                self.max_btn.configure(text=" 🗖 ")

    def close(self):
        voice.cancel_listen()
        if self._voice_mode_active:
            self.stop_voice_mode()
        try:
            self.win.withdraw()
        except Exception:
            pass


def open_or_focus_assistant(root, mode: str = "voice"):
    global _assistant_window
    if _assistant_window is None or not tk.Toplevel.winfo_exists(_assistant_window.win):
        _assistant_window = DishaAssistantWindow(root)
    else:
        _assistant_window.win.deiconify()
        _assistant_window.win.attributes("-topmost", True)

    if mode == "voice":
        _assistant_window.start_listening()
    else:
        _assistant_window.focus_text_input()


# ---------------------------------------------------------------------------
# Floating Desktop Logo Widget (Luxury Floating Avatar)
# ---------------------------------------------------------------------------

class DesktopLogoWidget:
    """
    Sleek, futuristic floating desktop emblem widget.
    Renders the high-res DISHA compass & soundwave emblem with a glowing neon ring.
    Draggable anywhere on screen. Click to speak!
    """

    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#0c0e17")

        try:
            self.win.attributes("-transparentcolor", "#0c0e17")
        except Exception:
            pass

        self.size = 64
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{self.size}x{self.size}+{sw - 110}+{sh - 190}")

        self._drag_x = 0
        self._drag_y = 0
        self._moved = False
        self._tooltip = None

        self._build_widget()

    def _build_widget(self):
        self.canvas = tk.Canvas(
            self.win,
            width=self.size,
            height=self.size,
            bg="#0c0e17",
            highlightthickness=0,
            cursor="hand2",
        )
        self.canvas.pack(fill="both", expand=True)

        # Load circular masked high-res logo
        self.avatar_img = _load_circle_icon((56, 56))
        if self.avatar_img:
            self.canvas.create_image(self.size // 2, self.size // 2, image=self.avatar_img)
        else:
            pad = 6
            self.canvas.create_oval(
                pad, pad, self.size - pad, self.size - pad,
                fill="#0ea5e9", outline="#00d2ff", width=2
            )
            self.canvas.create_text(
                self.size // 2, self.size // 2,
                text="✦", fill="#ffffff", font=("Segoe UI", 18, "bold")
            )

        # Glowing Neon Ring Border
        self.ring = self.canvas.create_oval(
            3, 3, self.size - 3, self.size - 3,
            outline="#00d2ff", width=2
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)

    def _on_enter(self, event):
        self.canvas.itemconfig(self.ring, outline="#38bdf8", width=3)
        self._show_tooltip()

    def _on_leave(self, event):
        self.canvas.itemconfig(self.ring, outline="#00d2ff", width=2)
        self._hide_tooltip()

    def _show_tooltip(self):
        if self._tooltip is not None:
            return
        x = self.win.winfo_x() - 40
        y = self.win.winfo_y() - 32
        self._tooltip = tk.Toplevel(self.win)
        self._tooltip.overrideredirect(True)
        self._tooltip.attributes("-topmost", True)
        self._tooltip.configure(bg="#1e2438", padx=1, pady=1)
        self._tooltip.geometry(f"+{max(10, x)}+{max(10, y)}")

        lbl = tk.Label(
            self._tooltip,
            text="DISHA • Click to Speak",
            bg="#101422",
            fg="#00d2ff",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
        )
        lbl.pack()

    def _hide_tooltip(self):
        if self._tooltip is not None:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None

    def _on_press(self, event):
        self._drag_x = event.x
        self._drag_y = event.y
        self._moved = False
        self._hide_tooltip()

    def _on_drag(self, event):
        dx = event.x - self._drag_x
        dy = event.y - self._drag_y
        if abs(dx) > 3 or abs(dy) > 3:
            self._moved = True
        nx = self.win.winfo_x() + dx
        ny = self.win.winfo_y() + dy
        self.win.geometry(f"+{nx}+{ny}")

    def _on_release(self, event):
        if not self._moved:
            open_or_focus_assistant(self.root, mode="voice")


# ---------------------------------------------------------------------------
# System Tray Icon
# ---------------------------------------------------------------------------

def make_icon_image():
    if ICON_PATH.exists():
        try:
            return Image.open(ICON_PATH).resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (12, 14, 23, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill="#00d2ff", outline="#8b5cf6", width=2)
    return img


def build_tray_icon(root):
    def on_voice(icon, item):
        root.after(0, lambda: open_or_focus_assistant(root, mode="voice"))

    def on_text(icon, item):
        root.after(0, lambda: open_or_focus_assistant(root, mode="text"))

    def on_quit(icon, item):
        icon.stop()
        root.after(0, root.quit)

    menu_items = [
        pystray.MenuItem("Speak to DISHA (Ctrl+Alt+V)", on_voice, default=True),
        pystray.MenuItem("Type to DISHA (Ctrl+Alt+D)", on_text),
    ]

    if WEB_ENABLED:
        local_url = f"http://{web_interface.get_local_ip()}:{WEB_PORT}"
        menu_items.append(
            pystray.MenuItem(f"Copy Web URL ({local_url})", lambda icon, item: app_launcher.pyperclip.copy(local_url))
        )

    menu_items.append(pystray.MenuItem("Quit", on_quit))
    menu = pystray.Menu(*menu_items)

    tooltip = f"{APP_NAME} (Web: http://{web_interface.get_local_ip()}:{WEB_PORT})" if WEB_ENABLED else APP_NAME
    icon = pystray.Icon(APP_NAME, make_icon_image(), tooltip, menu)
    return icon


# ---------------------------------------------------------------------------
# Global Hotkey Listener
# ---------------------------------------------------------------------------

def start_hotkey_listener(root):
    def on_voice():
        root.after(0, lambda: open_or_focus_assistant(root, mode="voice"))

    def on_text():
        root.after(0, lambda: open_or_focus_assistant(root, mode="text"))

    try:
        hotkey = keyboard.GlobalHotKeys({
            VOICE_HOTKEY: on_voice,
            HOTKEY: on_text,
        })
        hotkey.start()
        return hotkey
    except Exception as e:
        print(f"Hotkey registration warning: {e}")
        return None


# ---------------------------------------------------------------------------
# Reminder trigger callback
# ---------------------------------------------------------------------------

def _fire_reminder(msg: str, root):
    """Called when scheduler triggers an alarm or reminder."""
    def show():
        open_or_focus_assistant(root, mode="text")
        is_alarm = "alarm" in msg.lower() or "timer" in msg.lower()
        tag = "⏰ ALARM" if is_alarm else "🔔 REMINDER"
        if _assistant_window:
            _assistant_window.append_message("System", f"{tag}: {msg}")
            _assistant_window.set_status(f"{tag}: {msg}")
        speech_text = f"Alarm! {msg}" if is_alarm else f"Reminder: {msg}"
        voice.speak(speech_text, wait=False)
    root.after(0, show)


# ---------------------------------------------------------------------------
# Wake Word Listener Thread
# ---------------------------------------------------------------------------

def _start_wake_word_thread(root):
    """Start hands-free wake word detection in background daemon thread."""
    if not WAKE_WORD_ENABLED:
        return None
    stop_event = threading.Event()
    voice.set_root(root)
    t = threading.Thread(
        target=lambda: voice.listen_for_wake_word(
            callback=lambda: open_or_focus_assistant(root, mode="voice"),
            stop_event=stop_event,
        ),
        daemon=True,
    )
    t.start()
    return stop_event


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Enable crisp Windows High-DPI scaling
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    root = tk.Tk()
    root.withdraw()

    # IPC Single-instance guard: if another instance tries to launch, focus this window
    def _activate_callback():
        root.after(0, lambda: open_or_focus_assistant(root, mode="text"))

    if not acquire_single_instance_lock(on_activate=_activate_callback):
        sys.exit(0)

    # USB portable mode identity verification
    if not usb_guard.check_and_verify(parent=root):
        sys.exit(0)

    # Initialize scheduler with Tk-safe trigger callback
    scheduler.init(on_trigger=lambda msg: _fire_reminder(msg, root))

    # Initialize remote web interface if enabled
    web_interface.init(route_fn=route_request)

    # Launch Desktop Floating Logo Widget
    DesktopLogoWidget(root)

    # Automatically open and focus Assistant Window on launch
    open_or_focus_assistant(root, mode="text")

    # Launch System Tray Icon
    icon = build_tray_icon(root)
    threading.Thread(target=icon.run, daemon=True).start()

    # Launch Hotkeys
    start_hotkey_listener(root)

    # Launch Wake Word listener if enabled
    _start_wake_word_thread(root)

    # Startup Voice Greeting & Web notification
    def _announce_startup():
        voice.speak(f"Hey, {APP_NAME} here. Click my icon or press Control Alt V whenever you need me.")
        if WEB_ENABLED:
            voice.speak(f"Web interface ready on port {WEB_PORT}.", wait=False)

    threading.Thread(target=_announce_startup, daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()