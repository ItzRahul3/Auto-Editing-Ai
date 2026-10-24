"""Local AI: faster-whisper transcription, subtitle builders, prompt -> edit plan, model registry."""
import json, re, tempfile, urllib.request
from pathlib import Path

from pydantic import ValidationError

from .core import MODELS, OLLAMA_URL, TEMP, get_settings
from .media import FFMPEG, MediaError, run
from .schemas import EditPlan, PlanPatch

# ---------------- model registry (sizes are approximate and NOT verified) ----------------
REGISTRY = [
    {"id": "whisper-base", "name": "faster-whisper base", "purpose": "Speech-to-text (CPU, int8). Fast; Bengali accuracy is modest.",
     "kind": "hf", "repo": "Systran/faster-whisper-base", "path": "whisper/base", "size": "~150 MB (approx.)", "ram": "~1 GB (approx.)",
     "license": "MIT", "source": "https://huggingface.co/Systran/faster-whisper-base"},
    {"id": "whisper-small", "name": "faster-whisper small", "purpose": "Speech-to-text (CPU, int8). Better accuracy, slower.",
     "kind": "hf", "repo": "Systran/faster-whisper-small", "path": "whisper/small", "size": "~490 MB (approx.)", "ram": "~2 GB (approx.)",
     "license": "MIT", "source": "https://huggingface.co/Systran/faster-whisper-small"},
    {"id": "ollama-qwen2.5-1.5b", "name": "Qwen2.5 1.5B (Ollama)", "purpose": "Optional: turns your prompt into an edit plan. Needs Ollama installed.",
     "kind": "ollama", "tag": "qwen2.5:1.5b", "size": "~1 GB (approx.)", "ram": "~2 GB (approx.)",
     "license": "Apache-2.0 (verify on the model page)", "source": "https://ollama.com/library/qwen2.5"},
]


def ollama_tags():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=1.5) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


def models_status():
    tags = ollama_tags()
    out = []
    for m in REGISTRY:
        d = dict(m)
        if m["kind"] == "hf":
            d["installed"] = (MODELS / m["path"] / "model.bin").exists()
        else:
            d["installed"] = bool(tags and any(t == m["tag"] or t.startswith(m["tag"]) for t in tags))
            d["note"] = "Ollama is running." if tags is not None else "Ollama is not running or not installed."
        out.append(d)
    return out


# ---------------- transcription ----------------
def transcribe(src, language, progress, cancelled):
    size = get_settings()["whisper_model"]
    mdir = MODELS / "whisper" / size
    if not (mdir / "model.bin").exists():
        raise MediaError(f"Whisper '{size}' is not installed. Open Model Manager and download it first.")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise MediaError("faster-whisper is not installed in this Python environment (run install.bat again).")
    with tempfile.TemporaryDirectory(dir=str(TEMP)) as td:
        wav = Path(td) / "a.wav"
        progress(0.02, "Extracting audio...")
        r = run([FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        if r.returncode != 0 or not wav.exists():
            raise MediaError("Could not extract audio (does the file have an audio track?).")
        progress(0.05, f"Loading Whisper {size} (CPU)...")
        model = WhisperModel(str(mdir), device="cpu", compute_type="int8")
        segs, info = model.transcribe(str(wav), language=language, word_timestamps=True, vad_filter=True)
        cues = []
        for s in segs:
            if cancelled():
                raise MediaError("Cancelled.")
            words = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)} for w in (s.words or []) if w.word.strip()]
            cues.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(), "words": words})
            progress(0.05 + 0.93 * min(s.end / max(info.duration, 0.1), 1), "Transcribing...")
        return cues, info.language


# ---------------- subtitles ----------------
def _map_time(t, ranges, speed):
    """Source time -> output time. Times inside removed regions snap to the next kept boundary."""
    off = 0.0
    for a, b in ranges:
        if t <= a:
            return off / speed
        if t < b:
            return (off + t - a) / speed
        off += b - a
    return off / speed


