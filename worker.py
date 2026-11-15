"""
Persistent CosyVoice worker. Runs inside .venv-cosyvoice (its pinned dependencies are
isolated from the web server's environment) and keeps the model loaded between requests.

Protocol: one JSON object per line on stdin, one reply per line on stdout.
  request : {"mode": "zero_shot"|"cross_lingual", "speaker_wav", "prompt_text", "text", "out"}
  reply   : {"ok": true, "sample_rate": 24000, "duration": 4.2} | {"ok": false, "error": "..."}
A {"ready": true} line is printed once the model has loaded.
"""

import os
import sys
import json
import argparse

# Everything the libraries print goes to stderr; stdout carries only protocol lines.
PROTO = sys.stdout
sys.stdout = sys.stderr
sys.stdin.reconfigure(encoding="utf-8")   # Windows default is cp1252; transcripts can be Hindi
PROTO.reconfigure(encoding="utf-8")

PREFIX = "You are a helpful assistant.<|endofprompt|>"  # required by Fun-CosyVoice3


def reply(obj):
    PROTO.write(json.dumps(obj, ensure_ascii=False) + "\n")
    PROTO.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo_dir", required=True)
    ap.add_argument("--model_dir", required=True)
    args = ap.parse_args()

    sys.path.insert(0, args.repo_dir)
    sys.path.insert(0, os.path.join(args.repo_dir, "third_party", "Matcha-TTS"))
    os.chdir(args.repo_dir)

    import numpy as np
    import librosa
    import soundfile as sf
    import torch
    from cosyvoice.cli.cosyvoice import AutoModel

    model = AutoModel(model_dir=args.model_dir)
    sr = model.sample_rate
    reply({"ready": True, "sample_rate": sr})

    import re
    import random

    MIN_CHARS, MAX_CHARS = 70, 260   # sentences are merged/split into chunks of this size
    CHARS_PER_SEC = 14.0             # typical English speaking rate, used to sanity-check output
    MAX_TRIES = 4

    def chunk_text(text):
        """Split into sentences, then merge short ones: zero-shot is unstable on very short text."""
        sents = [x.strip() for x in re.split(r"(?<=[.!?।])\s+|\n+", text) if x.strip()]
        chunks, cur = [], ""
        for sent in sents:
            if cur and len(cur) + 1 + len(sent) > MAX_CHARS:
                chunks.append(cur)
                cur = sent
            else:
                cur = f"{cur} {sent}".strip()
            if len(cur) >= MIN_CHARS:
                chunks.append(cur)
                cur = ""
        if cur:
            if chunks and len(cur) < MIN_CHARS and len(chunks[-1]) + len(cur) < MAX_CHARS:
                chunks[-1] += " " + cur
            else:
                chunks.append(cur)
        return chunks

    def synth_once(chunk, req, mode):
        seed = random.randrange(1 << 30)
        torch.manual_seed(seed)
        with torch.no_grad():
            if mode == "zero_shot":
                # The model hears the reference speech *and* its transcript, so timbre,
                # accent and rhythm are carried from the very first word.
                gen = model.inference_zero_shot(
                    chunk, PREFIX + req["prompt_text"].strip(), req["speaker_wav"], stream=False)
            else:
                # Only a speaker embedding is used: weaker identity, generic accent.
                gen = model.inference_cross_lingual(PREFIX + chunk, req["speaker_wav"], stream=False)
            audio = np.concatenate([o["tts_speech"].cpu().numpy().reshape(-1) for o in gen]).astype(np.float32)
        _, (lo, hi) = librosa.effects.trim(audio, top_db=35, frame_length=512, hop_length=128)
        pad = int(sr * 0.05)
        return audio[max(0, lo - pad):min(len(audio), hi + pad)]

    def plausibility(chunk, audio):
        """Ratio of actual to expected duration; sampling sometimes stops early or rambles."""
        expected = max(len(chunk) / CHARS_PER_SEC, 0.8)
        return (len(audio) / sr) / expected

    def synth_chunk(chunk, req):
        mode = req["mode"] if req.get("prompt_text", "").strip() else "cross_lingual"
        best, best_err = None, 1e9
        for attempt in range(MAX_TRIES):
            m = mode if attempt < MAX_TRIES - 1 or mode == "cross_lingual" else "cross_lingual"
            audio = synth_once(chunk, req, m)
            ratio = plausibility(chunk, audio)
            err = abs(np.log(max(ratio, 1e-3)))
            if err < best_err:
                best, best_err = audio, err
            if 0.55 <= ratio <= 2.0:
                return audio
            print(f"[worker] retry {attempt + 1}: ratio {ratio:.2f} for {chunk[:40]!r}", flush=True)
        return best

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            parts, gap = [], np.zeros(int(sr * 0.2), dtype=np.float32)
            for chunk in chunk_text(req["text"].strip()):
                if parts:
                    parts.append(gap)
                parts.append(synth_chunk(chunk, req))
            audio = np.concatenate(parts)

            os.makedirs(os.path.dirname(os.path.abspath(req["out"])), exist_ok=True)
            sf.write(req["out"], audio, sr)
            reply({"ok": True, "sample_rate": sr, "duration": round(len(audio) / sr, 2)})
        except Exception as e:  # keep the worker alive for the next request
            import traceback
            traceback.print_exc()
            reply({"ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
