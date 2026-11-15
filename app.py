"""
Voice cloning web app.  Run:  .venv\\Scripts\\python app.py   then open http://127.0.0.1:5000
"""

import os
import atexit
import shutil
import tempfile
import uuid

from flask import Flask, jsonify, request, send_from_directory

from voice_cloner import VoiceCloner

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "output")
os.makedirs(OUT_DIR, exist_ok=True)

MAX_TEXT_CHARS = 1500

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap
cloner = VoiceCloner()
atexit.register(cloner.close)


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/status")
def status():
    return jsonify(ready=cloner.ready.is_set(), error=cloner.error)


@app.post("/api/clone")
def clone():
    audio = request.files.get("reference")
    text = (request.form.get("text") or "").strip()
    mode = request.form.get("mode", "zero_shot")
    transcript = request.form.get("transcript", "")

    if not audio or not audio.filename:
        return jsonify(error="Please upload a reference voice recording."), 400
    if not text:
        return jsonify(error="Please enter the text to speak."), 400
    if len(text) > MAX_TEXT_CHARS:
        return jsonify(error=f"Text is too long (max {MAX_TEXT_CHARS} characters)."), 400
    if mode not in ("zero_shot", "cross_lingual"):
        return jsonify(error="Invalid mode."), 400

    work = tempfile.mkdtemp(prefix="vc_")
    try:
        upload = os.path.join(work, "upload" + os.path.splitext(audio.filename)[1])
        audio.save(upload)
        ref = cloner.prepare_reference(upload, work, transcript)
        name = f"clone_{uuid.uuid4().hex[:8]}.wav"
        result = cloner.clone(text, ref, os.path.join(OUT_DIR, name), mode)
        return jsonify(
            url=f"/output/{name}",
            duration=result["duration"],
            transcript=ref["prompt_text"],
            language=ref["language"],
            reference_seconds=ref["seconds"],
        )
    except Exception as e:
        app.logger.exception("clone failed")
        return jsonify(error=str(e)), 500
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.get("/output/<path:name>")
def output(name):
    return send_from_directory(OUT_DIR, name)


if __name__ == "__main__":
    cloner.start()
    app.run(host="127.0.0.1", port=5000, threaded=True)
