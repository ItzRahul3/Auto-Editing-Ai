"""FFprobe / FFmpeg helpers and the render pipeline. All subprocess calls use argument lists (no shell)."""
import json, re, shutil, subprocess, threading
from collections import deque
from functools import lru_cache
from pathlib import Path

from .core import FFMPEG, FFPROBE, FONT_DIR, MAX_DURATION_S, OUTPUTS, TEMP, THUMBS, new_id

PROCS = {}  # job_id -> Popen (so cancel can kill ffmpeg)


class MediaError(Exception):
    pass


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError:
        raise MediaError("FFmpeg/FFprobe was not found. Install FFmpeg and add it to PATH (see README).")


def probe(path):
    r = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if r.returncode != 0:
        raise MediaError("This file could not be read as media (unsupported or corrupted): " + r.stderr.strip()[-200:])
    d = json.loads(r.stdout)
    st = d.get("streams", [])
    v = next((s for s in st if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in st if s["codec_type"] == "audio"), None)
    dur = float(d.get("format", {}).get("duration") or (v or {}).get("duration") or 0)
    fps = 0.0
    if v and v.get("avg_frame_rate", "0/0") not in ("0/0", "0"):
        n, _, den = v["avg_frame_rate"].partition("/")
        fps = round(float(n) / float(den or 1), 3) if float(den or 1) else 0.0
    return {"duration": dur, "width": (v or {}).get("width"), "height": (v or {}).get("height"), "fps": fps,
            "has_video": v is not None, "has_audio": a is not None,
            "video_codec": (v or {}).get("codec_name"), "audio_codec": (a or {}).get("codec_name"),
            "size": int(d.get("format", {}).get("size") or 0)}


def check_limits(info):
    if info["duration"] <= 0:
        raise MediaError("The file has no readable duration.")
    if info["duration"] > MAX_DURATION_S:
        raise MediaError(f"File is {info['duration']/60:.0f} min; the limit is {MAX_DURATION_S/60:.0f} min (MAX_DURATION_S).")


