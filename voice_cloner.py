"""
Voice cloning engine: prepares the reference clip (convert, pick a clean 5-12 s span,
transcribe it with faster-whisper) and synthesizes new speech through a persistent
CosyVoice worker process.
"""

import os
import sys
import json
import shutil
import subprocess
import threading
from typing import Optional, Dict

ROOT = os.path.dirname(os.path.abspath(__file__))

# Windows: faster-whisper needs the CUDA DLLs that ship inside torch/lib.
_torch_lib = os.path.join(ROOT, ".venv", "Lib", "site-packages", "torch", "lib")
if os.name == "nt" and os.path.isdir(_torch_lib):
    os.add_dll_directory(_torch_lib)
    os.environ["PATH"] = _torch_lib + os.pathsep + os.environ.get("PATH", "")

WORKER_PYTHON = os.path.join(ROOT, ".venv-cosyvoice", "Scripts", "python.exe")
if not os.path.exists(WORKER_PYTHON):  # Linux / macOS layout
    WORKER_PYTHON = os.path.join(ROOT, ".venv-cosyvoice", "bin", "python")
REPO_DIR = os.path.join(ROOT, "models", "CosyVoice")
MODEL_DIR = os.path.join(REPO_DIR, "pretrained_models", "Fun-CosyVoice3-0.5B")
WHISPER_DIR = os.path.join(ROOT, "models", "faster-whisper")

PROMPT_TARGET_SEC = 8.0   # keep adding speech segments until the prompt reaches this length
PROMPT_MAX_SEC = 12.0     # never longer than this (longer prompts hurt text/speech alignment)
REF_ANALYSE_SEC = 30.0    # only the first 30 s of the upload are analysed


class VoiceCloner:
    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self._whisper = None
        self.ready = threading.Event()
        self.error: Optional[str] = None

    # ------------------------------------------------------------ worker
    def start(self):
        """Load CosyVoice in the background so the first request is not slow."""
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        with self._proc_lock:
            if self._proc and self._proc.poll() is None:
                return
            self.ready.clear()
            self.error = None
            for path in (WORKER_PYTHON, os.path.join(REPO_DIR, "cosyvoice"), os.path.join(MODEL_DIR, "llm.pt")):
                if not os.path.exists(path):
                    self.error = f"Missing required file: {path}"
                    return
            self._proc = subprocess.Popen(
                [WORKER_PYTHON, os.path.join(ROOT, "worker.py"), "--repo_dir", REPO_DIR, "--model_dir", MODEL_DIR],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                text=True, encoding="utf-8", bufsize=1,
            )
            line = self._proc.stdout.readline()
            if not line:
                self.error = "CosyVoice worker exited while loading (see server console)."
                return
            self.ready.set()

    def _call_worker(self, req: Dict) -> Dict:
        if not self.ready.wait(timeout=300):
            raise RuntimeError(self.error or "CosyVoice is still loading, try again shortly.")
        if self._proc.poll() is not None:  # crashed: restart once
            self._start_worker()
            if not self.ready.is_set():
                raise RuntimeError(self.error or "CosyVoice worker is not running.")
        self._proc.stdin.write(json.dumps(req) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            self.ready.clear()
            raise RuntimeError("CosyVoice worker crashed (see server console).")
        res = json.loads(line)
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "synthesis failed"))
        return res

    # ------------------------------------------------------------ reference
    def _get_whisper(self, force_cpu: bool = False):
        if self._whisper is None or force_cpu:
            from faster_whisper import WhisperModel
            if force_cpu:
                self._whisper = WhisperModel("medium", device="cpu", compute_type="int8",
                                             download_root=WHISPER_DIR)
            else:
                try:
                    self._whisper = WhisperModel("medium", device="cuda", compute_type="float16",
                                                 download_root=WHISPER_DIR)
                except Exception:
                    return self._get_whisper(force_cpu=True)
        return self._whisper

    def _transcribe(self, wav: str):
        def run(model):
            segments, info = model.transcribe(
                wav, vad_filter=True, beam_size=5, condition_on_previous_text=False)
            return list(segments), info  # decoding is lazy: errors surface here
        try:
            return run(self._get_whisper())
        except Exception:  # e.g. missing CUDA libraries -> CPU
            return run(self._get_whisper(force_cpu=True))

    def prepare_reference(self, upload_path: str, work_dir: str, transcript_override: str = "") -> Dict:
        """
        Convert the upload to 24 kHz mono, transcribe it, and cut it to a clean 5-12 s span that
        ends on a sentence/segment boundary. Returns {wav, prompt_text, language, seconds}.
        """
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg was not found on PATH.")
        os.makedirs(work_dir, exist_ok=True)
        full_wav = os.path.join(work_dir, "ref_full.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", upload_path, "-t", str(REF_ANALYSE_SEC), "-vn", "-ac", "1",
             "-ar", "24000", full_wav],
            check=True, capture_output=True,
        )

        segments, info = self._transcribe(full_wav)
        segs = [s for s in segments if s.text.strip()]
        if not segs:
            raise RuntimeError("No speech found in the reference audio. Upload a clip with a clearly spoken voice.")

        start = max(0.0, segs[0].start - 0.05)
        end, texts = start, []
        for s in segs:
            if s.end - start > PROMPT_MAX_SEC and texts:
                break
            texts.append(s.text.strip())
            end = s.end + 0.1
            if end - start >= PROMPT_TARGET_SEC:
                break

        wav = os.path.join(work_dir, "ref_prompt.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", full_wav, wav],
            check=True, capture_output=True,
        )
        prompt_text = transcript_override.strip() or " ".join(texts)
        return {"wav": wav, "prompt_text": prompt_text, "language": info.language, "seconds": round(end - start, 1)}

    # ------------------------------------------------------------ synthesis
    def clone(self, text: str, reference: Dict, out_path: str, mode: str = "zero_shot") -> Dict:
        text = text.strip()
        if not text:
            raise ValueError("Text must not be empty.")
        with self._gen_lock:  # one GPU job at a time
            return self._call_worker({
                "mode": mode,
                "speaker_wav": reference["wav"],
                "prompt_text": reference["prompt_text"],
                "text": text,
                "out": out_path,
            })

    def close(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
