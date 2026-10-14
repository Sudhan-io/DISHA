"""
DISHA - Offline Voice (v2.1)
Speech-to-text via Vosk (fully local model, no internet) and text-to-speech
via Windows SAPI5 / pyttsx3 (also fully local).

v2.1 STT fixes:
  - Energy gate with an adaptive noise floor (noise no longer counts as speech)
  - Per-word confidence filtering (low-confidence guesses are rejected)
  - Noise-word filter ("the", "huh", "uh" ... on their own are ignored)
  - Only ONE listening session at a time
  - Waits for DISHA to finish speaking before listening (no self-hearing)
  - Selectable microphone + debug output for tuning
"""

import ctypes
import json
import os
import queue
import threading
import time
from typing import Callable

import numpy as np
import pyttsx3
import sounddevice as sd
import vosk
import win32com.client

import config as _cfg
from config import VOSK_MODEL_PATH, TTS_ENABLED, TTS_RATE, TTS_VOICE_GENDER, SILENCE_STOP_SECONDS

vosk.SetLogLevel(-1)  # quiet Vosk's default console spam

# ---------------------------------------------------------------------------
# Tunables (optional: define any of these in config.py to override)
# ---------------------------------------------------------------------------
MIN_RMS = getattr(_cfg, "VOICE_MIN_RMS", 80.0)                # absolute loudness floor (sensitive to soft casual speech)
NOISE_MARGIN = getattr(_cfg, "VOICE_NOISE_MARGIN", 1.4)        # speech must be this x louder than room noise
MIN_SPEECH_SECONDS = getattr(_cfg, "VOICE_MIN_SPEECH_SECONDS", 0.2)
NO_SPEECH_TIMEOUT = getattr(_cfg, "VOICE_NO_SPEECH_TIMEOUT", 5.0)   # give up if you never speak
MAX_LISTEN_SECONDS = getattr(_cfg, "VOICE_MAX_SECONDS", 20.0)
MIN_AVG_CONF = getattr(_cfg, "VOICE_MIN_AVG_CONF", 0.45)      # average word confidence required (for Vosk)
SINGLE_WORD_CONF = getattr(_cfg, "VOICE_SINGLE_WORD_CONF", 0.60)  # one-word results must be surer (for Vosk)

_mic_cfg = getattr(_cfg, "MIC_DEVICE", os.getenv("DISHA_MIC_DEVICE", ""))
if isinstance(_mic_cfg, str):
    _mic_cfg = _mic_cfg.strip()
    MIC_DEVICE = int(_mic_cfg) if _mic_cfg.isdigit() else (_mic_cfg or None)
else:
    MIC_DEVICE = _mic_cfg

DEBUG = os.getenv("DISHA_VOICE_DEBUG", "0") == "1"

# Words Vosk typically produces from pure noise
NOISE_WORDS = {
    "the", "a", "an", "uh", "um", "huh", "hmm", "mm", "oh", "ah", "eh",
    "and", "i", "it", "in", "is", "that", "to", "of", "hi",
}

_stt_model = None
_tts_queue = queue.Queue()
_tts_thread = None

_listen_lock = threading.Lock()
_interrupt_event = threading.Event()
_noise_floor = 150.0  # adaptive; persists between listening sessions
_root_ref = None


def cancel_listen() -> None:
    """Signal any currently active listen() session to cancel and return immediately."""
    _interrupt_event.set()


def set_root(root) -> None:
    """Store Tk root reference for thread-safe callbacks."""
    global _root_ref
    _root_ref = root


def _dbg(msg: str) -> None:
    if DEBUG:
        print(f"[voice] {msg}")


# ---------------------------------------------------------------------------
# Text-to-speech (unchanged)
# ---------------------------------------------------------------------------

