# Voice Cloner

Zero-shot voice cloning in the browser. Upload a short recording of a voice, type English text, and get the text back spoken in that voice.

- **Backend:** Flask, [CosyVoice 3](https://github.com/FunAudioLLM/CosyVoice) for synthesis, [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for the reference transcript
- **Frontend:** plain HTML, CSS and JavaScript (no build step)

---

## How it works

```mermaid
flowchart LR
    A[Browser UI<br/>static/index.html] -->|reference audio + text| B[Flask API<br/>app.py]
    B --> C[Prepare reference<br/>voice_cloner.py]
    C --> C1[ffmpeg: mono, 24 kHz]
    C1 --> C2[faster-whisper:<br/>transcribe + detect language]
    C2 --> C3[Cut ~8 s span ending on a<br/>segment boundary]
    C3 --> D[CosyVoice worker<br/>worker.py, own venv]
    B -->|text| D
    D --> D1[Split text into<br/>sentence chunks]
    D1 --> D2[Zero-shot synthesis:<br/>reference speech + transcript]
    D2 --> D3{Length<br/>plausible?}
    D3 -- no --> D2
    D3 -- yes --> D4[Join chunks, write WAV]
    D4 --> B
    B -->|WAV URL| A
```

1. **Reference preparation.** The uploaded clip is converted with ffmpeg, transcribed by faster-whisper, and cut to a clean span of about 8 seconds (never more than 12) that ends on a segment boundary.
2. **Voice match mode (default).** CosyVoice receives both the reference speech and its transcript, so the voice and speaking style are carried from the first word. A second mode, *cross-lingual*, uses only a speaker embedding and is available under **Advanced**.
3. **Chunked synthesis.** The text is split into sentence chunks. The sampling in the model is random and sometimes stops early, so each chunk's duration is checked against its text length and the chunk is regenerated if it looks wrong.
4. **Persistent worker.** CosyVoice runs in a separate process and virtual environment (`.venv-cosyvoice`) and stays loaded between requests.

---

## Demo

The same examples are built into the web app (the **Examples** section on the page, with a *Try this example* button).

### Reference audio (the voice that was cloned)

*मुनि श्री प्रणम्य सागर जी प्रवचन अंश / muni shri Pranamya sagar ji Pravchan ansh* (320 kbps, about 10.9 s)

[▶ Play](https://github.com/Om-Arham-Foundation-Inc/VoiceCloner/blob/main/assets/player/reference.mp4)

### Output 1: `clone_4b9e1f8c.wav` (42.3 s)

> The old oak tree stood quietly at the edge of the abandoned garden, its weathered branches swaying gently in the morning breeze. A small brown bird landed briefly on a lower limb, chirped twice to test the air, and then darted away toward the sunlit hills. Down below, a faded wooden bench rested in the shade, covered in a thin layer of autumn leaves that crunched softly whenever the wind shifted.

[▶ Play](https://github.com/Om-Arham-Foundation-Inc/VoiceCloner/blob/main/assets/player/clone_4b9e1f8c.mp4)

### Output 2: `clone_edefe70d.wav` (26.6 s)

> There are many definitions of peace, but all of them are rooted in notions of individual flourishing, cooperation, mutual respect, and justice. It is one thing for children to be healthy, but an ideal world would foster children who are also peaceful

[▶ Play](https://github.com/Om-Arham-Foundation-Inc/VoiceCloner/blob/main/assets/player/clone_edefe70d.mp4)

The original files are in [`assets/`](assets/): the [reference MP3](assets/reference/muni-shri-pranamya-sagar-ji-pravchan-ansh_320kbps.mp3), [clone_4b9e1f8c.wav](assets/outputs/clone_4b9e1f8c.wav) with its [text](assets/outputs/clone_4b9e1f8c.txt), and [clone_edefe70d.wav](assets/outputs/clone_edefe70d.wav) with its [text](assets/outputs/clone_edefe70d.txt). The **Play** links open MP4 copies of the same audio (with a waveform picture) in `assets/player/`, because GitHub can preview video but not audio files.

---|---|
| [muni-shri-pranamya-sagar-ji-pravchan-ansh_320kbps.mp3](assets/reference/muni-shri-pranamya-sagar-ji-pravchan-ansh_320kbps.mp3) | Source recording: *मुनि श्री प्रणम्य सागर जी प्रवचन अंश / muni shri Pranamya sagar ji Pravchan ansh* (320 kbps, about 10.9 s) |

**Generated outputs**, both using the reference above:

| Output | Duration | Input text |
|---|---|---|
| [clone_4b9e1f8c.wav](assets/outputs/clone_4b9e1f8c.wav) | 42.3 s | *The old oak tree stood quietly at the edge of the abandoned garden, its weathered branches swaying gently in the morning breeze. A small brown bird landed briefly on a lower limb, chirped twice to test the air, and then darted away toward the sunlit hills. Down below, a faded wooden bench rested in the shade, covered in a thin layer of autumn leaves that crunched softly whenever the wind shifted.* ([text file](assets/outputs/clone_4b9e1f8c.txt)) |
| [clone_edefe70d.wav](assets/outputs/clone_edefe70d.wav) | 26.6 s | *There are many definitions of peace, but all of them are rooted in notions of individual flourishing, cooperation, mutual respect, and justice. It is one thing for children to be healthy, but an ideal world would foster children who are also peaceful* ([text file](assets/outputs/clone_edefe70d.txt)) |

GitHub does not play audio inside a README. Open a file link above and use the download or raw button to listen.

---

## Requirements

- Windows with an NVIDIA GPU (developed on an RTX 4060 Ti, 8 GB)
- Python 3.11
- [ffmpeg](https://ffmpeg.org/) on `PATH`
- The CosyVoice repository and the `Fun-CosyVoice3-0.5B` weights in `models/CosyVoice/` (see the CosyVoice project for setup), with its dependencies installed in `.venv-cosyvoice`
- The faster-whisper `medium` model is downloaded into `models/faster-whisper/` on first use

## Setup and run

```powershell
# web server environment
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# start the app
.venv\Scripts\python app.py
```

Open http://127.0.0.1:5000. The first page load shows "Loading voice model…" until CosyVoice has finished loading, which takes about a minute.

## Project layout

```
app.py             Flask server and API (/api/status, /api/clone)
voice_cloner.py    Reference preparation and worker management
worker.py          Persistent CosyVoice process (runs in .venv-cosyvoice)
static/            index.html, style.css, app.js
assets/            Demo reference audio, generated outputs, and README players
```

## Accent

CosyVoice has no accent setting. The accent and delivery come from the reference recording, so choose a reference whose accent matches what you want.

## Responsible use

Voice cloning can be misused for impersonation. Only clone voices you have permission to use, and only publish recordings you have the right to share.
