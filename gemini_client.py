"""
DISHA - Gemini Client
Single abstraction point for calling Gemini. Everything else in the app
talks to ask() / ask_streaming() and never touches the API directly.
Supports real-time token streaming and dynamic personalization from facts.
"""

import socket
from typing import Callable, Optional
import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, SYSTEM_PROMPT
import memory

import config
_model = None


def _get_api_key() -> str:
    """Retrieve active API key from config or module attribute dynamically."""
    return getattr(config, "GEMINI_API_KEY", "") or globals().get("GEMINI_API_KEY", "")


def _get_model_name() -> str:
    """Retrieve active Gemini model name from config or module attribute dynamically."""
    return getattr(config, "GEMINI_MODEL", "") or globals().get("GEMINI_MODEL", "gemini-2.5-flash")


def _build_system_prompt() -> str:
    """Personalize the system prompt using saved facts (e.g. user_name) or config USER_NAME."""
    user_name = memory.get_fact("user_name", "") or getattr(config, "USER_NAME", "Sudhan")
    fact_context = f"User's name: {user_name}. " if user_name else ""
    return fact_context + getattr(config, "SYSTEM_PROMPT", SYSTEM_PROMPT)


def _get_model():
    key = _get_api_key()
    genai.configure(api_key=key)
    model_name = _get_model_name()
    if model_name == "local-ollama" or model_name.startswith("local-"):
        model_name = "gemini-3.5-flash-lite"
    return genai.GenerativeModel(
        model_name=model_name,
        system_instruction=_build_system_prompt(),
    )


_last_online_check = 0.0
_last_online_status = False


def is_online(timeout: float = 1.5, force: bool = False) -> bool:
    """Quick, reliable connectivity check with 2.5s caching to eliminate socket thrashing."""
    global _last_online_check, _last_online_status
    import time
    now = time.monotonic()
    if not force and (now - _last_online_check) < 2.5:
        return _last_online_status

    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 443), ("8.8.8.8", 53)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((host, port))
            _last_online_check = now
            _last_online_status = True
            return True
        except OSError:
            continue

    _last_online_check = now
    _last_online_status = False
    return False


def _sanitize_error(e: Exception) -> str:
    """Ensure raw API keys or internal secrets never leak in error messages."""
    import re
    msg = str(e)
    # Check both config and module-level keys
    for k in (getattr(config, "GEMINI_API_KEY", ""), globals().get("GEMINI_API_KEY", "")):
        if k and k in msg:
            msg = msg.replace(k, "[REDACTED_API_KEY]")
    # Also strip any stray Google API key format (AIza...)
    msg = re.sub(r"AIza[0-9A-Za-z-_]{16,45}", "[REDACTED_API_KEY]", msg)
    return msg


def ask(prompt: str, context: str = "") -> str:
    """
    Send a prompt to Gemini and return DISHA's reply as plain text.
    When offline or when local-ollama is selected, seamlessly routes to local_llm (Ollama).
    """
    model_name = _get_model_name()
    if model_name == "local-ollama" or model_name.startswith("local-"):
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local(prompt, context)
        return (
            "🛡️ Local Ollama is selected as your primary engine, but the Ollama service is not running on http://127.0.0.1:11434.\n\n"
            "Please start Ollama on your PC, or open Settings (⚙️) to switch to Gemini 3.5 Flash Lite."
        )

    if not is_online():
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local(prompt, context)
        return "I'm offline right now, and the local Ollama service is not running. Reconnect or start Ollama."

    api_key = _get_api_key()
    if not api_key:
        return "I don't have an API key set up yet — add one to your .env file or open Settings (⚙️)."

    try:
        model = _get_model()
        full_prompt = f"{context}\n\nUser: {prompt}" if context else prompt
        response = model.generate_content(full_prompt, request_options={"timeout": 20.0})
        return response.text.strip() if response.text else "I didn't get a response back — try rephrasing?"
    except Exception as e:
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local(prompt, context)
        err = _sanitize_error(e)
        if "429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower():
            return "Gemini quota limit reached (429). Please update your API key in Settings (⚙️) or launch Ollama for offline local inference."
        return f"Something went wrong reaching Gemini: {err}"