def remap_cues(cues, ranges, speed):
    out = []
    for c in cues:
        s, e = _map_time(c["start"], ranges, speed), _map_time(c["end"], ranges, speed)
        if e - s < 0.08:
            continue
        words = []
        for w in c.get("words") or []:
            ws, we = _map_time(w["s"], ranges, speed), _map_time(w["e"], ranges, speed)
            if we - ws >= 0.02:
                words.append({"w": w["w"], "s": ws, "e": we})
        out.append({"start": s, "end": e, "text": c["text"], "words": words})
    return out


def _ts(t, sep):
    t = max(t, 0)
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d}{sep}{int(round((s % 1) * 1000)):03d}".replace("1000", "999")


def to_srt(cues):
    return "\n".join(f"{i}\n{_ts(c['start'], ',')} --> {_ts(c['end'], ',')}\n{c['text']}\n" for i, c in enumerate(cues, 1))


def _ass_color(hex_, alpha="00"):
    h = hex_.lstrip("#")
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_t(t):
    cs = int(round(max(t, 0) * 100))
    return f"{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}"


def to_ass(cues, plan, W, H):
    st = plan.subtitle_style
    align = {"bottom": 2, "center": 5, "top": 8}[st.position]
    border, back = (3, _ass_color("#000000", "80")) if st.background else (1, _ass_color("#000000", "FF"))
    # In ASS karaoke, text starts in SecondaryColour and flips to PrimaryColour: primary = highlight.
    primary, secondary = (_ass_color(st.highlight), _ass_color(st.color)) if plan.karaoke else (_ass_color(st.color), _ass_color(st.color))
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
            "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Default,{st.font},{int(st.size * H / 1080 if H > W else st.size * H / 720)},{primary},{secondary},{_ass_color(st.outline)},{back},"
            f"-1,0,0,0,100,100,0,0,{border},{st.outline_width},0,{align},{int(W*0.06)},{int(W*0.06)},{int(H*0.08)},1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = []
    for c in cues:
        text = c["text"].replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        if plan.karaoke and c.get("words"):  # only when the model gave word timestamps
            text = " ".join("{\\k%d}%s" % (max(1, int(round((w["e"] - w["s"]) * 100))), w["w"].replace("{", "(").replace("}", ")")) for w in c["words"])
        lines.append(f"Dialogue: 0,{_ass_t(c['start'])},{_ass_t(c['end'])},Default,,0,0,0,,{text}")
    return head + "\n".join(lines) + "\n"


# ---------------- prompt -> edit plan ----------------
KW = [  # (regex, patch). English + Bengali + Banglish. Deterministic fallback for when no local LLM is available.
    (r"vertical|portrait|reel|9:16|shorts?|tiktok|insta(gram)?|ভার্টিক্যাল|রিল|শর্টস|ইনস্টা", {"aspect": "9:16"}),
    (r"landscape|16:9|youtube|horizontal|wide ?screen|ল্যান্ডস্কেপ|ইউটিউব", {"aspect": "16:9"}),
    (r"square|1:1|স্কয়ার|বর্গ", {"aspect": "1:1"}),
    (r"1080|full ?hd|\bfhd\b", {"resolution": 1080}),
    (r"\b720|\bhd\b", {"resolution": 720}),
    (r"silen|pause|dead ?air|\bgaps?\b|chup|faka|fanka|নীরব|বিরতি|সাইলেন্স|থামা|ফাঁকা|চুপ", {"remove_silence": True}),
    (r"sub ?title|subtittle|caption|সাবটাইটেল|ক্যাপশন|সাব-?টাইটেল", {"subtitles": True}),
    (r"bengali|bangla|bangali|bangla|বাংলা|বাঙালি", {"language": "bn", "subtitles": True}),
    (r"english|ইংরেজি|ইংলিশ", {"language": "en"}),
    (r"karaoke|highlight|animated|word by word|হাইলাইট|কারাওকে|অ্যানিমেটেড", {"karaoke": True, "subtitles": True}),
    (r"zoom[- ]?out|জুম আউট", {"zoom": "out"}),
    (r"zoom|push[- ]?in|জুম", {"zoom": "in"}),
    (r"noise|clarity|clean|clear|voice|awaj|audio|sound|নয়েজ|ভয়েস|পরিষ্কার|আওয়াজ|সাউন্ড", {"noise_reduction": True, "normalize_audio": True}),
    (r"fade|ফেড", {"fade_in": 0.5, "fade_out": 0.5}),
    (r"speed ?up|faster|fast|দ্রুত|জোরে", {"speed": 1.25}),
    (r"slow(er| ?down)?|ধীর|আস্তে", {"speed": 0.8}),
    (r"cinematic|সিনেমাটিক", {"zoom": "in", "contrast": 1.1, "saturation": 0.9, "fade_in": 1.0, "fade_out": 1.0}),
    (r"bright|উজ্জ্বল", {"brightness": 0.06}),
]
PLAN_KEYS = list(PlanPatch.model_fields.keys())


