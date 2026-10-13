"""
DISHA — USB Guard
When USB_MODE=true in .env or DISHA_USB_MODE=true in env, enforces device identity verification.
Generates a device_id.txt on first run. On subsequent runs from USB,
shows a PIN prompt before allowing DISHA to start.
"""

import os
import time
import uuid
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from config import USB_MODE, DEVICE_ID_FILE, BASE_DIR


def is_usb_mode() -> bool:
    """Check if USB mode is active via config or environment variable."""
    return USB_MODE or os.getenv("DISHA_USB_MODE", "false").lower() == "true"


def check_and_verify(parent: tk.Tk | None = None) -> bool:
    """
    Returns True if OK to proceed, False to abort startup.
    If USB mode is disabled, returns True immediately.
    If device_id.txt doesn't exist, creates it and shows first-run PIN.
    If it exists, displays PIN prompt (3 attempts before 30s lockout).
    """
    if not is_usb_mode():
        return True

    # First run on this drive
    if not DEVICE_ID_FILE.exists():
        device_id = str(uuid.uuid4()).replace("-", "").upper()
        try:
            DEVICE_ID_FILE.write_text(device_id, encoding="utf-8")
        except OSError as e:
            print(f"[USB Guard] Failed to write device ID: {e}")
            return False

        _show_first_run_dialog(device_id, parent=parent)
        return True

    # Subsequent run: verify PIN
    try:
        device_id = DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError as e:
        print(f"[USB Guard] Failed to read device ID: {e}")
        return False

    pin = device_id[-6:].upper()
    return _show_pin_prompt(pin, parent=parent)


def _show_first_run_dialog(device_id: str, parent: tk.Tk | None = None) -> None:
    """Show the device ID and PIN on first USB run."""
    created_root = False
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        created_root = True
    else:
        root = parent

    pin = device_id[-6:].upper()
    msg = (
        "DISHA Portable Mode — First Run\n\n"
        f"Your Device PIN is: {pin}\n\n"
        "You will need this PIN each time DISHA launches from this USB drive.\n"
        "Please write it down safely!"
    )
    messagebox.showinfo("DISHA — First Run Verification", msg, parent=root if not created_root else None)

    if created_root:
        root.destroy()


def _show_pin_prompt(correct_pin: str, parent: tk.Tk | None = None) -> bool:
    """
    Show dark-themed PIN entry dialog.
    Allows 3 attempts. On 3 failures, initiates a 30s lockout countdown.
    Returns True on success, False if user cancels or closes window.
    """
    created_root = False
    if parent is None:
        root = tk.Tk()
        created_root = True
    else:
        root = tk.Toplevel(parent)

    root.title("DISHA — Security Unlock")
    root.configure(bg="#1e1e2e")
    root.resizable(False, False)

    # Center dialog on screen
    w, h = 380, 290
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.attributes("-topmost", True)

    verified = [False]
    attempts_left = [3]
    lockout_remaining = [0]

    # Title label
    lbl_title = tk.Label(
        root,
        text="DISHA USB PORTABLE",
        font=("Segoe UI", 12, "bold"),
        fg="#89b4fa",
        bg="#1e1e2e",
    )
    lbl_title.pack(pady=(18, 4))

    lbl_sub = tk.Label(
        root,
        text="Enter 6-character PIN to unlock:",
        font=("Segoe UI", 10),
        fg="#cdd6f4",
        bg="#1e1e2e",
    )
    lbl_sub.pack(pady=(0, 12))

    # PIN input field
    pin_entry = tk.Entry(
        root,
        font=("Consolas", 18, "bold"),
        justify="center",
        show="●",
        width=10,
        bg="#313244",
        fg="#a6e3a1",
        insertbackground="#a6e3a1",
        relief="flat",
        bd=4,
    )
    pin_entry.pack(pady=6)
    pin_entry.focus_set()

    # Feedback / attempts label
    lbl_status = tk.Label(
        root,
        text="3 attempts remaining",
        font=("Segoe UI", 9),
        fg="#a6adc8",
        bg="#1e1e2e",
    )
    lbl_status.pack(pady=6)

    def update_lockout():
        if lockout_remaining[0] > 0:
            lbl_status.config(
                text=f"Locked out. Try again in {lockout_remaining[0]}s...",
                fg="#f38ba8",
            )
            lockout_remaining[0] -= 1
            root.after(1000, update_lockout)
        else:
            attempts_left[0] = 3
            pin_entry.config(state="normal")
            btn_unlock.config(state="normal")
            lbl_status.config(text="3 attempts remaining", fg="#a6adc8")
            pin_entry.delete(0, tk.END)
            pin_entry.focus_set()

    def do_unlock():
        if lockout_remaining[0] > 0:
            return

        entered = pin_entry.get().strip().upper()
        if entered == correct_pin.upper():
            verified[0] = True
            root.destroy()
            return

        # Wrong PIN entered
        attempts_left[0] -= 1
        pin_entry.delete(0, tk.END)

        if attempts_left[0] <= 0:
            lockout_remaining[0] = 30
            pin_entry.config(state="disabled")
            btn_unlock.config(state="disabled")
            update_lockout()
        else:
            lbl_status.config(
                text=f"Incorrect PIN! {attempts_left[0]} attempt{'s' if attempts_left[0] > 1 else ''} left.",
                fg="#f38ba8",
            )

    def do_cancel():
        root.destroy()

    # Button frame
    btn_frame = tk.Frame(root, bg="#1e1e2e")
    btn_frame.pack(pady=(14, 10))

    btn_unlock = tk.Button(
        btn_frame,
        text="Unlock",
        command=do_unlock,
        font=("Segoe UI", 10, "bold"),
        bg="#a6e3a1",
        fg="#11111b",
        activebackground="#94e2d5",
        relief="flat",
        padx=16,
        pady=4,
        cursor="hand2",
    )
    btn_unlock.pack(side="left", padx=8)

    btn_cancel = tk.Button(
        btn_frame,
        text="Cancel",
        command=do_cancel,
        font=("Segoe UI", 10),
        bg="#45475a",
        fg="#cdd6f4",
        activebackground="#585b70",
        relief="flat",
        padx=12,
        pady=4,
        cursor="hand2",
    )
    btn_cancel.pack(side="left", padx=8)

    pin_entry.bind("<Return>", lambda e: do_unlock())
    root.bind("<Escape>", lambda e: do_cancel())

    root.protocol("WM_DELETE_WINDOW", do_cancel)

    if created_root:
        root.mainloop()
    else:
        root.wait_window()

    return verified[0]
