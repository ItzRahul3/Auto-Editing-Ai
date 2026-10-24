"use client";
import { useEffect, useRef, useState } from "react";
import { api, API, pollJob, post, put, upload } from "../lib/api";
import { Bar, Err, Field, Sel } from "./ui";

export const PRESETS: [string, string, string][] = [
  ["reel", "Vertical Reel", "9:16, 1080p, silence removed, gentle zoom, karaoke captions"],
  ["youtube", "YouTube 16:9", "1080p landscape with fades and loudness normalization"],
  ["square", "Square post", "1:1 with captions"],
  ["voice-clean", "Voice clean-up", "Cuts silence, reduces noise, normalizes volume"],
  ["cinematic", "Cinematic", "Slow push-in, soft contrast, long fades"],
];

export function NewProject({ open }: { open: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null), [p, setP] = useState(0), [busy, setBusy] = useState(false), [e, setE] = useState<string | null>(null);
  const [preset, setPreset] = useState(""), [drag, setDrag] = useState(false), ref = useRef<HTMLInputElement>(null);
  const go = async () => {
    if (!file) return; setBusy(true); setE(null);
    try {
      const m = await upload(file, setP);
      const pr: any = await post("/api/projects", { name: file.name.replace(/\.[^.]+$/, "").slice(0, 100) || "Untitled", media_id: m.id, preset: preset || undefined });
      open(pr.id);
    } catch (x: any) { setE(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="card space-y-3">
      <div onDragOver={(ev) => { ev.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(ev) => { ev.preventDefault(); setDrag(false); setFile(ev.dataTransfer.files[0] || null); }}
        onClick={() => ref.current?.click()} role="button" tabIndex={0} onKeyDown={(k) => k.key === "Enter" && ref.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center ${drag ? "border-violet bg-violet/10" : "border-edge"}`}>
        <input ref={ref} type="file" hidden accept=".mp4,.mov,.mkv,.avi,.m4v,.webm" onChange={(ev) => setFile(ev.target.files?.[0] || null)} />
        {file ? <div><b>{file.name}</b><div className="text-xs text-mute">{(file.size / 2 ** 20).toFixed(1)} MB. It stays on this computer.</div></div>
          : <div>Drop a video here, or click to choose<div className="text-xs text-mute">MP4, MOV, MKV, AVI</div></div>}
      </div>
      <Sel label="Start from a preset" v={preset} on={setPreset} opts={[["", "None (describe it in the editor)"], ...PRESETS.map(([k, n]) => [k, n] as [string, string])]} />
      {busy && <Bar p={p} msg="Uploading and checking the file..." />}
      <Err e={e} />
      <button className="btn-primary" disabled={!file || busy} onClick={go}>Create project</button>
    </div>
  );
}

export function Status({ info }: { info: any }) {
  if (!info) return <div className="card text-sm text-mute">Connecting to the local backend...</div>;
  const row = (k: string, v: any, ok?: boolean) => <div className="flex justify-between gap-3 py-0.5 text-sm"><span className="text-mute">{k}</span><span className={ok === false ? "text-amber-300" : ""}>{v}</span></div>;
  return (
    <div className="card">
      <div className="mb-2 text-sm font-semibold">Local processing</div>
      <div className="mb-2 text-xs text-mute">{info.privacy}</div>
      {row("FFmpeg", info.ffmpeg ? "found" : "missing (see README)", info.ffmpeg)}
      {row("Speech-to-text", info.faster_whisper ? "faster-whisper (CPU)" : "not installed", info.faster_whisper)}
      {row("Scene detection", info.scenedetect ? "PySceneDetect" : "basic only", info.scenedetect)}
      {row("Ollama (optional)", info.ollama ? "running" : "not running")}
      {row("GPU", info.gpu || "unknown")}
      {row("RAM / free disk", `${info.ram_gb} GB / ${info.disk_free_gb} GB`)}
      {row("App storage", `${info.app_storage_mb} MB`)}
      <div className="mt-2 text-xs text-mute">{info.acceleration}</div>
    </div>
  );
}

export function Projects({ open, limit }: { open: (id: string) => void; limit?: number }) {
  const [list, setList] = useState<any[] | null>(null), [e, setE] = useState<string | null>(null);
  const load = () => api("/api/projects").then((r) => setList(r.projects)).catch((x) => setE(x.message));
  useEffect(() => { load(); }, []);
  const del = async (p: any) => {
    const withMedia = confirm(`Delete "${p.name}" and its rendered videos?\n\nPress OK to continue. You will be asked separately about the source video.`);
    if (!withMedia) return;
    const src = confirm("Also delete the uploaded source video from disk?\n(OK = delete source too, Cancel = keep the source file)");
    await api(`/api/projects/${p.id}?delete_media=${src}`, { method: "DELETE" }).catch((x) => setE(x.message)); load();
  };
  const dup = async (p: any) => { await post(`/api/projects/${p.id}/duplicate`).catch((x) => setE(x.message)); load(); };
  const shown = (list || []).slice(0, limit || 999);
  return (
    <div className="space-y-2"><Err e={e} />
      {list && !list.length && <div className="card text-sm text-mute">No projects yet. Drop a video above to start one.</div>}
      {shown.map((p) => (
        <div key={p.id} className="card flex items-center gap-3">
          {p.media?.kind === "video" && <img alt="" className="h-14 w-24 rounded object-cover" src={`${API}/api/media/${p.media.id}/thumb/thumb.jpg`} />}
          <div className="min-w-0 flex-1"><div className="truncate font-medium">{p.name}</div>
            <div className="text-xs text-mute">{p.media ? `${p.media.width}x${p.media.height}, ${p.media.duration.toFixed(1)}s` : "No media"} · {p.plan.aspect} · {new Date(p.updated * 1000).toLocaleString()}</div></div>
          <button className="btn" onClick={() => open(p.id)}>Open</button>
          {!limit && <><button className="btn" onClick={() => dup(p)}>Duplicate</button><button className="btn" onClick={() => del(p)}>Delete</button></>}
        </div>))}
    </div>
  );
}

export function Templates({ open }: { open: (id: string) => void }) {
  const [e, setE] = useState<string | null>(null);
  const make = async (k: string, n: string) => { try { const pr: any = await post("/api/projects", { name: n, preset: k }); open(pr.id); } catch (x: any) { setE(x.message); } };
  return (<div className="space-y-3"><Err e={e} /><div className="grid gap-3 md:grid-cols-2">
    {PRESETS.map(([k, n, d]) => (<div key={k} className="card"><div className="font-medium">{n}</div><div className="mb-3 text-sm text-mute">{d}</div>
      <button className="btn" onClick={() => make(k, n)}>Create empty project with this preset</button></div>))}</div>
    <div className="text-xs text-mute">The empty project opens in the editor, where you can add a video.</div></div>);
}

export function Models() {
  const [ms, setMs] = useState<any[]>([]), [job, setJob] = useState<any>(null), [e, setE] = useState<string | null>(null);
  const load = () => api("/api/models").then((r) => setMs(r.models)).catch((x) => setE(x.message));
  useEffect(() => { load(); }, []);
  const dl = async (m: any) => {
    if (!confirm(`Download ${m.name}?\nSize: ${m.size}\nLicense: ${m.license}\n\nThis is the one step that uses the internet.`)) return;
    setE(null);
    try { const { job_id } = await post("/api/models/download", { id: m.id }); const j = await pollJob(job_id, (x) => setJob({ ...x, mid: m.id }));
      if (j.status === "failed") setE(j.message); } catch (x: any) { setE(x.message); } setJob(null); load();
  };
  return (<div className="space-y-3"><Err e={e} />
    <div className="text-sm text-mute">Nothing is downloaded automatically. Sizes are approximate and were not verified; check the source page before relying on them.</div>
    {ms.map((m) => (<div key={m.id} className="card space-y-1">
      <div className="flex items-center justify-between"><b>{m.name}</b><span className={m.installed ? "text-emerald-300" : "text-mute"}>{m.installed ? "Installed" : "Not installed"}</span></div>
      <div className="text-sm">{m.purpose}</div>
      <div className="text-xs text-mute">Size {m.size} · RAM {m.ram} · License: {m.license} · <a className="underline" href={m.source} target="_blank" rel="noreferrer">source</a>{m.note ? " · " + m.note : ""}</div>
      {job?.mid === m.id ? <div><Bar p={job.progress} msg={job.message} /><button className="btn mt-2" onClick={() => post(`/api/jobs/${job.id}/cancel`)}>Cancel</button></div>
        : !m.installed && <button className="btn" onClick={() => dl(m)}>Download</button>}
    </div>))}</div>);
}

export function SettingsView({ info }: { info: any }) {
  const [s, setS] = useState<any>(null), [e, setE] = useState<string | null>(null), [ok, setOk] = useState(false);
  useEffect(() => { api("/api/settings").then(setS).catch((x) => setE(x.message)); }, []);
  if (!s) return <Err e={e} />;
  const save = async (patch: any) => { try { setS(await put("/api/settings", patch)); setOk(true); setTimeout(() => setOk(false), 1200); } catch (x: any) { setE(x.message); } };
  const enc = info?.encoders || ["libx264"];
  return (<div className="card grid max-w-xl gap-3"><Err e={e} />
    <Sel label="Whisper model (install it in Model Manager)" v={s.whisper_model} on={(v) => save({ whisper_model: v })} opts={[["base", "base (faster)"], ["small", "small (more accurate)"]]} />
    <Sel label="Default resolution" v={s.default_resolution} on={(v) => save({ default_resolution: +v })} opts={[["720", "720p"], ["1080", "1080p"]]} />
    <Sel label="Default video codec" v={s.default_codec} on={(v) => save({ default_codec: v })} opts={[["libx264", "H.264 (CPU) - default"], ...(enc.includes("h264_amf") ? [["h264_amf", "H.264 AMD AMF (GPU encode)"]] : []), ...(enc.includes("libx265") ? [["libx265", "H.265 (CPU)"]] : [])] as [string, string][]} />
    <Field label="Ollama model for prompt parsing"><input className="input" defaultValue={s.ollama_model} onBlur={(ev) => save({ ollama_model: ev.target.value })} /></Field>
    <Field label="Subtitle font name (applies to new projects)"><input className="input" defaultValue={s.subtitle_font} onBlur={(ev) => save({ subtitle_font: ev.target.value })} /></Field>
    <div className="text-xs text-mute">Bengali needs a font that contains Bengali glyphs. "Nirmala UI" ships with Windows. For another font, install it in Windows (right-click the .ttf, Install) and type its exact name above. Upload limit, duration limit, folders and ffmpeg paths are set in the .env file. {ok && <span className="text-emerald-300">Saved.</span>}</div></div>);
}

export function About() {
  return (<div className="card max-w-2xl space-y-2 text-sm"><div className="text-lg font-semibold">AutoEdit AI</div>
    <p>A local-first video editor. Upload a clip, describe the edit in English or Bengali, review the plan, then render with FFmpeg. Videos, subtitles and projects stay in this folder; there is no telemetry and no API key.</p>
    <p className="text-mute">Speech-to-text: faster-whisper (MIT). Rendering: FFmpeg. Scenes: PySceneDetect. Optional prompt parsing: your local Ollama model. Each model's license is shown in Model Manager.</p>
    <p className="font-medium">Created by Rahul</p></div>);
}
