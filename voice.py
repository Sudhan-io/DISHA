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
import socket
import threading
import time
from typing import Callable, Optional

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
MIN_RMS = getattr(_cfg, "VOICE_MIN_RMS", 1.8)                 # absolute loudness floor (calibrated for real laptop & headset mics)
NOISE_MARGIN = getattr(_cfg, "VOICE_NOISE_MARGIN", 1.25)       # speech must be this x louder than room noise
MIN_SPEECH_SECONDS = getattr(_cfg, "VOICE_MIN_SPEECH_SECONDS", 0.2)
NO_SPEECH_TIMEOUT = getattr(_cfg, "VOICE_NO_SPEECH_TIMEOUT", 5.0)   # give up if you never speak
MAX_LISTEN_SECONDS = getattr(_cfg, "VOICE_MAX_SECONDS", 20.0)
MIN_AVG_CONF = getattr(_cfg, "VOICE_MIN_AVG_CONF", 0.45)      # average word confidence required (for Vosk)
SINGLE_WORD_CONF = getattr(_cfg, "VOICE_SINGLE_WORD_CONF", 0.60)  # one-word results must be surer (for Vosk)


def _ensure_mic_volume() -> None:
    """Ensure Windows microphone input volume is at least 80% and not muted."""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        device = AudioUtilities.GetMicrophone()
        if device:
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))
            cur = volume.GetMasterVolumeLevelScalar()
            if cur < 0.70:
                volume.SetMasterVolumeLevelScalar(0.85, None)
            if volume.GetMute():
                volume.SetMute(0, None)
    except Exception:
        pass


def _is_device_openable(dev_idx: int) -> bool:
    try:
        def _dummy_cb(indata, frames, time_info, status):
            pass
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=1600,
            dtype="int16",
            channels=1,
            device=dev_idx,
            callback=_dummy_cb,
        ):
            return True
    except Exception:
        return False


def get_mic_device() -> Optional[int]:
    """
    Resolve the best available microphone:
    1. If DISHA_MIC_DEVICE is configured (as index or name substring), find it if openable.
    2. System default input device (from Windows Sound Settings) if openable.
    3. DirectSound microphone (higher quality & dynamic range on Windows).
    4. Connected headset / earbuds / wireless mic if active.
    5. Any openable input.
    """
    cfg = getattr(_cfg, "MIC_DEVICE", os.getenv("DISHA_MIC_DEVICE", ""))
    devs = sd.query_devices()

    # 1. User-configured device
    if cfg is not None and str(cfg).strip():
        s = str(cfg).strip().lower()
        if s.isdigit():
            idx = int(s)
            if 0 <= idx < len(devs) and devs[idx].get("max_input_channels", 0) > 0:
                if _is_device_openable(idx):
                    return idx
        for i, d in enumerate(devs):
            if d.get("max_input_channels", 0) > 0 and s in d.get("name", "").lower():
                if _is_device_openable(i):
                    return i

    # 2. System default input (what Windows actively has selected in Sound Settings)
    def_in = sd.default.device[0]
    if def_in is not None and def_in >= 0 and _is_device_openable(def_in):
        return def_in

    # 3. DirectSound microphone (higher quality & dynamic range on Windows)
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            name_low = d.get("name", "").lower()
            try:
                hostapi_name = sd.query_hostapis(d.get("hostapi", 0)).get("name", "").lower()
            except Exception:
                hostapi_name = ""
            if "directsound" in hostapi_name and "mic" in name_low:
                if _is_device_openable(i):
                    return i

    # 4. Connected headset / earbuds / wireless mic
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            name_low = d.get("name", "").lower()
            if any(k in name_low for k in ["headset", "buds", "enco", "airpods", "wireless"]):
                if _is_device_openable(i):
                    return i

    # 5. Any openable input
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0 and _is_device_openable(i):
            return i

    return None


MIC_DEVICE = get_mic_device()

DEBUG = os.getenv("DISHA_VOICE_DEBUG", "0") == "1"