def thumbnail(src, out, t=1.0):
    r = run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", str(out)])
    if r.returncode != 0 or not Path(out).exists():  # very short clips: retry at 0
        run([FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", str(out)])


@lru_cache(maxsize=1)
def encoders():
    r = run([FFMPEG, "-hide_banner", "-encoders"])
    return sorted(n for n in ("libx264", "libx265", "h264_amf", "hevc_amf", "libvpx-vp9") if re.search(r"\s" + re.escape(n) + r"\s", r.stdout))


@lru_cache(maxsize=1)
def ffmpeg_version():
    r = run([FFMPEG, "-version"])
    m = re.search(r"ffmpeg version \S*?(\d+)\.(\d+)", r.stdout)
    return (int(m.group(1)), int(m.group(2))) if m else (7, 0)  # unparsable = dev build, assume recent


def silence_ranges(src, db=-35, min_dur=0.6, total=0.0):
    r = run([FFMPEG, "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af", f"silencedetect=noise={db}dB:d={min_dur}", "-f", "null", "-"])
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None and total:
        out.append((start, total))
    return out


def detect_scenes(src, duration, progress=lambda p: None):
    """PySceneDetect if installed; otherwise one scene covering the whole clip."""
    try:
        from scenedetect import ContentDetector, detect
    except ImportError:
        return [(0.0, duration)], "PySceneDetect not installed - showing a single scene."
    lst = detect(str(src), ContentDetector(threshold=27.0))
    if not lst:
        return [(0.0, duration)], "No scene changes found."
    return [(a.get_seconds(), b.get_seconds()) for a, b in lst], ""


def _subtract(ranges, cuts):
    out = []
    for a, b in ranges:
        cur = a
        for s, e in cuts:
            if e <= cur or s >= b:
                continue
            if s > cur:
                out.append((cur, s))
            cur = max(cur, e)
        if cur < b:
            out.append((cur, b))
    return out


def keep_ranges(plan, dur, silences):
    if plan.segments:
        base = sorted((s.start, min(s.end, dur)) for s in plan.segments if s.enabled)
    else:
        base = [(plan.trim_start, min(plan.trim_end or dur, dur))]
    if plan.remove_silence:
        pad = 0.12  # keep a little breathing room around speech
        cuts = [(s + pad, e - pad) for s, e in silences if e - s > 2 * pad + 0.05]
        base = _subtract(base, cuts)
    return [(a, b) for a, b in base if b - a >= 0.15]


def out_size(aspect, res):
    if aspect == "1:1":
        return res, res
    if aspect == "9:16":
        return res, (res * 16 // 9) // 2 * 2
    return (res * 16 // 9) // 2 * 2, res


def _esc_path(p):
    return str(p).replace("\\", "/").replace(":", "\\:")


def build_graph(plan, ranges, W, H, has_audio, out_dur, has_ass, fonts_dir):
    g, n, sp = [], len(ranges), plan.speed
    for i, (a, b) in enumerate(ranges):
        g.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            g.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
    ins = "".join(f"[v{i}]" + (f"[a{i}]" if has_audio else "") for i in range(n))
    g.append(f"{ins}concat=n={n}:v=1:a={1 if has_audio else 0}[cv]" + ("[ca]" if has_audio else ""))

    v = []
    if sp != 1:
        v.append(f"setpts=PTS/{sp}")
    v += [f"fps={plan.fps}", f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}"]
    if plan.zoom != "none":  # real time-varying zoom: scale evaluated per frame, then centre-crop
        p = f"min(t/{max(out_dur, 0.1):.3f},1)"
        f = f"(1+{plan.zoom_amount}*{p})" if plan.zoom == "in" else f"(1+{plan.zoom_amount}*(1-{p}))"
        v += [f"scale=w='trunc({W}*{f}/2)*2':h='trunc({H}*{f}/2)*2':eval=frame", f"crop={W}:{H}"]
    if plan.brightness or plan.contrast != 1 or plan.saturation != 1:
        v.append(f"eq=brightness={plan.brightness}:contrast={plan.contrast}:saturation={plan.saturation}")
    if plan.fade_in:
        v.append(f"fade=t=in:st=0:d={plan.fade_in}")
    if plan.fade_out:
        v.append(f"fade=t=out:st={max(out_dur - plan.fade_out, 0):.3f}:d={plan.fade_out}")
    if has_ass:
        v.append("ass=subs.ass" + (f":fontsdir='{_esc_path(fonts_dir)}'" if fonts_dir else ""))
    v += ["setsar=1", "format=yuv420p"]
    g.append("[cv]" + ",".join(v) + "[outv]")

    if has_audio:
        au = []
        if sp != 1:
            au.append(f"atempo={sp}")
        if plan.noise_reduction:
            au.append("afftdn=nf=-25")
        if plan.normalize_audio:
            au.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        if plan.audio_fade and plan.fade_in:
            au.append(f"afade=t=in:st=0:d={plan.fade_in}")
        if plan.audio_fade and plan.fade_out:
            au.append(f"afade=t=out:st={max(out_dur - plan.fade_out, 0):.3f}:d={plan.fade_out}")
        g.append("[ca]" + ",".join(au or ["anull"]) + "[outa]")
    return ";\n".join(g)


def render(job_id, plan, src, info, ass_text, out_path, progress, cancelled):
    """Returns (ranges, out_duration). Raises MediaError with an actionable message."""
    if not info["has_video"]:
        raise MediaError("The project's media has no video stream.")
    need = max(1 << 30, 2 * info.get("size", 0))
    free = shutil.disk_usage(OUTPUTS).free
    if free < need:
        raise MediaError(f"Not enough free disk space: need about {need/2**30:.1f} GB, have {free/2**30:.1f} GB.")
    codec = plan.codec
    if codec not in encoders():
        raise MediaError(f"Encoder '{codec}' is not available in this FFmpeg build. Pick H.264 (libx264) in the export settings.")

    work = TEMP / f"job_{job_id}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        silences = []
        if plan.remove_silence and info["has_audio"]:
            progress(0.02, "Detecting silence...")
            silences = silence_ranges(src, plan.silence_db, plan.silence_min, info["duration"])
        ranges = keep_ranges(plan, info["duration"], silences)
        if not ranges:
            raise MediaError("Nothing left to render: the selected range is empty or all of it was silence.")
        out_dur = sum(b - a for a, b in ranges) / plan.speed
        W, H = out_size(plan.aspect, plan.resolution)

        fonts_dir = None
        if ass_text:
            (work / "subs.ass").write_text(ass_text(ranges, W, H), encoding="utf-8-sig")
            if FONT_DIR and Path(FONT_DIR).is_dir():
                fonts_dir = Path(FONT_DIR)
        graph = build_graph(plan, ranges, W, H, info["has_audio"], out_dur, bool(ass_text), fonts_dir)
        script = work / "graph.txt"
        script.write_text(graph, encoding="utf-8")

        flag = "-/filter_complex" if ffmpeg_version()[0] >= 7 else "-filter_complex_script"
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
               "-i", str(src), flag, str(script), "-map", "[outv]"]
        if info["has_audio"]:
            cmd += ["-map", "[outa]"]
        if codec == "libx264":
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
        elif codec == "libx265":
            cmd += ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-tag:v", "hvc1"]
        else:  # h264_amf: AMD hardware encoder (encode only)
            cmd += ["-c:v", "h264_amf", "-quality", "quality", "-b:v", "10M" if plan.resolution == 1080 else "6M"]
        cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path)]

        progress(0.04, "Rendering...")
        proc = subprocess.Popen(cmd, cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace")
        PROCS[job_id] = proc
        tail = deque(maxlen=30)
        threading.Thread(target=lambda: [tail.append(l.rstrip()) for l in proc.stderr], daemon=True).start()
        for line in proc.stdout:
            k, _, val = line.strip().partition("=")
            if k in ("out_time_us", "out_time_ms") and val.isdigit():
                progress(min(0.98, 0.04 + 0.94 * int(val) / 1e6 / max(out_dur, 0.1)), "Rendering...")
        proc.wait()
        PROCS.pop(job_id, None)
        if cancelled():
            raise MediaError("Cancelled.")
        if proc.returncode != 0:
            raise MediaError("FFmpeg failed: " + " | ".join(list(tail)[-6:]))
        progress(0.99, "Validating output...")
        res = probe(out_path)
        if not res["has_video"] or res["duration"] < 0.1:
            raise MediaError("The rendered file failed validation (no video or zero length).")
        return ranges, out_dur
    except MediaError:
        Path(out_path).unlink(missing_ok=True)
        raise
    finally:
        PROCS.pop(job_id, None)
        shutil.rmtree(work, ignore_errors=True)
