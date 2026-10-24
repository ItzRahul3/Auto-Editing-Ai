"""Background job queue (threads + SQLite state). Never blocks the web server."""
import json, queue, shutil, threading, traceback, urllib.request

from . import ai, media as M
from .core import MODELS, OLLAMA_URL, OUTPUTS, THUMBS, MAX_CONCURRENT_JOBS, new_id, now, q
from .schemas import EditPlan

QUEUE = queue.Queue()
CANCEL = set()
_COLS = {"status", "progress", "message", "result", "output", "log"}


def update(job_id, **f):
    f = {k: (json.dumps(v) if k == "result" else v) for k, v in f.items() if k in _COLS}
    if f:
        q(f"UPDATE jobs SET {', '.join(k + '=?' for k in f)}, updated=? WHERE id=?", (*f.values(), now(), job_id))


def create(jtype, params, project_id=None):
    jid = new_id()
    q("INSERT INTO jobs(id,type,status,progress,message,project_id,params,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
      (jid, jtype, "queued", 0, "Queued", project_id, json.dumps(params), now(), now()))
    QUEUE.put(jid)
    return jid


def cancel(jid):
    CANCEL.add(jid)
    p = M.PROCS.get(jid)
    if p:
        p.kill()


def _project(pid):
    pr = q("SELECT * FROM projects WHERE id=?", (pid,), one=True)
    if not pr:
        raise M.MediaError("Project not found.")
    md = q("SELECT * FROM media WHERE id=?", (pr["media_id"],), one=True)
    if not md:
        raise M.MediaError("The project has no source media. Upload a video first.")
    return pr, md


def h_render(job, params, progress, cancelled):
    pr, md = _project(params["project_id"])
    plan = EditPlan(**json.loads(pr["plan"]))
    subs = json.loads(pr["subtitles"] or "[]")
    info = json.loads(md["info"])
    ass_fn = None
    if plan.subtitles and subs:
        ass_fn = lambda ranges, W, H: ai.to_ass(ai.remap_cues(subs, ranges, plan.speed), plan, W, H)
    out = OUTPUTS / f"{job['id']}.mp4"
    ranges, dur = M.render(job["id"], plan, md["path"], info, ass_fn, out, progress, cancelled)
    return {"output": str(out), "ranges": ranges, "duration": dur, "subtitles_burned": bool(ass_fn)}


def h_transcribe(job, params, progress, cancelled):
    pr, md = _project(params["project_id"])
    info = json.loads(md["info"])
    if not info["has_audio"]:
        raise M.MediaError("This media has no audio track to transcribe.")
    cues, lang = ai.transcribe(md["path"], params.get("language"), progress, cancelled)
    q("UPDATE projects SET subtitles=?, updated=? WHERE id=?", (json.dumps(cues), now(), pr["id"]))
    return {"cues": len(cues), "language": lang}


def h_scenes(job, params, progress, cancelled):
    md = q("SELECT * FROM media WHERE id=?", (params["media_id"],), one=True)
    info = json.loads(md["info"])
    progress(0.05, "Detecting scenes...")
    scenes, note = M.detect_scenes(md["path"], info["duration"])
    scenes = scenes[:80]
    d = THUMBS / md["id"]
    d.mkdir(exist_ok=True)
    out = []
    for i, (a, b) in enumerate(scenes):
        if cancelled():
            raise M.MediaError("Cancelled.")
        M.thumbnail(md["path"], d / f"s{i}.jpg", a + min(0.5, (b - a) / 2))
        out.append({"start": round(a, 3), "end": round(b, 3), "thumb": f"s{i}.jpg"})
        progress(0.1 + 0.88 * (i + 1) / len(scenes), "Creating thumbnails...")
    info["scenes"], info["scene_note"] = out, note
    q("UPDATE media SET info=? WHERE id=?", (json.dumps(info), md["id"]))
    return {"scenes": len(out), "note": note}


def h_model(job, params, progress, cancelled):
    m = next((x for x in ai.REGISTRY if x["id"] == params["id"]), None)
    if not m:
        raise M.MediaError("Unknown model.")
    if m["kind"] == "hf":
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            raise M.MediaError("huggingface_hub is missing (installed with faster-whisper; rerun install.bat).")
        progress(0.1, "Downloading from huggingface.co (internet needed for this step only)...")
        snapshot_download(m["repo"], local_dir=str(MODELS / m["path"]))
        return {"installed": True}
    if ai.ollama_tags() is None:
        raise M.MediaError("Ollama is not running. Install it from ollama.com and start it, then retry.")
    req = urllib.request.Request(OLLAMA_URL + "/api/pull", json.dumps({"name": m["tag"], "stream": True}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        for line in r:
            if cancelled():
                raise M.MediaError("Cancelled.")
            d = json.loads(line)
            if d.get("total"):
                progress(d.get("completed", 0) / d["total"], d.get("status", "Downloading..."))
            elif "error" in d:
                raise M.MediaError(d["error"])
    return {"installed": True}


HANDLERS = {"render": h_render, "transcribe": h_transcribe, "scenes": h_scenes, "model": h_model}


def _work():
    while True:
        jid = QUEUE.get()
        try:
            job = q("SELECT * FROM jobs WHERE id=?", (jid,), one=True)
            if not job or jid in CANCEL:
                update(jid, status="cancelled", message="Cancelled")
                continue
            update(jid, status="running", message="Starting...")
            prog = lambda p, msg="": update(jid, progress=round(float(p), 4), message=msg or "Working...")
            res = HANDLERS[job["type"]](job, json.loads(job["params"]), prog, lambda: jid in CANCEL)
            extra = {"output": res.pop("output")} if "output" in res else {}
            update(jid, status="done", progress=1, message="Done", result=res, **extra)
        except M.MediaError as e:
            update(jid, status="cancelled" if jid in CANCEL else "failed", message=str(e))
        except Exception as e:  # unexpected: keep the traceback in the job log, show a short message
            update(jid, status="failed", message=f"Unexpected error: {e}", log=traceback.format_exc()[-4000:])
        finally:
            CANCEL.discard(jid)


def start():
    for _ in range(MAX_CONCURRENT_JOBS):
        threading.Thread(target=_work, daemon=True).start()