def _rules(prompt):
    p = {}
    for rx, patch in KW:
        if re.search(rx, prompt, re.I):
            p.update(patch)
    return p


def _ask_ollama(prompt, model):
    sys_p = ("You convert a video-editing request into JSON. Output ONLY a JSON object using these optional keys: "
             "aspect ('9:16'|'16:9'|'1:1'), resolution (720|1080), remove_silence (bool), zoom ('none'|'in'|'out'), "
             "fade_in (0-3), fade_out (0-3), speed (0.5-2), noise_reduction (bool), normalize_audio (bool), subtitles (bool), "
             "karaoke (bool), language ('bn'|'en'), brightness (-0.3..0.3), contrast (0.5..2), saturation (0..2). "
             "Omit keys that were not requested. The request may be in English or Bengali.")
    body = json.dumps({"model": model, "system": sys_p, "prompt": prompt, "stream": False, "format": "json",
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(json.load(r)["response"])


def make_plan(prompt, base):
    """Returns (plan, source, notes). LLM output is validated; invalid output falls back to rules."""
    base = base or EditPlan()
    notes, patch, source = [], None, "rules"
    s = get_settings()
    tags = ollama_tags()
    if tags is not None and any(t.startswith(s["ollama_model"]) for t in tags):
        try:
            raw = _ask_ollama(prompt, s["ollama_model"])
            patch = PlanPatch(**{k: v for k, v in raw.items() if k in PLAN_KEYS}).model_dump(exclude_none=True)
            source = "llm"
        except (ValidationError, Exception) as e:  # noqa - any failure => deterministic fallback
            notes.append(f"Local LLM output was unusable ({type(e).__name__}); used keyword rules instead.")
    else:
        notes.append("Ollama model not available; used keyword rules (English + Bengali).")
    if patch is None:
        patch = PlanPatch(**_rules(prompt)).model_dump(exclude_none=True)
    merged = base.model_copy(update=patch)
    plan = EditPlan(**merged.model_dump())  # re-validate the final plan
    if not patch:
        notes.append("No editing instructions recognised. Words that work: vertical/reel/square/landscape, silence/pause, subtitle, bangla, karaoke, zoom, fade, noise/clean voice, fast/slow, 1080. Bengali words work too.")
    return plan, source, notes, patch


PRESETS = {
    "reel": {"aspect": "9:16", "resolution": 1080, "remove_silence": True, "zoom": "in", "subtitles": True, "karaoke": True, "fade_out": 0.4, "noise_reduction": True},
    "youtube": {"aspect": "16:9", "resolution": 1080, "fade_in": 0.4, "fade_out": 0.6, "normalize_audio": True},
    "square": {"aspect": "1:1", "resolution": 1080, "subtitles": True},
    "voice-clean": {"remove_silence": True, "noise_reduction": True, "normalize_audio": True},
    "cinematic": {"aspect": "16:9", "zoom": "in", "zoom_amount": 0.06, "contrast": 1.1, "saturation": 0.9, "fade_in": 1, "fade_out": 1},
}
