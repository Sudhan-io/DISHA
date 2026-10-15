"""
DISHA — Local LLM via Ollama
Wraps Ollama's REST API for offline AI reasoning.
Only used when gemini_client.is_online() returns False.
"""

import atexit
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional
import requests

from config import OLLAMA_MODEL, OLLAMA_URL, SYSTEM_PROMPT

_ollama_process = None


def get_ollama_path() -> Optional[str]:
    """Find installed path to ollama.exe."""
    candidates = [
        Path(r"D:\Ollama\ollama.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    w = shutil.which("ollama")
    if w:
        return w
    return None


def is_ollama_running() -> bool:
    """Check if the local Ollama daemon is currently running and responding."""
    try:
        base_url = OLLAMA_URL.rsplit("/api/", 1)[0]
        res = requests.get(base_url, timeout=1.5)
        return res.status_code == 200
    except Exception:
        return False


def start_ollama() -> bool:
    """Start Ollama daemon in background if not already listening on port 11434."""
    global _ollama_process
    if is_ollama_running():
        return True
    exe = get_ollama_path()
    if not exe:
        return False
    env = os.environ.copy()
    if os.path.isdir(r"D:\Ollama\models"):
        env["OLLAMA_MODELS"] = r"D:\Ollama\models"
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        _ollama_process = subprocess.Popen(
            [exe, "serve"],
            env=env,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(0.2)
            if is_ollama_running():
                return True
    except Exception as e:
        print(f"[Ollama] Failed to start daemon: {e}")
    return is_ollama_running()


def stop_ollama() -> None:
    """Terminate Ollama daemon when DISHA exits."""
    global _ollama_process
    if _ollama_process is not None:
        try:
            _ollama_process.terminate()
            _ollama_process.wait(timeout=2)
        except Exception:
            try:
                _ollama_process.kill()
            except Exception:
                pass
        _ollama_process = None
    try:
        subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, check=False)
    except Exception:
        pass


atexit.register(stop_ollama)


def ask_local(prompt: str, context: str = "") -> str:
    """
    Call Ollama for offline reasoning.
    Returns response text or a friendly fallback message on failure.
    """
    if not is_ollama_running():
        if not start_ollama():
            return "I'm offline, and the local Ollama service is not currently running."

    try:
        full_prompt = f"{SYSTEM_PROMPT}\n\n{context}\n\nUser: {prompt}\nDISHA:" if context else f"{SYSTEM_PROMPT}\n\nUser: {prompt}\nDISHA:"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": full_prompt,
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "temperature": 0.7,
                "num_predict": 150,
            },
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=45)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("response", "").strip() or "I couldn't generate an answer."
        return f"Local AI returned error status {resp.status_code}."
    except requests.exceptions.Timeout:
        return "Local AI took too long to respond."
    except Exception as e:
        return f"Local AI error: {e}"


def ask_local_streaming(
    prompt: str,
    context: str = "",
    on_chunk: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Call Ollama with streaming tokens.
    Invokes on_chunk(partial_accumulated_text) as tokens arrive.
    """
    if not is_ollama_running():
        if not start_ollama():
            msg = "I'm offline, and the local Ollama service is not currently running."
            if on_chunk:
                on_chunk(msg)
            return msg

    try:
        full_prompt = f"{SYSTEM_PROMPT}\n\n{context}\n\nUser: {prompt}\nDISHA:" if context else f"{SYSTEM_PROMPT}\n\nUser: {prompt}\nDISHA:"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": full_prompt,
            "stream": True,
            "keep_alive": "5m",
            "options": {
                "temperature": 0.7,
                "num_predict": 150,
            },
        }

        full_response = ""
        with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=60) as resp:
            if resp.status_code != 200:
                err_msg = f"Local AI returned error {resp.status_code}."
                if on_chunk:
                    on_chunk(err_msg)
                return err_msg

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk_obj = json.loads(line)
                    chunk_text = chunk_obj.get("response", "")
                    if chunk_text:
                        full_response += chunk_text
                        if on_chunk:
                            on_chunk(full_response)
                    if chunk_obj.get("done", False):
                        break
                except Exception:
                    continue

        return full_response.strip() or "I couldn't generate an answer."
    except Exception as e:
        err = f"Local AI error: {e}"
        if on_chunk:
            on_chunk(err)
        return err
