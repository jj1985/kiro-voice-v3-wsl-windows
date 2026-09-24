"""Local microphone/STT/TTS sidecar. Standard output is reserved for JSONL."""
from __future__ import annotations

import argparse
import json
import math
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from .config import DEFAULTS, validate
from .speech import clean_tts, strip_wake

OUTPUT = threading.Lock()


def emit(**message):
    with OUTPUT:
        print(json.dumps(message, ensure_ascii=False), flush=True)


class Speaker:
    def __init__(self, cfg):
        self.cfg, self.proc = cfg, None
        self.lock = threading.Lock()

    def active(self):
        with self.lock:
            return self.proc is not None and self.proc.poll() is None

    def stop(self):
        with self.lock:
            proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(2)

    def speak(self, text, token):
        self.stop()
        text = clean_tts(text, self.cfg["tts_max_chars"])
        if not text or not self.cfg["tts"]:
            emit(event="tts_finished", token=token)
            return
        proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "quack_actual.audio", "--tts-worker", str(self.cfg["tts_rate"])],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=None,
        )
        with self.lock:
            self.proc = proc
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        emit(event="tts_started", token=token)

        def wait():
            code = proc.wait()
            with self.lock:
                current = self.proc is proc
                if current:
                    self.proc = None
            if current:
                if code:
                    emit(event="warning", error=f"TTS exited {code}; response remains in terminal")
                emit(event="tts_finished", token=token)
        threading.Thread(target=wait, daemon=True).start()


