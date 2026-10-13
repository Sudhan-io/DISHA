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
from datetime import datetime
from typing import Optional, Callable

import pystray
from PIL import Image, ImageDraw
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

# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------
_LOCK_PORT = 54321
_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def acquire_single_instance_lock():
    try:
        _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Exit Triggers ("go", "bye", "exit", "close", etc.)
# ---------------------------------------------------------------------------
EXIT_WORDS = {"go", "go away", "bye", "goodbye", "exit", "close", "dismiss", "hide", "stop", "shut up"}


def is_exit_command(text: str) -> bool:
    cleaned = text.strip().lower().rstrip(".!")
    return cleaned in EXIT_WORDS


# ---------------------------------------------------------------------------
# Routing logic (Multi-tier: System/Apps -> Reminders -> Local Brain -> Gemini)
# ---------------------------------------------------------------------------

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

    # 3. Try local brain (date, time, battery, math, wifi, ram) — always offline
    brain_response = local_brain.try_answer(user_input)
    if brain_response is not None:
        memory.log_exchange(user_input, brain_response)
        return brain_response

    # 4. Gemini (online) with streaming or graceful offline message
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


class DishaAssistantWindow:
    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.title("DISHA Companion")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#1e1e2e")
        center_window(self.win, 520, 480)

        # Allow dragging the window by header
        self._drag_data = {"x": 0, "y": 0}
        self._current_stream_mark = None

        self._build_ui()

    def _build_ui(self):
        # Header / Title Bar
        header = tk.Frame(self.win, bg="#181825", height=40)
        header.pack(fill="x", side="top")

        title_lbl = tk.Label(
            header,
            text="✨ DISHA Desktop Companion",
            bg="#181825",
            fg="#a6e3a1",
            font=("Segoe UI", 11, "bold"),
        )
        title_lbl.pack(side="left", padx=14, pady=8)

        # Visual indicator badge (idle/listening)
        self.indicator_dot = tk.Label(
            header,
            text="● IDLE",
            bg="#181825",
            fg="#585b70",
            font=("Segoe UI", 9, "bold"),
        )
        self.indicator_dot.pack(side="left", padx=4)

        close_btn = tk.Label(
            header,
            text=" ✕ ",
            bg="#181825",
            fg="#f38ba8",
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
        )
        close_btn.pack(side="right", padx=10)
        close_btn.bind("<Button-1>", lambda e: self.close())

        header.bind("<Button-1>", self._start_drag)
        header.bind("<B1-Motion>", self._do_drag)
        title_lbl.bind("<Button-1>", self._start_drag)
        title_lbl.bind("<B1-Motion>", self._do_drag)

        # Scrollable Chat History Area
        chat_frame = tk.Frame(self.win, bg="#181825")
        chat_frame.pack(fill="both", expand=True, padx=14, pady=(10, 6))

        scrollbar = tk.Scrollbar(chat_frame, bg="#313244", troughcolor="#181825", bd=0, relief="flat")
        scrollbar.pack(side="right", fill="y")

        self.chat_text = tk.Text(
            chat_frame,
            bg="#181825",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Segoe UI", 10),
            wrap="word",
            padx=12,
            pady=10,
            bd=0,
            highlightthickness=0,
            yscrollcommand=scrollbar.set,
            state=tk.DISABLED,
        )
        self.chat_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.chat_text.yview)

        # Configure style tags for chat roles
        self.chat_text.tag_configure("time", foreground="#6c7086", font=("Segoe UI", 9))
        self.chat_text.tag_configure("role_you", foreground="#89b4fa", font=("Segoe UI", 10, "bold"))
        self.chat_text.tag_configure("role_disha", foreground="#a6e3a1", font=("Segoe UI", 10, "bold"))
        self.chat_text.tag_configure("role_system", foreground="#fab387", font=("Segoe UI", 10, "bold"))
        self.chat_text.tag_configure("msg_text", foreground="#cdd6f4", font=("Segoe UI", 10))

        # Initial welcome message in chat
        self.append_message("System", "Ready. Press 🎤 Listen, type below, or say 'bye' to exit.")

        # Status Bar (shows real-time listening/thinking state)
        status_frame = tk.Frame(self.win, bg="#1e1e2e")
        status_frame.pack(fill="x", padx=14, pady=(0, 6))

        self.status_var = tk.StringVar(value="Ready.")
        self.status_lbl = tk.Label(
            status_frame,
            textvariable=self.status_var,
            bg="#1e1e2e",
            fg="#a6adc8",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.status_lbl.pack(fill="x")

        # Input Frame (Entry + Send + Listen)
        input_frame = tk.Frame(self.win, bg="#1e1e2e")
        input_frame.pack(fill="x", side="bottom", padx=14, pady=(0, 14))

        self.entry = tk.Entry(
            input_frame,
            bg="#313244",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Segoe UI", 11),
            bd=1,
            relief="solid",
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.submit_text())

        send_btn = tk.Button(
            input_frame,
            text="Send",
            bg="#89b4fa",
            fg="#11111b",
            font=("Segoe UI", 10, "bold"),
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.submit_text,
        )
        send_btn.pack(side="left", padx=(0, 6))

        speak_btn = tk.Button(
            input_frame,
            text="🎤 Listen",
            bg="#a6e3a1",
            fg="#11111b",
            font=("Segoe UI", 10, "bold"),
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.start_listening,
        )
        speak_btn.pack(side="left")

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
        """Append formatted line [HH:MM] Role: text to scrollable history."""
        self.chat_text.configure(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%I:%M %p")
        self.chat_text.insert(tk.END, f"[{timestamp}] ", "time")
        tag_role = "role_disha" if role == "DISHA" else ("role_you" if role == "You" else "role_system")
        self.chat_text.insert(tk.END, f"{role}: ", tag_role)
        self.chat_text.insert(tk.END, f"{text}\n\n", "msg_text")
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def append_streaming_chunk(self, accumulated_text: str):
        """Stream response tokens into the chat widget in real time."""
        self.chat_text.configure(state=tk.NORMAL)
        if self._current_stream_mark is None:
            timestamp = datetime.now().strftime("%I:%M %p")
            self.chat_text.insert(tk.END, f"[{timestamp}] ", "time")
            self.chat_text.insert(tk.END, "DISHA: ", "role_disha")
            self._current_stream_mark = self.chat_text.index(f"{tk.END}-1c")
            self.chat_text.insert(tk.END, f"{accumulated_text}\n\n", "msg_text")
        else:
            self.chat_text.delete(self._current_stream_mark, tk.END)
            self.chat_text.insert(tk.END, f"{accumulated_text}\n\n", "msg_text")
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def finish_streaming(self):
        """Reset streaming marker when response finishes."""
        self._current_stream_mark = None

    def set_status(self, text: str):
        """Update status label."""
        self.status_var.set(text)

    def set_listening_indicator(self, active: bool):
        """Toggle visual listening indicator."""
        if active:
            self.indicator_dot.configure(text="● LISTENING", fg="#f38ba8")
        else:
            self.indicator_dot.configure(text="● IDLE", fg="#585b70")

    def focus_text_input(self):
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.entry.focus_set()

    def start_listening(self):
        if voice.is_listening():
            return
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.set_listening_indicator(True)
        self.set_status("🎤 Listening...")

        def on_partial(text):
            self.root.after(0, lambda: self.set_status(f"🎤 Hearing: {text}"))

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
                self.root.after(0, lambda: self.set_status("Didn't catch anything. Click 🎤 Listen or type below."))
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
                self.root.after(0, lambda: self.append_streaming_chunk(chunk_text))

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
        if not query:
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
        self.set_status("Thinking...")

        def worker():
            streamed = [False]

            def on_stream(chunk_text):
                streamed[0] = True
                self.root.after(0, lambda: self.append_streaming_chunk(chunk_text))

            answer = route_request(query, on_chunk=on_stream)
            if not streamed[0]:
                self.root.after(0, lambda: self.append_message("DISHA", answer))
            else:
                self.root.after(0, self.finish_streaming)

            self.root.after(0, lambda: self.set_status("Ready."))
            voice.speak(answer, wait=False)

        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        global _assistant_window
        _assistant_window = None
        try:
            self.win.destroy()
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
# Floating Desktop Logo Widget
# ---------------------------------------------------------------------------

class DesktopLogoWidget:
    """
    A sleek, draggable floating desktop avatar logo widget.
    Sits gracefully on your desktop. Click to open DISHA!
    """

    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#11111b")

        # Make background transparent if supported
        try:
            self.win.attributes("-transparentcolor", "#11111b")
        except Exception:
            pass

        self.size = 56
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{self.size}x{self.size}+{sw - 100}+{sh - 180}")

        self._drag_x = 0
        self._drag_y = 0
        self._moved = False

        self._build_widget()

    def _build_widget(self):
        self.canvas = tk.Canvas(
            self.win,
            width=self.size,
            height=self.size,
            bg="#11111b",
            highlightthickness=0,
            cursor="hand2",
        )
        self.canvas.pack(fill="both", expand=True)

        pad = 4
        self.canvas.create_oval(
            pad, pad, self.size - pad, self.size - pad,
            fill="#a6e3a1", outline="#89b4fa", width=2
        )
        self.canvas.create_text(
            self.size // 2, self.size // 2,
            text="D", fill="#11111b", font=("Segoe UI", 16, "bold")
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, event):
        self._drag_x = event.x
        self._drag_y = event.y
        self._moved = False

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
        return Image.open(ICON_PATH)
    img = Image.new("RGB", (64, 64), "#1e1e2e")
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill="#a6e3a1")
    draw.text((24, 22), "D", fill="#1e1e2e")
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
    """Called when scheduler triggers a reminder."""
    def show():
        open_or_focus_assistant(root, mode="text")
        if _assistant_window:
            _assistant_window.append_message("System", f"⏰ Reminder: {msg}")
        voice.speak(f"Reminder: {msg}", wait=False)
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
    # USB portable mode identity verification
    if not usb_guard.check_and_verify():
        sys.exit(0)

    if not acquire_single_instance_lock():
        sys.exit(0)

    root = tk.Tk()
    root.withdraw()

    # Initialize scheduler with Tk-safe trigger callback
    scheduler.init(on_trigger=lambda msg: _fire_reminder(msg, root))

    # Initialize remote web interface if enabled
    web_interface.init(route_fn=route_request)

    # Launch Desktop Floating Logo Widget
    DesktopLogoWidget(root)

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