def ask_streaming(prompt: str, context: str = "", on_chunk: Optional[Callable[[str], None]] = None) -> str:
    """
    Like ask(), but calls on_chunk(partial_accumulated_text) as tokens arrive.
    When offline or when local-ollama is selected, streams from local_llm (Ollama).
    Falls back to non-streaming ask() if on_chunk is None.
    """
    if on_chunk is None:
        return ask(prompt, context)

    model_name = _get_model_name()
    if model_name == "local-ollama" or model_name.startswith("local-"):
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local_streaming(prompt, context, on_chunk=on_chunk)
        msg = (
            "🛡️ Local Ollama is selected as your primary engine, but the Ollama service is not running on http://127.0.0.1:11434.\n\n"
            "Please start Ollama on your PC, or open Settings (⚙️) to switch to Gemini 3.5 Flash Lite."
        )
        on_chunk(msg)
        return msg

    if not is_online():
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local_streaming(prompt, context, on_chunk=on_chunk)
        msg = "I'm offline right now, and the local Ollama service is not running. Reconnect or start Ollama."
        on_chunk(msg)
        return msg

    api_key = _get_api_key()
    if not api_key:
        msg = "I don't have an API key set up yet — add one to your .env file or open Settings (⚙️)."
        on_chunk(msg)
        return msg

    try:
        model = _get_model()
        full_prompt = f"{context}\n\nUser: {prompt}" if context else prompt
        response = model.generate_content(full_prompt, stream=True, request_options={"timeout": 20.0})
        accumulated = []
        for chunk in response:
            if chunk.text:
                accumulated.append(chunk.text)
                on_chunk("".join(accumulated))
        result = "".join(accumulated).strip()
        return result if result else "I didn't get a response back — try rephrasing?"
    except Exception as e:
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local_streaming(prompt, context, on_chunk=on_chunk)
        err = _sanitize_error(e)
        if "429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower():
            msg = "Gemini quota limit reached (429). Please update your API key in Settings (⚙️) or launch Ollama for offline local inference."
        else:
            msg = f"Something went wrong reaching Gemini: {err}"
        on_chunk(msg)
        return msg


def ask_with_screenshot(prompt: str) -> str:
    """
    Capture the current desktop screen and send to Gemini Vision for analysis.
    Uses PIL ImageGrab with PowerShell System.Drawing fallback for reliability.
    Safely purges any temporary capture files immediately after use.
    """
    if not is_online():
        return "Screen awareness requires an internet connection for multimodal AI analysis."

    api_key = _get_api_key()
    if not api_key:
        return "I don't have a Gemini API key set up yet — add one in Settings (⚙️) or .env."

    temp_path = None
    try:
        from PIL import Image, ImageGrab
        import subprocess
        from config import BASE_DIR

        img = None
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            try:
                img = ImageGrab.grab()
            except Exception:
                img = None

        if img is None:
            # Fallback to PowerShell GDI capture
            temp_path = BASE_DIR / "temp_screen.png"
            temp_path_str = str(temp_path).replace("\\", "/")
            ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bmp)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save('{temp_path_str}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bmp.Dispose()
"""
            try:
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=5)
                if temp_path.exists():
                    with Image.open(temp_path) as opened_img:
                        img = opened_img.copy()
            except Exception:
                pass

        if img is None:
            return "Unable to capture the screen right now. Please ensure your desktop is active and unlocked."

        # Ensure image is in RGB format for Gemini Vision
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Downscale if massive to reduce latency while keeping text legible
        if max(img.width, img.height) > 1920:
            img.thumbnail((1920, 1080))

        model = _get_model()
        vision_prompt = (
            f"You are looking at an actual live screenshot of the user's desktop screen. "
            f"The user is asking: '{prompt}'. "
            f"Carefully examine the image and describe or answer based strictly and only on what is genuinely visible. "
            f"Identify open applications, active windows, text, or websites clearly shown on screen. "
            f"Do NOT guess or hallucinate any software, editor, or terminal that is not visibly open."
        )
        response = model.generate_content([vision_prompt, img], request_options={"timeout": 25.0})
        return response.text.strip() if response.text else "I couldn't analyze what's on the screen."
    except Exception as e:
        return f"Screen analysis error: {_sanitize_error(e)}"
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass

