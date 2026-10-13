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

_model = None


def _build_system_prompt() -> str:
    """Personalize the system prompt using saved facts (e.g. user_name)."""
    user_name = memory.get_fact("user_name", "")
    fact_context = f"User's name: {user_name}. " if user_name else ""
    return fact_context + SYSTEM_PROMPT


def _get_model():
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=_build_system_prompt(),
    )


def is_online(timeout: float = 2.0) -> bool:
    """Quick, reliable connectivity check before attempting an API call."""
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 443), ("8.8.8.8", 53)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((host, port))
            return True
        except OSError:
            continue
    return False


def _sanitize_error(e: Exception) -> str:
    """Ensure raw API keys or internal secrets never leak in error messages."""
    msg = str(e)
    if GEMINI_API_KEY and GEMINI_API_KEY in msg:
        msg = msg.replace(GEMINI_API_KEY, "[REDACTED_API_KEY]")
    return msg


def ask(prompt: str, context: str = "") -> str:
    """
    Send a prompt to Gemini and return DISHA's reply as plain text.
    When offline, seamlessly routes to local_llm (Ollama).
    """
    if not is_online():
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local(prompt, context)
        return "I'm offline right now, and the local Ollama service is not running. Reconnect or start Ollama."

    if not GEMINI_API_KEY:
        return "I don't have an API key set up yet — add one to your .env file."

    try:
        model = _get_model()
        full_prompt = f"{context}\n\nUser: {prompt}" if context else prompt
        response = model.generate_content(full_prompt)
        return response.text.strip() if response.text else "I didn't get a response back — try rephrasing?"
    except Exception as e:
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local(prompt, context)
        err = _sanitize_error(e)
        if "429" in err:
            return "Gemini quota limit reached. Please wait a bit or start Ollama for offline GPU mode."
        return f"Something went wrong reaching Gemini: {err}"


def ask_streaming(prompt: str, context: str = "", on_chunk: Optional[Callable[[str], None]] = None) -> str:
    """
    Like ask(), but calls on_chunk(partial_accumulated_text) as tokens arrive.
    When offline, streams from local_llm (Ollama).
    Falls back to non-streaming ask() if on_chunk is None.
    """
    if on_chunk is None:
        return ask(prompt, context)

    if not is_online():
        import local_llm
        if local_llm.is_ollama_running():
            return local_llm.ask_local_streaming(prompt, context, on_chunk=on_chunk)
        msg = "I'm offline right now, and the local Ollama service is not running. Reconnect or start Ollama."
        on_chunk(msg)
        return msg

    if not GEMINI_API_KEY:
        msg = "I don't have an API key set up yet — add one to your .env file."
        on_chunk(msg)
        return msg

    try:
        model = _get_model()
        full_prompt = f"{context}\n\nUser: {prompt}" if context else prompt
        response = model.generate_content(full_prompt, stream=True)
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
        if "429" in err:
            msg = "Gemini quota limit reached. Please wait a bit or start Ollama for offline GPU mode."
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

    if not GEMINI_API_KEY:
        return "I don't have a Gemini API key set up yet in .env."

    temp_path = None
    try:
        from PIL import ImageGrab
        import subprocess
        from config import BASE_DIR

        img = None
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            try:
                img = ImageGrab.grab()
            except Exception:
                pass

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
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=5)
            from PIL import Image
            if temp_path.exists():
                img = Image.open(temp_path)

        if img is None:
            return "Unable to capture the screen right now."

        # Ensure image is in RGB format for Gemini Vision
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Downscale if massive to reduce latency while keeping text legible
        if max(img.width, img.height) > 1920:
            img.thumbnail((1920, 1080))

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=_build_system_prompt(),
        )
        vision_prompt = (
            f"You are looking at an actual live screenshot of the user's desktop screen. "
            f"The user is asking: '{prompt}'. "
            f"Carefully examine the image and describe or answer based strictly and only on what is genuinely visible. "
            f"Identify open applications, active windows, text, or websites clearly shown on screen. "
            f"Do NOT guess or hallucinate any software, editor, or terminal that is not visibly open."
        )
        response = model.generate_content([vision_prompt, img])
        return response.text.strip() if response.text else "I couldn't analyze what's on the screen."
    except Exception as e:
        return f"Screen analysis error: {_sanitize_error(e)}"
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass

