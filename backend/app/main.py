"""AutoEdit AI backend. Binds to localhost; CORS limited to the local frontend. Created by Rahul."""
import json, platform, re, shutil, subprocess, sys
from importlib.util import find_spec
from pathlib import Path

import psutil
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from . import ai, jobs, media as M
from .core import (AUDIO_EXT, DB_PATH, FONT_DIR, MAX_UPLOAD_BYTES, MODELS, ORIGINS, OUTPUTS, ROOT, THUMBS, UPLOADS, VIDEO_EXT,
                   get_settings, new_id, now, q, set_settings)
from .schemas import *

app = FastAPI(title="AutoEdit AI", version="0.1.0", description="Local-first AI video editing. Created by Rahul.")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"])
ID = r"^[0-9a-f]{12}$"


def err(code, msg, status):
    return JSONResponse({"error": {"code": code, "message": msg}}, status_code=status)


@app.exception_handler(M.MediaError)
async def _me(_, e): return err("media_error", str(e), 400)
@app.exception_handler(HTTPException)
async def _he(_, e): return err("http_error", str(e.detail), e.status_code)
@app.exception_handler(RequestValidationError)
async def _ve(_, e):
    f = e.errors()[0]
    return err("invalid_request", f"{'.'.join(str(x) for x in f['loc'][1:])}: {f['msg']}", 422)
@app.exception_handler(Exception)
async def _ex(_, e): return err("server_error", "Unexpected server error. See the backend window for details.", 500)


@app.on_event("startup")
def _startup():
    jobs.start()


def _check_id(v):
    if not re.match(ID, v):
        raise HTTPException(404, "Not found.")
    return v


def _media(mid):
    r = q("SELECT * FROM media WHERE id=?", (_check_id(mid),), one=True)
    if not r:
        raise HTTPException(404, "Media not found.")
    return r


def _proj(row):
    d = dict(row)
    d["plan"], d["subtitles"] = json.loads(d["plan"]), json.loads(d["subtitles"] or "[]")
    m = q("SELECT * FROM media WHERE id=?", (d["media_id"] or "",), one=True)
    d["media"] = {"id": m["id"], "name": m["name"], "kind": m["kind"], **json.loads(m["info"])} if m else None
    last = q("SELECT id FROM jobs WHERE project_id=? AND type='render' AND status='done' ORDER BY updated DESC LIMIT 1", (d["id"],), one=True)
    d["last_render_job"] = last["id"] if last else None
    return d


def _job(r):
    d = dict(r)
    d["result"] = json.loads(d["result"]) if d["result"] else None
    d.pop("params", None); d.pop("log", None); d.pop("output", None)
    return d


# ---------- health / system ----------
@app.get("/api/health")
def health():
    return {"status": "ok", "ffmpeg": shutil.which(M.FFMPEG) is not None, "ffprobe": shutil.which(M.FFPROBE) is not None}


@app.get("/api/system/info")
def system_info():
    gpu = None
    if platform.system() == "Windows":
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name -join '; '"],
                               capture_output=True, text=True, timeout=8)
            gpu = r.stdout.strip() or None
        except Exception:
            pass
    enc = M.encoders() if shutil.which(M.FFMPEG) else []
    du = shutil.disk_usage(OUTPUTS)
    used = sum(p.stat().st_size for d in (UPLOADS, OUTPUTS, MODELS) for p in d.rglob("*") if p.is_file())
    return {"os": platform.platform(), "python": sys.version.split()[0], "cpu_threads": psutil.cpu_count(),
            "ram_gb": round(psutil.virtual_memory().total / 2**30, 1), "disk_free_gb": round(du.free / 2**30, 1),
            "app_storage_mb": round(used / 2**20), "gpu": gpu, "encoders": enc,
            "ffmpeg": shutil.which(M.FFMPEG) is not None, "faster_whisper": find_spec("faster_whisper") is not None,
            "scenedetect": find_spec("scenedetect") is not None, "ollama": ai.ollama_tags() is not None,
            "font_dir": FONT_DIR or None, "max_upload_gb": MAX_UPLOAD_BYTES / 2**30,
            "acceleration": "Transcription runs on CPU (int8). " + ("AMD AMF hardware video encoding (h264_amf) is available for export."
                            if "h264_amf" in enc else "No AMD AMF encoder found in this FFmpeg build; export uses CPU."),
            "privacy": "All processing is local. Internet is used only when you click a model download."}


# ---------- settings ----------
@app.get("/api/settings")
def settings_get(): return get_settings()


@app.put("/api/settings")
def settings_put(p: SettingsPatch):
    set_settings(p.model_dump(exclude_none=True))
    return get_settings()


# ---------- models ----------
@app.get("/api/models")
def models_list(): return {"models": ai.models_status()}


@app.post("/api/models/download")
def models_download(b: ModelDownload):
    if not any(m["id"] == b.id for m in ai.REGISTRY):
        raise HTTPException(404, "Unknown model id.")
    return {"job_id": jobs.create("model", {"id": b.id})}


# ---------- media ----------
@app.post("/api/media/upload")
async def media_upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT | AUDIO_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use MP4, MOV, MKV, AVI (video) or MP3, WAV, M4A (audio).")
    mid = new_id()
    dest = UPLOADS / f"{mid}{ext}"
    size = 0
    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File is larger than the {MAX_UPLOAD_BYTES/2**30:.0f} GB upload limit (MAX_UPLOAD_GB).")
                f.write(chunk)
        if shutil.disk_usage(UPLOADS).free < 1 << 30:
            raise HTTPException(507, "Less than 1 GB of disk space is free.")
        info = await run_in_threadpool(M.probe, dest)
        M.check_limits(info)
        kind = "video" if ext in VIDEO_EXT else "audio"
        if kind == "video" and not info["has_video"]:
            raise HTTPException(400, "No video stream found in this file.")
        if kind == "audio" and not info["has_audio"]:
            raise HTTPException(400, "No audio stream found in this file.")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if kind == "video":
        (THUMBS / mid).mkdir(exist_ok=True)
        await run_in_threadpool(M.thumbnail, dest, THUMBS / mid / "thumb.jpg", min(1.0, info["duration"] / 2))
    name = re.sub(r"[^\w .()-]", "_", Path(file.filename).name)[:120]
    q("INSERT INTO media(id,name,path,kind,info,created) VALUES(?,?,?,?,?,?)", (mid, name, str(dest), kind, json.dumps(info), now()))
    return {"id": mid, "name": name, "kind": kind, **info}


@app.get("/api/media/{mid}/file")
def media_file(mid: str):
    return FileResponse(_media(mid)["path"])  # Starlette serves HTTP Range requests, so seeking works


@app.get("/api/media/{mid}/thumb/{name}")
def media_thumb(mid: str, name: str):
    _media(mid)
    if not re.match(r"^(thumb|s\d{1,3})\.jpg$", name) or not (THUMBS / mid / name).exists():
        raise HTTPException(404, "Thumbnail not found.")
    return FileResponse(THUMBS / mid / name)


@app.post("/api/media/{mid}/scenes")
def media_scenes(mid: str):
    _media(mid)
    return {"job_id": jobs.create("scenes", {"media_id": mid})}


# ---------- projects ----------
@app.post("/api/projects")
def project_create(b: ProjectCreate):
    if b.media_id:
        _media(b.media_id)
    s = get_settings()
    plan = {"resolution": s["default_resolution"], "codec": s["default_codec"],
            "subtitle_style": {"font": s["subtitle_font"]}, **ai.PRESETS.get(b.preset or "", {})}
    pid = new_id()
    q("INSERT INTO projects(id,name,media_id,plan,subtitles,created,updated) VALUES(?,?,?,?,?,?,?)",
      (pid, b.name, b.media_id, EditPlan(**plan).model_dump_json(), "[]", now(), now()))
    return _proj(q("SELECT * FROM projects WHERE id=?", (pid,), one=True))


@app.get("/api/projects")
def project_list():
    return {"projects": [_proj(r) for r in q("SELECT * FROM projects ORDER BY updated DESC")]}


def _get_proj(pid):
    r = q("SELECT * FROM projects WHERE id=?", (_check_id(pid),), one=True)
    if not r:
        raise HTTPException(404, "Project not found.")
    return r


@app.get("/api/projects/{pid}")
def project_get(pid: str): return _proj(_get_proj(pid))


@app.put("/api/projects/{pid}")
def project_put(pid: str, b: ProjectUpdate):
    r = _get_proj(pid)
    if b.media_id:
        _media(b.media_id)
    mid = b.media_id or r["media_id"]
    name = b.name or r["name"]
    plan = b.plan.model_dump_json() if b.plan else r["plan"]
    subs = json.dumps([c.model_dump() for c in b.subtitles]) if b.subtitles is not None else r["subtitles"]
    q("UPDATE projects SET name=?, media_id=?, plan=?, subtitles=?, version=version+1, updated=? WHERE id=?", (name, mid, plan, subs, now(), pid))
    return _proj(_get_proj(pid))


@app.post("/api/projects/{pid}/duplicate")
def project_dup(pid: str):
    r = _get_proj(pid)
    nid = new_id()
    q("INSERT INTO projects(id,name,media_id,plan,subtitles,created,updated) VALUES(?,?,?,?,?,?,?)",
      (nid, r["name"] + " (copy)", r["media_id"], r["plan"], r["subtitles"], now(), now()))
    return _proj(_get_proj(nid))


@app.delete("/api/projects/{pid}")
def project_delete(pid: str, delete_media: bool = False):
    r = _get_proj(pid)
    for j in q("SELECT id, output FROM jobs WHERE project_id=?", (pid,)):  # generated renders always go
        if j["output"]:
            Path(j["output"]).unlink(missing_ok=True)
    q("DELETE FROM jobs WHERE project_id=?", (pid,))
    q("DELETE FROM projects WHERE id=?", (pid,))
    if delete_media and r["media_id"] and not q("SELECT 1 FROM projects WHERE media_id=?", (r["media_id"],)):
        m = q("SELECT * FROM media WHERE id=?", (r["media_id"],), one=True)
        if m:
            Path(m["path"]).unlink(missing_ok=True)
            shutil.rmtree(THUMBS / m["id"], ignore_errors=True)
            q("DELETE FROM media WHERE id=?", (m["id"],))
    return {"deleted": True, "source_media_deleted": bool(delete_media)}


@app.get("/api/projects/{pid}/subtitles")
def project_subs(pid: str, format: str = "json", timeline: str = "source"):
    r = _get_proj(pid)
    cues = json.loads(r["subtitles"] or "[]")
    plan = EditPlan(**json.loads(r["plan"]))
    if timeline == "output":
        j = q("SELECT result FROM jobs WHERE project_id=? AND type='render' AND status='done' ORDER BY updated DESC LIMIT 1", (pid,), one=True)
        if not j:
            raise HTTPException(404, "Render the project first to export output-timeline subtitles.")
        cues = ai.remap_cues(cues, json.loads(j["result"])["ranges"], plan.speed)
    if format == "srt":
        return PlainTextResponse(ai.to_srt(cues), headers={"Content-Disposition": 'attachment; filename="subtitles.srt"'})
    if format == "ass":
        W, H = M.out_size(plan.aspect, plan.resolution)
        return PlainTextResponse(ai.to_ass(cues, plan, W, H), headers={"Content-Disposition": 'attachment; filename="subtitles.ass"'})
    return {"cues": cues}


# ---------- AI / jobs ----------
@app.post("/api/transcribe")
def transcribe(b: TranscribeRequest):
    _get_proj(b.project_id)
    return {"job_id": jobs.create("transcribe", {"project_id": b.project_id, "language": b.language}, b.project_id)}


@app.post("/api/edit-plan")
def edit_plan(b: PlanRequest):
    plan, source, notes, patch = ai.make_plan(b.prompt, b.base_plan)
    return {"plan": plan.model_dump(), "source": source, "notes": notes, "changes": patch}


@app.post("/api/render")
def render(b: RenderRequest):
    r = _get_proj(b.project_id)
    if not r["media_id"]:
        raise HTTPException(400, "Add a video to this project first.")
    return {"job_id": jobs.create("render", {"project_id": b.project_id}, b.project_id)}


@app.get("/api/jobs/{jid}")
def job_get(jid: str):
    r = q("SELECT * FROM jobs WHERE id=?", (_check_id(jid),), one=True)
    if not r:
        raise HTTPException(404, "Job not found.")
    return _job(r)


@app.post("/api/jobs/{jid}/cancel")
def job_cancel(jid: str):
    r = q("SELECT status FROM jobs WHERE id=?", (_check_id(jid),), one=True)
    if not r:
        raise HTTPException(404, "Job not found.")
    if r["status"] in ("queued", "running"):
        jobs.cancel(jid)
    return {"cancelling": r["status"] in ("queued", "running")}


@app.get("/api/jobs/{jid}/output")
def job_output(jid: str, download: bool = False):
    r = q("SELECT output FROM jobs WHERE id=? AND status='done'", (_check_id(jid),), one=True)
    if not r or not r["output"] or not Path(r["output"]).exists():
        raise HTTPException(404, "No finished output for this job.")
    return FileResponse(r["output"], media_type="video/mp4", filename="autoedit-output.mp4" if download else None,
                        content_disposition_type="attachment" if download else "inline")