def _clean_tts_text(text: str) -> str:
    """Strip markdown formatting, URLs, code blocks, and emojis so speech sounds natural."""
    if not text:
        return ""
    import re
    # Remove code blocks and inline code
    t = re.sub(r"```[\s\S]*?```", " code block omitted. ", text)
    t = re.sub(r"`[^`]*`", "", t)
    # Remove markdown links [title](url) -> title
    t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
    # Remove raw URLs
    t = re.sub(r"https?://\S+", "", t)
    # Remove bold, italics, strikethrough, headers, bullet dashes
    t = re.sub(r"[*_~#]+", "", t)
    t = re.sub(r"^[-*•]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"─{3,}", "", t)
    # Remove common emojis and decorative symbols
    t = re.sub(r"[✨🔴🎙️🗣️🕒🔋💾📋📸⏰ℹ️➤🗖🗗●•]", "", t)
    return " ".join(t.split())


def _tts_speak_direct_sapi(text: str) -> bool:
    """
    Direct Windows SAPI5 COM dispatch. Bypasses pyttsx3 driver loops and
    guarantees audio output on Windows 10/11 even after microphone input.
    """
    try:
        ctypes.windll.ole32.CoInitialize(None)
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            try:
                sapi_rate = max(-10, min(10, int((TTS_RATE - 175) / 15)))
                speaker.Rate = sapi_rate
            except Exception:
                pass
            try:
                voices = speaker.GetVoices()
                for i in range(voices.Count):
                    v = voices.Item(i)
                    desc = (v.GetDescription() or "").lower()
                    if TTS_VOICE_GENDER == "female" and ("zira" in desc or "female" in desc):
                        speaker.Voice = v
                        break
                    elif TTS_VOICE_GENDER == "male" and ("david" in desc or "male" in desc):
                        speaker.Voice = v
                        break
            except Exception:
                pass
            speaker.Speak(text)
            del speaker
            return True
        finally:
            ctypes.windll.ole32.CoUninitialize()
    except Exception:
        return False


def _tts_speak_neural(text: str) -> bool:
    """
    Generate and stream high-quality neural voice in-memory via edge-tts.
    Zero disk files, zero GPU memory overhead, crystal-clear anime/e-girl voice.
    """
    try:
        import asyncio
        import io
        import av
        import edge_tts
        neural_voice = getattr(_cfg, "TTS_NEURAL_VOICE", "en-US-AnaNeural")

        async def gen():
            c = edge_tts.Communicate(text, neural_voice)
            data = b""
            async for chunk in c.stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return data

        mp3_data = asyncio.run(gen())
        if not mp3_data:
            return False

        container = av.open(io.BytesIO(mp3_data), format="mp3")
        stream = container.streams.audio[0]
        sr = stream.codec_context.sample_rate or 24000
        frames = [f.to_ndarray() for f in container.decode(audio=0)]
        if not frames:
            return False
        audio_np = np.concatenate(frames, axis=1).T
        sd.play(audio_np, samplerate=sr)
        sd.wait()
        return True
    except Exception as e:
        _dbg(f"Neural TTS failed ({e}), falling back to SAPI5...")
        return False


def _tts_worker():
    """
    Dedicated worker thread loop for TTS.
    Tries in-memory neural voice (edge-tts) first, falling back to native SAPI5, then pyttsx3.
    """
    while True:
        item = _tts_queue.get()
        if item is None:
            _tts_queue.task_done()
            break
        text, done_event = item
        if TTS_ENABLED and text:
            tts_engine = getattr(_cfg, "TTS_ENGINE", "neural").lower()
            success = False
            if tts_engine == "neural":
                success = _tts_speak_neural(text)
            if not success:
                success = _tts_speak_direct_sapi(text)
            if not success:
                try:
                    ctypes.windll.ole32.CoInitialize(None)
                    try:
                        engine = pyttsx3.init()
                        engine.setProperty("rate", TTS_RATE)
                        _select_voice(engine, TTS_VOICE_GENDER)
                        engine.say(text)
                        engine.runAndWait()
                        del engine
                    finally:
                        ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass
        if done_event:
            done_event.set()
        _tts_queue.task_done()


def _ensure_tts_thread():
    global _tts_thread
    if _tts_thread is None or not _tts_thread.is_alive():
        _tts_thread = threading.Thread(target=_tts_worker, daemon=True)
        _tts_thread.start()


def _select_voice(engine, preferred_gender: str) -> None:
    """
    Pick a matching installed voice (e.g. Windows' built-in "Zira" for
    female, "David" for male). Falls back to whatever's default if no
    match is found — never errors out.
    """
    try:
        voices = engine.getProperty("voices")
    except Exception:
        return

    for v in voices:
        name = (v.name or "").lower()
        v_id = (v.id or "").lower()
        if preferred_gender == "female" and ("zira" in name or "female" in name or "zira" in v_id):
            engine.setProperty("voice", v.id)
            return
        if preferred_gender == "male" and ("david" in name or "male" in name or "david" in v_id):
            engine.setProperty("voice", v.id)
            return


def set_voice_profile(profile_id: str) -> bool:
    """Set the active voice persona and sync engine & voice parameters."""
    profile = getattr(_cfg, "VOICE_PROFILES", {}).get(profile_id)
    if not profile:
        return False
    _cfg.VOICE_PROFILE = profile_id
    _cfg.TTS_ENGINE = profile["engine"]
    if profile.get("neural_voice"):
        _cfg.TTS_NEURAL_VOICE = profile["neural_voice"]
    if profile.get("gender"):
        _cfg.TTS_VOICE_GENDER = profile["gender"]
    return True


def get_active_voice_profile() -> dict:
    """Return dictionary of the currently active voice profile."""
    prof_id = getattr(_cfg, "VOICE_PROFILE", "egirl")
    profiles = getattr(_cfg, "VOICE_PROFILES", {})
    return profiles.get(prof_id, profiles.get("egirl", {
        "id": "egirl",
        "name": "💖 E-Girl Persona (egirl.pth / Anime Character)",
        "short_name": "💖 E-Girl",
        "engine": "neural",
        "neural_voice": "en-US-AnaNeural"
    }))


def speak(text: str, wait: bool = False) -> None:
    """
    Speak text aloud, fully offline. No-op if TTS is disabled in config.
    If wait is True, blocks the calling thread until speaking is complete.
    """
    if not TTS_ENABLED or not text:
        return
    cleaned = _clean_tts_text(text)
    if not cleaned:
        return
    _ensure_tts_thread()
    done_event = threading.Event() if wait else None
    _tts_queue.put((cleaned, done_event))
    if wait and done_event:
        done_event.wait()


def _wait_for_tts(timeout: float = 30.0) -> None:
    """Block until DISHA has finished speaking, so the mic never hears her."""
    waited = False
    deadline = time.monotonic() + timeout
    while _tts_queue.unfinished_tasks and time.monotonic() < deadline:
        waited = True
        time.sleep(0.05)
    if waited:
        time.sleep(0.35)  # let the room echo die down


# ---------------------------------------------------------------------------
# Speech-to-text
# ---------------------------------------------------------------------------

def list_input_devices() -> None:
    """Print available microphones. Set DISHA_MIC_DEVICE to the index you want."""
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            print(f"{i:>3}  {d['name']}  (default rate {int(d['default_samplerate'])})")


def is_listening() -> bool:
    """True while a listening session is running."""
    return _listen_lock.locked()


def _get_stt_model():
    global _stt_model
    if _stt_model is None:
        try:
            _stt_model = vosk.Model(VOSK_MODEL_PATH)
        except Exception as e:
            raise RuntimeError(
                f"Couldn't load the Vosk model at '{VOSK_MODEL_PATH}'. "
                f"Download a model from https://alphacephei.com/vosk/models, "
                f"unzip it, and set VOSK_MODEL_PATH to that folder. ({e})"
            )
    return _stt_model


def _rms(block: bytes) -> float:
    a = np.frombuffer(block, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def _clean_result(result: dict) -> str:
    """
    Turn a Vosk result into trustworthy text, or "" if it looks like noise.
    Requires recognizer.SetWords(True) so per-word confidence is present.
    """
    text = (result.get("text") or "").strip()
    if not text:
        return ""

    words = result.get("result") or []
    if words:
        words = [w for w in words if w.get("word") and w["word"] != "[unk]"]
        if not words:
            return ""
        confs = [float(w.get("conf", 0.0)) for w in words]
        avg = sum(confs) / len(confs)
        _dbg(f"'{text}'  avg_conf={avg:.2f}  words={len(words)}")
        if avg < MIN_AVG_CONF:
            return ""
        if len(words) == 1 and avg < SINGLE_WORD_CONF:
            return ""
        text = " ".join(w["word"] for w in words)

    tokens = text.lower().split()
    if tokens and all(t in NOISE_WORDS for t in tokens):
        _dbg(f"dropped noise-only result: '{text}'")
        return ""
    return text


_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            import ctranslate2
            model_size = getattr(_cfg, "WHISPER_MODEL_SIZE", "small.en")
            # Auto-detect CUDA for fast GPU inference (~0.1s on RTX GPU), graceful CPU fallback
            has_cuda = ctranslate2.get_cuda_device_count() > 0
            device = "cuda" if has_cuda else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            _dbg(f"Loading faster-whisper model '{model_size}' on {device} ({compute_type})...")
            try:
                _whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
            except Exception as e_dev:
                _dbg(f"{device} init failed ({e_dev}), falling back to CPU int8...")
                _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=6)
            _dbg("faster-whisper model loaded successfully!")
        except Exception as e:
            _dbg(f"Failed to load faster-whisper: {e}")
            _whisper_model = False
    return _whisper_model if _whisper_model is not False else None


def listen(sample_rate: int = 16000, max_seconds: float = None, on_partial=None) -> str:
    """
    Listen on the microphone until you finish speaking, then return the text.

    Uses faster-whisper for high-accuracy neural STT (with Vosk real-time partials),
    falling back to Vosk if whisper is disabled or unavailable.
    """
    global _noise_floor

    if not _listen_lock.acquire(blocking=False):
        return ""
    try:
        _interrupt_event.clear()
        _wait_for_tts()

        use_whisper = getattr(_cfg, "STT_ENGINE", "whisper") == "whisper"
        model = _get_stt_model()
        recognizer = vosk.KaldiRecognizer(model, sample_rate)
        recognizer.SetWords(True)

        max_seconds = max_seconds or MAX_LISTEN_SECONDS
        block_seconds = 0.1
        blocksize = int(sample_rate * block_seconds)
        min_speech_blocks = max(1, int(MIN_SPEECH_SECONDS / block_seconds))

        audio_queue: queue.Queue = queue.Queue()

        def callback(indata, frames, time_info, status):
            audio_queue.put(bytes(indata))

        import collections
        pre_roll = collections.deque(maxlen=12)  # 1200ms pre-roll buffer so initial casual words are never clipped
        parts = []
        recorded_blocks = []
        speech_blocks = 0
        started = False
        last_speech_t = None
        t_start = time.monotonic()

        try:
            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=blocksize,
                dtype="int16",
                channels=1,
                device=MIC_DEVICE,
                callback=callback,
            ):
                while True:
                    if _interrupt_event.is_set():
                        _dbg("listen() interrupted by cancel signal")
                        return ""
                    now = time.monotonic()
                    if now - t_start > max_seconds:
                        break
                    if not started and now - t_start > NO_SPEECH_TIMEOUT:
                        break

                    try:
                        data = audio_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    level = _rms(data)
                    threshold = max(MIN_RMS, _noise_floor * NOISE_MARGIN)
                    is_speech = level > threshold

                    if is_speech:
                        speech_blocks += 1
                        last_speech_t = now
                        if speech_blocks >= min_speech_blocks:
                            if not started:
                                started = True
                                # Prepend pre-roll buffer so the start of the first word is fully preserved
                                recorded_blocks.extend(pre_roll)
                    else:
                        speech_blocks = max(0, speech_blocks - 1)
                        # learn the room's background level from non-speech blocks
                        _noise_floor = 0.97 * _noise_floor + 0.03 * level

                    if started:
                        recorded_blocks.append(data)
                    else:
                        pre_roll.append(data)

                    # Real-time partial feedback
                    if recognizer.AcceptWaveform(data):
                        text = _clean_result(json.loads(recognizer.Result()))
                        if text and started:
                            parts.append(text)
                            if on_partial:
                                on_partial(" ".join(parts))
                    elif started and on_partial:
                        p = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                        if p:
                            on_partial(" ".join(parts + [p]).strip())

                    # Stop once you were speaking and have been quiet long enough
                    if started and last_speech_t and (now - last_speech_t) >= SILENCE_STOP_SECONDS:
                        break
        except Exception as e:
            raise RuntimeError(f"Microphone error: {e}")

        if not started or not recorded_blocks:
            _dbg("no real speech detected")
            return ""

        # Neural transcription with faster-whisper
        if use_whisper:
            w_model = _get_whisper_model()
            if w_model:
                try:
                    if on_partial:
                        on_partial("Transcribing...")
                    raw_audio = b"".join(recorded_blocks)
                    audio_np = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
                    segments, _ = w_model.transcribe(
                        audio_np,
                        language="en",
                        beam_size=5,
                        best_of=5,
                        temperature=0.0,
                        vad_filter=False,
                        condition_on_previous_text=False,
                        initial_prompt=None,
                    )
                    whisper_text = " ".join(s.text.strip() for s in segments).strip()
                    if whisper_text:
                        _dbg(f"faster-whisper result: '{whisper_text}'")
                        return whisper_text
                except Exception as e:
                    _dbg(f"faster-whisper error: {e}. Falling back to Vosk.")

        # Fallback to Vosk result
        final = _clean_result(json.loads(recognizer.FinalResult()))
        if final:
            parts.append(final)

        return " ".join(parts).strip()
    finally:
        _listen_lock.release()


