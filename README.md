# AutoEdit AI
Local-first AI video editor for Windows 10/11. **Created by Rahul.**

> **Status: first working baseline, written but NOT run or tested.** Expect small bugs on first launch. See "Limitations".

Videos, subtitles, projects and renders stay in this folder. No API keys, no telemetry. The internet is used only when you click a model download (and by `install.bat` for packages).

## Install (Windows)
1. Install **Python 3.11** (tick "Add python.exe to PATH") and **Node.js 18+ LTS**.
2. Install **FFmpeg**: download a "release full" build from https://www.gyan.dev/ffmpeg/builds/, unzip to `C:\ffmpeg`, add `C:\ffmpeg\bin` to PATH, open a *new* terminal, check `ffmpeg -version` and `ffprobe -version`. (The "full" build includes libass, needed for burned-in subtitles. Use FFmpeg 6 or newer.)
3. Double-click `install.bat`.

## Run
Double-click `start.bat` (or run it in a terminal). Open **http://127.0.0.1:3000**. API docs: http://127.0.0.1:8000/docs. `stop.bat` closes both windows.

## First use
1. **Model Manager** → download *faster-whisper base* (≈150 MB, approximate) for subtitles. Optional: Ollama + Qwen2.5 1.5B for smarter prompt parsing (without it, keyword rules are used).
2. **Home** → drop a video → project opens.
3. Pick a preset or write a prompt (English/Bengali) → **Preview plan** → **Apply**.
4. **Transcribe locally** (or import SRT), fix text, **Render video**, then preview/download.

## Bengali subtitles
The font must contain Bengali glyphs. Windows ships **Nirmala UI** (default). For another font, install it in Windows and type its exact name in the subtitle style box. To use fonts from a folder, set `SUBTITLE_FONT_DIR` in `.env`. Whisper Bengali accuracy is limited (use `small` if you can) - always proofread. Complex conjuncts need libass built with HarfBuzz (the gyan.dev full build has it).

## AMD GPU
Transcription runs on **CPU** (int8). No ROCm/CUDA path is used. If your FFmpeg has `h264_amf`, you can choose **H.264 AMD AMF** for hardware *video encoding*.

## Implemented
Upload + FFprobe validation, thumbnails, scene detection (PySceneDetect) with enable/disable per scene, trim, silence removal, 9:16/16:9/1:1, time-varying zoom in/out, fades, speed (A/V synced), brightness/contrast/saturation, loudness normalize, noise reduction (afftdn), local Whisper transcription with word timestamps, subtitle editing, SRT import/export, ASS export, burned-in/karaoke subtitles, prompt→validated plan (LLM or rules), background render with real progress + cancel, output validation, projects (SQLite, versioned plan JSON, autosave, duplicate, delete with explicit source deletion), undo/redo, Model Manager, system info.

## Limitations / not implemented yet
- Not run or tested anywhere; FFmpeg filter graph and `-/filter_complex` handling are unverified on your build.
- No drag-based timeline (scene list + trim fields instead); no crossfade transitions, pan animation, background music mixing, browser voice recording, voice-as-instructions, VAD/source-separation options, or title cards.
- Audio-only uploads are accepted but only video projects are editable.
- Noise reduction is FFmpeg `afftdn`, not an AI model. Loudness normalization is single-pass.
- Model sizes shown are approximate and unverified; check each source page and license.
- Karaoke needs word timestamps; Whisper's Bengali word timing can be rough.

## Layout
`backend/app` (FastAPI: `main.py` API, `media.py` FFmpeg, `ai.py` Whisper/planner, `jobs.py` queue, `schemas.py`), `frontend` (Next.js), `models`, `projects` (SQLite), `media/{uploads,outputs,temp,thumbs}`. Config via `.env` (see `.env.example`).

## Troubleshooting
- "Cannot reach the backend": check the *AutoEdit Backend* window for errors.
- pip fails on `faster-whisper`/`scenedetect`: use Python 3.11 and rerun `install.bat`.
- Subtitles show boxes: the font lacks Bengali glyphs; change the font name.
