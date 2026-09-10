#!/usr/bin/env python
from __future__ import annotations

import argparse, json, os, queue, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
from typing import Any
import numpy as np
import sounddevice as sd

HERE = Path(__file__).resolve().parent
CFG_PATH = Path(os.getenv('KIRO_VOICE_CONFIG', HERE / 'config.json'))
CFG = json.loads((CFG_PATH if CFG_PATH.exists() else HERE / 'config.example.json').read_text())
OUT = threading.Lock()


def emit(**msg):
    with OUT:
        print(json.dumps(msg, ensure_ascii=False), flush=True)


def norm(s: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r"[^a-z0-9\s']", ' ', s.casefold())).strip()


def strip_phrase(text: str, phrase: str):
    nt, np_ = norm(text), norm(phrase)
    if np_ not in nt:
        return False, text.strip()
    words = text.split()
    p = np_.split()
    nw = [norm(w) for w in words]
    for i in range(len(words) - len(p) + 1):
        if nw[i:i+len(p)] == p:
            return True, ' '.join(words[:i] + words[i+len(p):]).strip(' ,.!?;:')
    return True, text.strip()


def clean_tts(text: str) -> str:
    text = re.sub(r'```.*?```', ' I included a code block in the terminal. ', text, flags=re.S)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*_#>|]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    limit = int(CFG.get('tts_max_chars', 3500))
    if len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0] + '. The remainder is visible in the terminal.'
    return text


def beep(kind='wake'):
    if not CFG.get('activation_sound', True):
        return
    try:
        import winsound
        tones = {'wake': [(880,90),(1175,90)], 'sleep': [(660,90),(440,110)], 'cancel': [(350,110)]}
        for hz, ms in tones.get(kind, []):
            winsound.Beep(hz, ms)
    except Exception:
        pass


class Whisper:
    def __init__(self):
        self.models, self.lock = {}, threading.Lock()

    def transcribe(self, audio, purpose='command'):
        if audio.size == 0:
            return ''
        from faster_whisper import WhisperModel
        name = CFG.get('wake_whisper_model','tiny.en') if purpose == 'wake' else CFG.get('whisper_model','small.en')
        key = (name, CFG.get('whisper_device','cpu'), CFG.get('whisper_compute_type','int8'))
        with self.lock:
            if key not in self.models:
                self.models[key] = WhisperModel(key[0], device=key[1], compute_type=key[2])
            segs, _ = self.models[key].transcribe(audio.astype(np.float32), language='en', beam_size=1, vad_filter=True, condition_on_previous_text=False)
            return ' '.join(s.text.strip() for s in segs).strip()


