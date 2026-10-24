"""Config, paths, SQLite helpers. Everything stays on this machine."""
import json, os, sqlite3, threading, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _dir(key, default):
    p = Path(os.environ.get(key, str(ROOT / default))).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


UPLOADS = _dir("AUTOEDIT_UPLOADS", "media/uploads")
OUTPUTS = _dir("AUTOEDIT_OUTPUTS", "media/outputs")
TEMP = _dir("AUTOEDIT_TEMP", "media/temp")
THUMBS = _dir("AUTOEDIT_THUMBS", "media/thumbs")
MODELS = _dir("AUTOEDIT_MODELS", "models")
DB_PATH = _dir("AUTOEDIT_DB_DIR", "projects") / "autoedit.db"

MAX_UPLOAD_BYTES = int(float(os.environ.get("MAX_UPLOAD_GB", "4")) * 1024**3)
MAX_DURATION_S = int(os.environ.get("MAX_DURATION_S", "3600"))
MAX_CONCURRENT_JOBS = max(1, int(os.environ.get("MAX_CONCURRENT_JOBS", "1")))
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_PATH", "ffprobe")
FONT_DIR = os.environ.get("SUBTITLE_FONT_DIR", "")
OLLAMA_URL = "http://127.0.0.1:11434"
ORIGINS = ["http://127.0.0.1:3000", "http://localhost:3000"]

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

DEFAULT_SETTINGS = {
    "whisper_model": "base",
    "ollama_model": "qwen2.5:1.5b",
    "default_resolution": 720,
    "default_codec": "libx264",
    "subtitle_font": "Nirmala UI",
}

_conn = None
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY, name TEXT, path TEXT, kind TEXT, info TEXT, created REAL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, media_id TEXT, plan TEXT, subtitles TEXT,
  version INTEGER DEFAULT 1, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, type TEXT, status TEXT, progress REAL DEFAULT 0, message TEXT DEFAULT '',
  project_id TEXT, params TEXT, result TEXT, output TEXT, log TEXT DEFAULT '', created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
"""


def conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        # jobs left running by a previous crash can never finish
        _conn.execute("UPDATE jobs SET status='failed', message='Interrupted by restart' WHERE status IN ('queued','running')")
        _conn.commit()
    return _conn


def q(sql, args=(), one=False):
    with _lock:
        cur = conn().execute(sql, args)
        rows = cur.fetchall()
        conn().commit()
    if one:
        return rows[0] if rows else None
    return rows


def new_id():
    return uuid.uuid4().hex[:12]


def now():
    return time.time()


def get_settings():
    s = dict(DEFAULT_SETTINGS)
    for r in q("SELECT k, v FROM settings"):
        s[r["k"]] = json.loads(r["v"])
    return s


def set_settings(patch):
    for k, v in patch.items():
        q("INSERT INTO settings(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