class Monitor:
    def __init__(self, cfg, speaker):
        self.cfg, self.speaker = cfg, speaker
        self.stopped = threading.Event()
        self.jobs = queue.Queue(maxsize=2)
        self.models = {}
        self.lock = threading.Lock()
        self.epoch = 0
        self.armed_until = self.followup_until = 0.0
        self.busy = False

    def state(self, mode):
        with self.lock:
            self.epoch += 1
            self.armed_until = self.followup_until = 0.0
            self.busy = mode == "busy"
            if mode == "listen":
                self.armed_until = time.monotonic() + self.cfg["arm_seconds"]
            elif mode == "followup":
                self.followup_until = time.monotonic() + self.cfg["conversation_seconds"]

    def snapshot(self):
        with self.lock:
            active = time.monotonic() < max(self.armed_until, self.followup_until)
            return self.epoch, active, self.speaker.active(), self.busy

    def beep(self):
        if self.cfg["activation_sound"]:
            try:
                import winsound
                winsound.Beep(880, 80)
            except (ImportError, RuntimeError):
                pass

    def transcribe(self, audio, purpose):
        from faster_whisper import WhisperModel
        model = self.cfg["wake_model"] if purpose == "wake" else self.cfg["command_model"]
        if model not in self.models:
            emit(event="status", text=f"Loading local speech model {model}")
            self.models[model] = WhisperModel(model, device=self.cfg["device"], compute_type=self.cfg["compute_type"])
        segments, _ = self.models[model].transcribe(
            audio, language="en", beam_size=1, vad_filter=True, condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def handle(self, audio, snapshot, captured):
        epoch, active, speaking, busy = snapshot
        if time.monotonic() - captured > 10 or epoch != self.epoch:
            return  # Never execute queued room speech after a state change.
        if speaking and not self.cfg["barge_in"]:
            return
        purpose = "command" if active and not speaking and not busy else "wake"
        text = self.transcribe(audio, purpose)
        if not text or epoch != self.epoch:
            return
        found, remainder = strip_wake(text, self.cfg["wake_phrase"])
        if speaking or busy or not active:
            if not found:
                return
            if speaking:
                self.speaker.stop()
                emit(event="interrupt")
            self.beep()
            emit(event="wake")
            if not remainder:
                self.state("listen")
                return
            # A wake-only result is never promoted to a prompt by a second model.
            if purpose == "wake":
                better = self.transcribe(audio, "command")
                matched, rest = strip_wake(better, self.cfg["wake_phrase"])
                if matched and rest:
                    remainder = rest
            text = remainder
        else:
            text = remainder if found else text
        if epoch != self.epoch or not text.strip():
            return
        self.state("busy")
        emit(event="utterance", text=text.strip())

    def worker(self):
        while not self.stopped.is_set():
            try:
                job = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.handle(*job)
            except Exception as exc:
                emit(event="warning", error=f"Speech recognition failed: {exc}")
                self.state("sleep")

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            threshold = self.cfg["rms_threshold"]
            blocks = queue.Queue(maxsize=64)
            pre = deque(maxlen=8)
            frames, rec, voiced, silent = [], False, 0, 0
            epoch = -1
            snapshot = None
            block_ms, rate = 40, 16000
            stop_count = math.ceil(self.cfg["silence_seconds"] * 1000 / block_ms)
            maximum = math.ceil(self.cfg["max_utterance_seconds"] * 1000 / block_ms)
            sd.check_input_settings(device=self.cfg["microphone"], channels=1, dtype="float32", samplerate=rate)
            device = sd.query_devices(self.cfg["microphone"], "input")

            def callback(indata, count, timing, status):
                try:
                    blocks.put_nowait(indata[:, 0].copy())
                except queue.Full:
                    pass

            threading.Thread(target=self.worker, daemon=True).start()
            with sd.InputStream(device=self.cfg["microphone"], channels=1, samplerate=rate, dtype="float32", blocksize=640, callback=callback):
                emit(event="ready", microphone=device["name"], wake_phrase=self.cfg["wake_phrase"])
                while not self.stopped.is_set():
                    try:
                        block = blocks.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    state = self.snapshot()
                    if state[0] != epoch:
                        pre.clear()
                        frames, rec, voiced, silent = [], False, 0, 0
                        epoch = state[0]
                    rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
                    if not rec:
                        pre.append(block)
                        voiced = voiced + 1 if rms >= threshold else 0
                        if voiced >= 3:
                            frames, rec, snapshot = list(pre), True, state
                    else:
                        frames.append(block)
                        silent = silent + 1 if rms < threshold else 0
                        if silent >= stop_count or len(frames) >= maximum:
                            # Bounded FIFO prevents unbounded transcription threads.
                            try:
                                self.jobs.put_nowait((np.concatenate(frames), snapshot, time.monotonic()))
                            except queue.Full:
                                emit(event="warning", error="Speech worker busy; utterance dropped")
                            pre.clear()
                            frames, rec, voiced, silent = [], False, 0, 0
        except Exception as exc:
            emit(event="fatal", error=f"Microphone unavailable: {exc}. Check Windows microphone privacy and input-device settings.")


def download_models(cfg):
    from faster_whisper import WhisperModel
    for name in dict.fromkeys((cfg["wake_model"], cfg["command_model"])):
        print(f"Downloading/loading {name} ...", flush=True)
        WhisperModel(name, device=cfg["device"], compute_type=cfg["compute_type"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts-worker", type=int)
    args = parser.parse_args()
    if args.tts_worker:
        import pyttsx3
        engine = pyttsx3.init("sapi5" if sys.platform == "win32" else None)
        engine.setProperty("rate", args.tts_worker)
        engine.say(sys.stdin.read())
        engine.runAndWait()
        return
    speaker = monitor = None
    try:
        for line in sys.stdin:
            rid = None
            try:
                req = json.loads(line)
                rid, op = req.get("id"), req.get("op")
                if op == "configure":
                    if monitor:
                        raise ValueError("Audio already configured")
                    cfg = {**DEFAULTS, **req["config"]}
                    validate(cfg)
                    speaker = Speaker(cfg)
                    monitor = Monitor(cfg, speaker)
                    threading.Thread(target=monitor.run, daemon=True).start()
                elif op == "quit":
                    emit(id=rid, ok=True)
                    break
                elif not monitor:
                    raise ValueError("Audio must be configured first")
                elif op == "state":
                    mode = req["mode"]
                    if mode not in {"busy", "sleep", "listen", "followup"}:
                        raise ValueError("Unknown listening mode")
                    monitor.state(mode)
                elif op == "speak":
                    monitor.state("busy")
                    speaker.speak(req["text"], req["token"])
                elif op == "stop_speaking":
                    speaker.stop()
                else:
                    raise ValueError(f"Unknown audio operation: {op}")
                emit(id=rid, ok=True)
            except Exception as exc:
                emit(id=rid, ok=False, error=str(exc))
    finally:
        if monitor:
            monitor.stopped.set()
        if speaker:
            speaker.stop()


if __name__ == "__main__":
    main()