# Words Vosk typically produces from pure noise
NOISE_WORDS = {
    "the", "a", "an", "uh", "um", "huh", "hmm", "mm", "oh", "ah", "eh",
    "and", "i", "it", "in", "is", "that", "to", "of", "hi",
}

_stt_model = None
_tts_queue = queue.Queue()
_tts_thread = None
_tts_interrupted = False

_listen_lock = threading.Lock()
_interrupt_event = threading.Event()
_noise_floor = 5.0   # calibrated for clean room background noise (real measured ~0.5-2.0)
_root_ref = None


def cancel_listen() -> None:
    """Signal any currently active listen() session to cancel and return immediately."""
    _interrupt_event.set()


def set_root(root) -> None:
    """Store Tk root reference for thread-safe callbacks."""
    global _root_ref
    _root_ref = root
    preload_stt()


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
    t = re.sub(r"[✨🔴🎙️🗣️🕒🔋💾📋📸⏰ℹ️➤🗖🗗●•🔔⏳]", "", t)
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
        if _tts_interrupted:
            return True
        audio_np = np.concatenate(frames, axis=1).T
        if _tts_interrupted:
            return True
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
        if _tts_interrupted:
            if done_event:
                done_event.set()
            _tts_queue.task_done()
            continue
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
    global _tts_interrupted
    if not TTS_ENABLED or not text:
        return
    cleaned = _clean_tts_text(text)
    if not cleaned:
        return
    _tts_interrupted = False
    _ensure_tts_thread()
    done_event = threading.Event() if wait else None
    _tts_queue.put((cleaned, done_event))
    if wait and done_event:
        done_event.wait()


def stop_speaking() -> None:
    """Immediately stop audio playback and clear pending speech queue."""
    global _tts_interrupted
    _tts_interrupted = True
    try:
        sd.stop()
    except Exception:
        pass
    while True:
        try:
            item = _tts_queue.get_nowait()
            if item is not None:
                _, done_event = item
                if done_event:
                    done_event.set()
            _tts_queue.task_done()
        except queue.Empty:
            break
        except Exception:
            break


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
_whisper_device = "unloaded"
_whisper_name = ""
_whisper_lock = threading.Lock()

_BIG_MODELS = {"large-v3", "large-v3-turbo", "turbo", "distil-large-v3", "distil-large-v3.5",
               "large-v2", "medium", "medium.en"}


def _add_cuda_dll_dirs() -> None:
    """
    On Windows, faster-whisper needs cublas64_12.dll / cudnn DLLs. If they were
    installed with pip (nvidia-cublas-cu12, nvidia-cudnn-cu12) they live in
    site-packages/nvidia/*/bin, which Windows does not search by default.
    """
    if os.name != "nt":
        return
    import sys
    for base in list(sys.path):
        nv = os.path.join(base, "nvidia")
        if not os.path.isdir(nv):
            continue
        for pkg in os.listdir(nv):
            bin_dir = os.path.join(nv, pkg, "bin")
            if os.path.isdir(bin_dir):
                try:
                    os.add_dll_directory(bin_dir)
                except (OSError, AttributeError):
                    pass
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def _transcribe_google(raw_audio: bytes, sample_rate: int = 16000) -> Optional[str]:
    """
    Transcribe raw PCM audio bytes using Google Web Speech API (Google Voice backend).
    Provides Google Assistant-grade cloud transcription for accents and conversational speech.
    Returns transcribed string, or None if failed or silent.
    """
    try:
        import speech_recognition as sr
        audio = sr.AudioData(raw_audio, sample_rate, 2)
        rec = sr.Recognizer()
        lang = getattr(_cfg, "GOOGLE_STT_LANG", "en-US")
        text = rec.recognize_google(audio, language=lang).strip()
        if text:
            _dbg(f"Google Voice recognition success ({lang}): '{text}'")
            return text
    except Exception as e:
        _dbg(f"Google Voice transcription note: {e}")
    return None


