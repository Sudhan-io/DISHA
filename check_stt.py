"""
DISHA - Speech-to-Text & Microphone Diagnostics
Run this script to inspect available audio inputs, test microphone levels,
and benchmark speech recognition models.

Usage:
    python check_stt.py
"""

import os
import sys
import time
import numpy as np
import sounddevice as sd

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import voice
from voice import get_mic_device, _is_device_openable, _get_whisper_model, stt_status, _transcribe


def print_banner(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_audio_devices():
    print_banner("1. AUDIO INPUT DEVICES")
    devs = sd.query_devices()
    selected_mic = get_mic_device()
    
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            openable = _is_device_openable(i)
            status = "OPEN" if openable else "INACTIVE / DISCONNECTED"
            mark = "-> [ACTIVE MIC]" if i == selected_mic else "  "
            hostapi = sd.query_hostapis(d.get("hostapi", 0)).get("name", "Unknown API")
            name = d.get("name", "").splitlines()[0]
            print(f"{mark} [{i:2d}] {name} ({hostapi}) - {status}")
            
    print(f"\nCurrently resolved microphone index: {selected_mic}")
    if selected_mic is not None:
        print(f"Device name: {sd.query_devices(selected_mic)['name']}")


def check_models():
    print_banner("2. SPEECH-TO-TEXT ENGINE STATUS")
    print(f"Configured STT Mode: {voice._cfg.STT_ENGINE}")
    
    # Check Google Voice (Online)
    try:
        import speech_recognition as sr
        print("Google Speech Recognition (Online): Available (Google Web Speech API)")
    except ImportError:
        print("Google Speech Recognition: SpeechRecognition not installed")

    # Check Whisper (Local Neural)
    print("Initializing faster-whisper engine...")
    t0 = time.monotonic()
    w_model = _get_whisper_model()
    t_load = time.monotonic() - t0
    
    if w_model:
        print(f"Status: {stt_status()} (load/probe time: {t_load:.2f}s)")
    else:
        print("faster-whisper failed to initialize. Falling back to Vosk.")
        
    v_model = voice._get_stt_model()
    if v_model:
        print("Vosk model: Ready (local offline)")
    else:
        print("Vosk model: Failed to load")


def test_microphone_audio():
    print_banner("3. MICROPHONE AUDIO CAPTURE & LEVEL TEST")
    mic_idx = get_mic_device()
    if mic_idx is None:
        print("ERROR: No openable audio input device found.")
        return
        
    duration = 3.0
    sr = 16000
    print(f"Listening on device [{mic_idx}] for {duration:.1f}s...")
    print("Speak something or remain quiet to test anti-hallucination...\n")
    
    rec = sd.rec(int(sr * duration), samplerate=sr, channels=1, dtype="int16", device=mic_idx)
    sd.wait()
    
    audio_int16 = rec.flatten()
    rms = float(np.sqrt(np.mean(audio_int16.astype(float) ** 2)))
    max_amp = int(np.max(np.abs(audio_int16)))
    
    print(f"Audio stats: Peak amplitude = {max_amp} / 32767, RMS level = {rms:.2f}")
    if rms < 2.0:
        print("Level note: Dead silence or quiet room. Threshold filter active.")
    elif rms < 20.0:
        print("Level note: Subtle room noise / low speech level.")
    else:
        print("Level note: Strong, clear audio signal detected!")

    print_banner("4. TRANSCRIPTION TEST")
    w_model = _get_whisper_model()
    if not w_model:
        print("Whisper model unavailable.")
        return
        
    audio_np = audio_int16.astype(np.float32) / 32768.0
    peak = float(np.max(np.abs(audio_np)))
    if peak > 1e-4:
        audio_np = audio_np * min(0.85 / peak, 30.0)
        
    t0 = time.monotonic()
    result = _transcribe(w_model, audio_np)
    elapsed = time.monotonic() - t0
    
    print(f"Transcription ({elapsed:.2f}s): '{result}'")
    if not result:
        print("Result: No speech detected (anti-hallucination filter correctly dropped silence/noise).")
    else:
        print("Result: Speech recognized cleanly!")


if __name__ == "__main__":
    check_audio_devices()
    check_models()
    test_microphone_audio()
    print("\n" + "=" * 60)
    print("  DIAGNOSTICS COMPLETE")
    print("=" * 60 + "\n")