class TTS:
    def __init__(self):
        self.proc = None
        self.tmp = None
        self.lock = threading.Lock()

    def speaking(self):
        with self.lock:
            return self.proc is not None and self.proc.poll() is None

    def stop(self):
        with self.lock:
            p, tmp = self.proc, self.tmp
            self.proc = self.tmp = None
        if p and p.poll() is None:
            p.terminate()
        if tmp:
            try: os.unlink(tmp)
            except OSError: pass

    def speak(self, text, followup):
        self.stop()
        text = clean_tts(text)
        if not text or not CFG.get('tts_enabled', True):
            emit(event='tts_finished', followup_seconds=followup); return
        fd, tmp = tempfile.mkstemp(suffix='.txt'); os.close(fd); Path(tmp).write_text(text)
        p = subprocess.Popen([sys.executable, '-u', __file__, '--tts-worker', tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self.lock: self.proc, self.tmp = p, tmp
        emit(event='tts_started')
        def wait():
            p.wait()
            with self.lock:
                active = self.proc is p
                if active: self.proc = self.tmp = None
            try: os.unlink(tmp)
            except OSError: pass
            if active: emit(event='tts_finished', followup_seconds=followup)
        threading.Thread(target=wait, daemon=True).start()


def tts_worker(path):
    import pyttsx3
    e = pyttsx3.init('sapi5')
    e.setProperty('rate', int(CFG.get('tts_rate',190)))
    e.setProperty('volume', float(CFG.get('tts_volume',1.0)))
    e.say(Path(path).read_text())
    e.runAndWait()


class Monitor:
    def __init__(self, whisper, tts):
        self.w, self.tts = whisper, tts
        self.armed_until = self.conv_until = 0.0
        self.force = False
        self.stop_evt = threading.Event()

    def arm(self, secs=None):
        self.armed_until = time.monotonic() + float(secs or CFG.get('command_arm_timeout_seconds',8))
        beep('wake'); emit(event='wake', phrase=CFG.get('wake_phrase','hey kiro'))

    def followup(self, secs=None):
        secs = float(secs or CFG.get('conversation_timeout_seconds',30))
        self.conv_until = time.monotonic() + secs
        emit(event='conversation_armed', seconds=secs)

    def sleep(self):
        self.armed_until = self.conv_until = 0
        self.force = False
        beep('sleep'); emit(event='sleep')

    def handle(self, audio):
        wake = CFG.get('wake_phrase','hey kiro')
        speaking = self.tts.speaking()
        if speaking:
            txt = self.w.transcribe(audio, 'wake')
            n = norm(txt)
            action = None
            for p in CFG.get('cancel_phrases',[]):
                if norm(p) in n: action='cancel'
            for p in CFG.get('stop_phrases',[]):
                if norm(p) in n: action=action or 'stop'
            name = norm(CFG.get('barge_name','kiro'))
            if not action and CFG.get('barge_in_enabled',True) and n.startswith(name): action='interrupt'
            if action:
                self.tts.stop(); beep('cancel'); emit(event='barge_in', action=action, text=txt)
                if action == 'interrupt':
                    cmd = self.w.transcribe(audio, 'command')
                    cmd = re.sub(r'^\s*kiro[\s,.:;-]*', '', cmd, flags=re.I).strip()
                    if cmd: emit(event='utterance', text=cmd, source='barge')
            return

        active = self.force or time.monotonic() < self.conv_until
        if active:
            self.force = False
            txt = self.w.transcribe(audio, 'command')
            if txt: emit(event='utterance', text=txt, source='conversation')
            return

        if time.monotonic() < self.armed_until:
            txt = self.w.transcribe(audio, 'command')
            found, rem = strip_phrase(txt, wake)
            if rem:
                emit(event='utterance', text=rem if found else txt, source='wake')
                self.armed_until = 0
            return

        if CFG.get('wake_backend','whisper_phrase') == 'whisper_phrase':
            txt = self.w.transcribe(audio, 'wake')
            found, _ = strip_phrase(txt, wake)
            if found:
                self.arm()
                cmd = self.w.transcribe(audio, 'command')
                _, rem = strip_phrase(cmd, wake)
                if rem:
                    emit(event='utterance', text=rem, source='wake'); self.armed_until = 0

    def run(self):
        sr = int(CFG.get('sample_rate',16000)); block_ms = int(CFG.get('block_ms',80)); bs = int(sr*block_ms/1000)
        threshold = float(CFG.get('speech_rms_threshold',0.012))
        start_need = max(1, int(CFG.get('speech_start_ms',200))/block_ms)
        stop_need = max(1, int(CFG.get('silence_stop_ms',850))/block_ms)
        max_blocks = max(1, int(float(CFG.get('max_utterance_seconds',45))*1000/block_ms))
        q = queue.Queue(maxsize=200); pre=[]; frames=[]; speech=silence=0; rec=False
        def cb(indata, *_):
            try: q.put_nowait(indata[:,0].copy())
            except queue.Full: pass
        emit(event='listening', mode=CFG.get('wake_backend','whisper_phrase'))
        with sd.InputStream(samplerate=sr, channels=1, dtype='float32', blocksize=bs, callback=cb):
            while not self.stop_evt.is_set():
                try: b=q.get(timeout=.25)
                except queue.Empty: continue
                rms=float(np.sqrt(np.mean(np.square(b), dtype=np.float64)))
                if not rec:
                    pre=(pre+[b])[-max(1,int(500/block_ms)):]
                    speech = speech+1 if rms>=threshold else max(0,speech-1)
                    if speech>=start_need: rec=True; frames=list(pre); silence=0
                else:
                    frames.append(b); silence = silence+1 if rms<threshold else 0
                    if silence>=stop_need or len(frames)>=max_blocks:
                        audio=np.concatenate(frames); rec=False; pre=[]; frames=[]; speech=silence=0
                        threading.Thread(target=self.handle,args=(audio,),daemon=True).start()


def device_info():
    idx=int(sd.default.device[0]); d=sd.query_devices(idx)
    return {'index':idx,'name':d['name'],'channels':int(d['max_input_channels']),'default_samplerate':float(d['default_samplerate'])}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--tts-worker'); args=ap.parse_args()
    if args.tts_worker: tts_worker(args.tts_worker); return
    w, t = Whisper(), TTS(); m=Monitor(w,t); threading.Thread(target=m.run,daemon=True).start()
    emit(event='ready', device=device_info(), config={'wake_phrase':CFG.get('wake_phrase','hey kiro'),'wake_backend':CFG.get('wake_backend','whisper_phrase'),'conversation_timeout_seconds':CFG.get('conversation_timeout_seconds',30)})
    for line in sys.stdin:
        rid=None
        try:
            req=json.loads(line); rid=req.get('id'); op=req.get('op')
            if op=='ping': emit(id=rid,ok=True,result='pong')
            elif op=='device': emit(id=rid,ok=True,result=device_info())
            elif op=='speak': t.speak(str(req.get('text','')),float(req.get('followup_seconds',30))); emit(id=rid,ok=True)
            elif op=='stop_speaking': t.stop(); emit(id=rid,ok=True)
            elif op=='arm_followup': m.followup(req.get('seconds')); emit(id=rid,ok=True)
            elif op=='force_listen': m.force=True; m.arm(); emit(id=rid,ok=True)
            elif op=='sleep': m.sleep(); emit(id=rid,ok=True)
            elif op=='status': emit(id=rid,ok=True,result={'speaking':t.speaking(),'armed':time.monotonic()<m.armed_until,'conversation':time.monotonic()<m.conv_until,'wake_phrase':CFG.get('wake_phrase','hey kiro')})
            elif op=='quit': emit(id=rid,ok=True); break
            else: raise ValueError(f'unknown operation: {op}')
        except Exception as e: emit(id=rid,ok=False,error=f'{type(e).__name__}: {e}')
    m.stop_evt.set(); t.stop()

if __name__=='__main__': main()