def stt_status() -> str:
    """Human-readable description of active speech models."""
    mode = getattr(_cfg, "STT_ENGINE", "auto").lower()
    whisper_info = f"{_whisper_name or getattr(_cfg, 'WHISPER_MODEL_SIZE', 'large-v3-turbo')} on {_whisper_device}"
    if mode == "auto":
        return f"Hybrid (Online: Google Voice + Offline: OpenAI Whisper {whisper_info})"
    elif mode in ("google", "online"):
        return f"Google Voice Cloud (Fallback: {whisper_info})"
    elif mode == "whisper":
        return f"OpenAI Whisper ({whisper_info})"
    return "Vosk Offline (Kaldi)"


def _get_whisper_model():
    global _whisper_model, _whisper_device, _whisper_name
    with _whisper_lock:
        if _whisper_model is None:
            try:
                _add_cuda_dll_dirs()
                from faster_whisper import WhisperModel
                import ctranslate2
                model_size = getattr(_cfg, "WHISPER_MODEL_SIZE", "large-v3-turbo")
                loaded = False
                try:
                    has_cuda = ctranslate2.get_cuda_device_count() > 0
                except Exception:
                    has_cuda = False
                if has_cuda:
                    try:
                        # float16 explicitly: CTranslate2's "auto" picks int8_float16,
                        # which fails on RTX 50-series (Blackwell) GPUs.
                        test_m = WhisperModel(model_size, device="cuda", compute_type="float16")
                        dummy = np.zeros(16000, dtype=np.float32)
                        list(test_m.transcribe(dummy, language="en")[0])  # real probe
                        _whisper_model, _whisper_device, _whisper_name = test_m, "GPU (CUDA float16)", model_size
                        loaded = True
                    except Exception as e_cuda:
                        print(f"[DISHA] GPU speech model failed ({e_cuda}); falling back to CPU.")
                else:
                    print("[DISHA] No usable CUDA GPU found for speech recognition; using CPU.")

                if not loaded:
                    cpu_threads = int(os.getenv("DISHA_WHISPER_THREADS", str(max(4, min(8, (os.cpu_count() or 4) - 2)))))
                    cpu_size = "base.en" if model_size in _BIG_MODELS else model_size
                    _whisper_model = WhisperModel(cpu_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
                    _whisper_device, _whisper_name = f"CPU (int8, {cpu_threads} threads)", cpu_size
                print(f"[DISHA] Speech recognition ready: {stt_status()}")
            except Exception as e:
                print(f"[DISHA] Failed to load faster-whisper: {e}")
                _whisper_model = False
    return _whisper_model if _whisper_model is not False else None


def preload_stt() -> None:
    """Load the speech model in the background so your first sentence isn't slow."""
    threading.Thread(target=_get_whisper_model, daemon=True).start()


# --- accuracy helpers -------------------------------------------------------

PHANTOM_PHRASES = {
    "thanks for watching", "thank you for watching", "please subscribe",
    "subscribe to my channel", "subtitles by the amara.org community", "you",
}


_prompt_cache = None


def _clean_whisper_repetition(text: str) -> str:
    """
    Detect and collapse Whisper autoregressive repetition loops (e.g. 'vscode. vscode. vscode. ...')
    down to a single clean utterance.
    """
    if not text:
        return ""
    import re
    cleaned = text.strip()
    tokens = [w.lower() for w in re.findall(r"\b[\w'-]+\b", cleaned)]
    if len(tokens) >= 3:
        unique = set(tokens)
        if len(unique) == 1:
            return tokens[0]
        # Check 2-word phrase repeat (e.g. 'vs code vs code vs code')
        if len(tokens) % 2 == 0:
            first_pair = tokens[:2]
            if tokens == first_pair * (len(tokens) // 2):
                return " ".join(first_pair)

    # 2. Regex collapse 3+ repeated word-tokens with optional trailing punctuation
    cleaned = re.sub(r'(\b\w+[\.\?!,]?\s+)(?:\1){2,}', r'\1', cleaned + " ", flags=re.IGNORECASE).strip()
    if len(cleaned.split()) == 1:
        cleaned = cleaned.rstrip(".!? ")

    return cleaned


def _build_prompt() -> str:
    """
    A short vocabulary hint. Whisper reads it as 'text that came just before',
    which makes it far more likely to spell your assistant's name and your
    app names correctly. Cached so it executes with zero overhead.
    """
    global _prompt_cache
    if _prompt_cache is not None:
        return _prompt_cache
    if not getattr(_cfg, "WHISPER_USE_PROMPT", True):
        _prompt_cache = ""
        return ""
    name = getattr(_cfg, "APP_NAME", "Disha")
    _prompt_cache = f"{name.title()}, VS Code, Google Chrome, Spotify, Calculator, Notepad, Terminal."
    return _prompt_cache


def _transcribe(w_model, audio_np):
    """Transcribe with low-latency VAD, anti-hallucination thresholds, repetition penalties, and greedy decoding."""
    import re
    prompt = _build_prompt()
    beam_size = getattr(_cfg, "WHISPER_BEAM_SIZE", 1)
    segments, _info = w_model.transcribe(
        audio_np,
        language="en",
        beam_size=beam_size,
        temperature=0.0,
        vad_filter=True,
        vad_parameters=dict(threshold=0.5, min_silence_duration_ms=350, speech_pad_ms=180),
        condition_on_previous_text=False,
        initial_prompt=prompt or None,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        repetition_penalty=1.2,
        no_repeat_ngram_size=3,
    )
    kept = []
    last_norm = ""
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
            _dbg(f"dropped segment (no_speech={seg.no_speech_prob:.2f}, logprob={seg.avg_logprob:.2f}): '{text}'")
            continue
        if seg.avg_logprob < -1.6:
            _dbg(f"dropped low-confidence segment (logprob={seg.avg_logprob:.2f}): '{text}'")
            continue
        norm = re.sub(r"[^\w\s]", "", text).lower().strip()
        if norm and norm == last_norm:
            _dbg(f"collapsed duplicate consecutive segment: '{text}'")
            continue
        last_norm = norm
        kept.append(text)

    raw_result = " ".join(kept).strip()
    result = _clean_whisper_repetition(raw_result)

    low = result.lower().strip(" .!?,")
    if low in PHANTOM_PHRASES:
        _dbg(f"dropped phantom phrase: '{result}'")
        return ""

    # Drop prompt hallucinations (when Whisper echoes back words from the vocabulary hint)
    if prompt and len(low.split()) >= 4:
        p_words = set(re.findall(r"\b\w+\b", prompt.lower()))
        r_words = re.findall(r"\b\w+\b", low)
        if r_words:
            overlap = sum(1 for w in r_words if w in p_words)
            action_verbs = {"open", "opening", "launch", "launching", "start", "close", "quit", "exit", "kill", "what", "how", "tell", "show", "calculate", "play", "set"}
            has_action = any(w in action_verbs for w in r_words)
            if not has_action and (overlap / len(r_words)) >= 0.60:
                _dbg(f"dropped vocabulary prompt echo: '{result}'")
                return ""

    return result


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
        _ensure_mic_volume()

        stt_mode = getattr(_cfg, "STT_ENGINE", "auto").lower()
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
        pre_roll = collections.deque(maxlen=4)  # 400ms pre-roll buffer catches initial consonants without feeding dead air
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
                device=get_mic_device(),
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
                    silence_limit = getattr(_cfg, "SILENCE_STOP_SECONDS", SILENCE_STOP_SECONDS)
                    if started and last_speech_t and (now - last_speech_t) >= silence_limit:
                        break
        except Exception as e:
            raise RuntimeError(f"Microphone error: {e}")

        if not started or not recorded_blocks:
            _dbg("no real speech detected")
            return ""

        raw_audio = b"".join(recorded_blocks)

        has_cuda_gpu = ("GPU" in _whisper_device or "CUDA" in _whisper_device)
        if not has_cuda_gpu:
            try:
                import ctranslate2
                has_cuda_gpu = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                has_cuda_gpu = False

        run_whisper_first = (stt_mode == "whisper") or (stt_mode == "auto" and has_cuda_gpu)

        if run_whisper_first:
            w_model = _get_whisper_model()
            if w_model:
                try:
                    if on_partial:
                        on_partial("Transcribing (Whisper GPU)..." if has_cuda_gpu else "Transcribing (Whisper Neural)...")
                    audio_np = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0

                    # Automatic gain control / peak normalization with safe ceiling
                    max_amp = float(np.max(np.abs(audio_np)))
                    if max_amp > 1e-4:
                        audio_np = audio_np * min(0.85 / max_amp, 30.0)

                    t0 = time.monotonic()
                    whisper_text = _transcribe(w_model, audio_np)
                    _dbg(f"faster-whisper ({stt_status()}) {time.monotonic() - t0:.2f}s: '{whisper_text}'")
                    if whisper_text:
                        return whisper_text
                    _dbg("faster-whisper detected silence / no speech; trying fallback")
                except Exception as e:
                    _dbg(f"faster-whisper error: {e}")

            # Fallback to Google Cloud if online
            if stt_mode in ("auto", "google", "online"):
                is_online = False
                try:
                    import gemini_client
                    is_online = gemini_client.is_online()
                except Exception:
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.connect(("8.8.8.8", 80))
                        s.close()
                        is_online = True
                    except Exception:
                        is_online = False

                if is_online:
                    try:
                        if on_partial:
                            on_partial("Transcribing (Google Cloud)...")
                        t0 = time.monotonic()
                        google_text = _transcribe_google(raw_audio, sample_rate)
                        if google_text:
                            _dbg(f"Google Voice fallback ({time.monotonic() - t0:.2f}s): '{google_text}'")
                            return google_text
                    except Exception as e_g:
                        _dbg(f"Google Voice fallback error: {e_g}")
        else:
            # Cloud-first path for CPU-only systems or explicit 'google' mode
            if stt_mode in ("auto", "google", "online"):
                is_online = False
                try:
                    import gemini_client
                    is_online = gemini_client.is_online()
                except Exception:
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.connect(("8.8.8.8", 80))
                        s.close()
                        is_online = True
                    except Exception:
                        is_online = False

                if is_online:
                    try:
                        if on_partial:
                            on_partial("Transcribing (Google Cloud)...")
                        t0 = time.monotonic()
                        google_text = _transcribe_google(raw_audio, sample_rate)
                        if google_text:
                            _dbg(f"Google Voice ({time.monotonic() - t0:.2f}s): '{google_text}'")
                            return google_text
                        _dbg("Google Voice detected no speech or silent; trying Whisper fallback")
                    except Exception as e_g:
                        _dbg(f"Google Voice error: {e_g}")

            # Fallback to local Whisper
            w_model = _get_whisper_model()
            if w_model:
                try:
                    if on_partial:
                        on_partial("Transcribing (Whisper Neural)...")
                    audio_np = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0

                    # Automatic gain control / peak normalization with safe ceiling
                    max_amp = float(np.max(np.abs(audio_np)))
                    if max_amp > 1e-4:
                        audio_np = audio_np * min(0.85 / max_amp, 30.0)

                    t0 = time.monotonic()
                    whisper_text = _transcribe(w_model, audio_np)
                    _dbg(f"faster-whisper ({stt_status()}) {time.monotonic() - t0:.2f}s: '{whisper_text}'")
                    if whisper_text:
                        return whisper_text
                    _dbg("faster-whisper detected silence / no speech")
                    return ""
                except Exception as e:
                    _dbg(f"faster-whisper error: {e}")

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
                device=get_mic_device(),
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