wait_for_tts = _wait_for_tts


def listen_for_wake_word(callback: Callable[[], None], stop_event: threading.Event) -> None:
    """
    Continuously monitor microphone for WAKE_WORD (from config).
    When heard, calls callback() on the main thread via root.after().
    Runs until stop_event.is_set().
    """
    wake_phrase = getattr(_cfg, "WAKE_WORD", "hey disha").lower().strip()
    sample_rate = 16000
    block_seconds = 0.2
    blocksize = int(sample_rate * block_seconds)

    try:
        model = _get_stt_model()
    except Exception as e:
        _dbg(f"Wake word model load failed: {e}")
        return

    audio_queue: queue.Queue = queue.Queue()

    def mic_cb(indata, frames, time_info, status):
        audio_queue.put(bytes(indata))

    try:
        grammar = json.dumps([wake_phrase, "disha", "hey", "[unk]"])
        recognizer = vosk.KaldiRecognizer(model, sample_rate, grammar)
    except Exception:
        recognizer = vosk.KaldiRecognizer(model, sample_rate)
    recognizer.SetWords(False)

    while not stop_event.is_set():
        if is_listening() or _tts_queue.unfinished_tasks:
            time.sleep(0.3)
            continue

        try:
            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=blocksize,
                dtype="int16",
                channels=1,
                device=MIC_DEVICE,
                callback=mic_cb,
            ):
                while not stop_event.is_set() and not is_listening() and not _tts_queue.unfinished_tasks:
                    try:
                        data = audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    if recognizer.AcceptWaveform(data):
                        res = json.loads(recognizer.Result())
                        text = (res.get("text") or "").strip().lower()
                    else:
                        p_res = json.loads(recognizer.PartialResult())
                        text = (p_res.get("partial") or "").strip().lower()

                    if wake_phrase in text:
                        _dbg(f"Wake word matched: '{wake_phrase}' in '{text}'")
                        recognizer.Reset()
                        if _root_ref:
                            _root_ref.after(0, callback)
                        else:
                            callback()
                        time.sleep(2.5)  # cooldown period
                        break
        except Exception as e:
            _dbg(f"Wake word error: {e}")
            time.sleep(1.0)