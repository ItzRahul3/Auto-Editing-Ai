"use client";
import { useEffect, useRef, useState } from "react";
import { api, API, fmt, pollJob, post, put, upload } from "../lib/api";
import { Bar, Err, Num, Sel, Toggle } from "./ui";

type St = { plan: any; subs: any[] };
const parseSrt = (t: string) => t.replace(/\r/g, "").split(/\n\n+/).map((b) => {
  const l = b.trim().split("\n"); const i = l.findIndex((x) => x.includes("-->")); if (i < 0) return null;
  const m = l[i].match(/(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)/); if (!m) return null;
  const f = (h: string, mi: string, s: string, ms: string) => +h * 3600 + +mi * 60 + +s + +ms / 1000;
  return { start: f(m[1], m[2], m[3], m[4]), end: f(m[5], m[6], m[7], m[8]), text: l.slice(i + 1).join("\n"), words: [] };
}).filter(Boolean) as any[];

export default function Editor({ id, info }: { id: string; info: any }) {
  const [proj, setProj] = useState<any>(null), [st, setSt] = useState<St | null>(null), [name, setName] = useState("");
  const [past, setPast] = useState<St[]>([]), [future, setFuture] = useState<St[]>([]);
  const [saved, setSaved] = useState(true), [e, setE] = useState<string | null>(null), [t, setT] = useState(0);
  const [prompt, setPrompt] = useState(""), [preview, setPreview] = useState<any>(null);
  const [job, setJob] = useState<any>(null), [kind, setKind] = useState<string>(""), [outJob, setOutJob] = useState<string | null>(null), [showOut, setShowOut] = useState(false);
  const [lang, setLang] = useState(""), vid = useRef<HTMLVideoElement>(null), cancelled = useRef(false);

  const load = async () => { const p = await api("/api/projects/" + id); setProj(p); setName(p.name); setSt({ plan: p.plan, subs: p.subtitles }); setOutJob(p.last_render_job); setShowOut(!!p.last_render_job); };
  useEffect(() => { load().catch((x) => setE(x.message)); }, [id]);
  useEffect(() => { if (saved || !st) return; const h = setTimeout(() => flush().catch((x) => setE(x.message)), 1000); return () => clearTimeout(h); }, [st, name, saved]);

  if (!proj || !st) return <Err e={e} />;
  const { plan, subs } = st, m = proj.media;
  const flush = async () => { await put("/api/projects/" + id, { name, plan: st.plan, subtitles: st.subs }); setSaved(true); };
  const commit = (n: Partial<St>) => { setPast((p) => [...p.slice(-50), st]); setFuture([]); setSt({ ...st, ...n }); setSaved(false); };
  const setP = (k: string, v: any) => commit({ plan: { ...plan, [k]: v } });
  const setStyle = (k: string, v: any) => commit({ plan: { ...plan, subtitle_style: { ...plan.subtitle_style, [k]: v } } });
  const undo = () => { if (!past.length) return; setFuture([st, ...future]); setSt(past[past.length - 1]); setPast(past.slice(0, -1)); setSaved(false); };
  const redo = () => { if (!future.length) return; setPast([...past, st]); setSt(future[0]); setFuture(future.slice(1)); setSaved(false); };

  const run = async (k: string, start: () => Promise<{ job_id: string }>, after?: (j: any) => void) => {
    setE(null); setKind(k); cancelled.current = false;
    try { await flush(); const { job_id } = await start(); const j = await pollJob(job_id, setJob);
      if (j.status === "failed") setE(j.message); else if (j.status === "done") after?.(j); } catch (x: any) { setE(x.message); }
    setJob(null); setKind("");
  };
  const attach = async (f: File) => { try { setKind("upload"); const md = await upload(f, (p) => setJob({ progress: p, message: "Uploading..." })); await put("/api/projects/" + id, { media_id: md.id }); await load(); } catch (x: any) { setE(x.message); } setJob(null); setKind(""); };

  const scenes: any[] = m?.scenes || [];
  const toggleScene = (i: number) => {
    const base = plan.segments ?? scenes.map((s) => ({ start: s.start, end: s.end, enabled: true }));
    const nx = base.map((s: any, j: number) => (j === i ? { ...s, enabled: !s.enabled } : s));
    setP("segments", nx.every((s: any) => s.enabled) ? null : nx);
  };
  const cue = !showOut ? subs.find((c) => t >= c.start && t <= c.end) : null, S = plan.subtitle_style;
  const upCue = (i: number, patch: any) => commit({ subs: subs.map((c, j) => (j === i ? { ...c, ...patch, ...(patch.text !== undefined ? { words: [] } : {}) } : c)) });
  const srcUrl = m ? `${API}/api/media/${m.id}/file` : "";
  const outUrl = outJob ? `${API}/api/jobs/${outJob}/output` : "";
  const encs: string[] = info?.encoders || ["libx264"];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <input className="input max-w-sm font-medium" value={name} onChange={(ev) => { setName(ev.target.value); setSaved(false); }} aria-label="Project name" />
          <button className="btn" onClick={undo} disabled={!past.length}>Undo</button><button className="btn" onClick={redo} disabled={!future.length}>Redo</button>
          <span className="text-xs text-mute">{saved ? "Saved" : "Saving..."}</span>
        </div>
        <Err e={e} />
        {!m ? <div className="card text-sm"><div className="mb-2">This project has no video yet.</div><input type="file" accept=".mp4,.mov,.mkv,.avi,.m4v,.webm" onChange={(ev) => ev.target.files?.[0] && attach(ev.target.files[0])} />{kind === "upload" && job && <Bar p={job.progress} msg={job.message} />}</div> : (<>
          <div className="relative overflow-hidden rounded-lg border border-edge bg-black">
            <video ref={vid} key={showOut ? outUrl : srcUrl} src={showOut ? outUrl : srcUrl} controls className="mx-auto max-h-[60vh] w-full" onTimeUpdate={(ev) => setT(ev.currentTarget.currentTime)} />
            {cue && plan.subtitles && <div className={`pointer-events-none absolute inset-x-0 px-6 text-center ${S.position === "top" ? "top-4" : S.position === "center" ? "top-1/2 -translate-y-1/2" : "bottom-14"}`}
              style={{ color: S.color, fontFamily: `"${S.font}", "Nirmala UI", sans-serif`, fontSize: Math.max(14, S.size / 3), textShadow: `0 0 ${S.outline_width}px ${S.outline}, 0 0 ${S.outline_width}px ${S.outline}`, background: S.background ? "rgba(0,0,0,.5)" : undefined }}>{cue.text}</div>}
          </div>
          <div className="flex items-center gap-2 text-xs text-mute">
            <span>{m.width}x{m.height} · {m.fps} fps · {fmt(m.duration)} · {m.has_audio ? "audio" : "no audio"}</span>
            {outJob && <><button className="btn ml-auto" onClick={() => setShowOut(false)} disabled={!showOut}>Original</button><button className="btn" onClick={() => setShowOut(true)} disabled={showOut}>Rendered</button></>}
          </div>
          <div className="card space-y-2">
            <div className="flex items-center justify-between"><b className="text-sm">Scenes</b>
              <button className="btn" disabled={!!kind} onClick={() => run("scenes", () => post("/api/media/" + m.id + "/scenes"), () => load())}>{scenes.length ? "Re-detect" : "Detect scenes"}</button></div>
            {kind === "scenes" && job && <Bar p={job.progress} msg={job.message} />}
            {m.scene_note && <div className="text-xs text-mute">{m.scene_note}</div>}
            <div className="flex gap-2 overflow-x-auto pb-1">{scenes.map((s, i) => { const on = plan.segments ? plan.segments[i]?.enabled : true; return (
              <div key={i} className={`w-32 shrink-0 rounded border p-1 text-xs ${on ? "border-violet" : "border-edge opacity-50"}`}>
                <img alt="" className="mb-1 aspect-video w-full cursor-pointer rounded object-cover" src={`${API}/api/media/${m.id}/thumb/${s.thumb}`} onClick={() => { if (vid.current) vid.current.currentTime = s.start; }} />
                <label className="flex items-center gap-1"><input type="checkbox" className="accent-violet" checked={on} onChange={() => toggleScene(i)} />{fmt(s.start)}-{fmt(s.end)}</label></div>); })}</div>
            <div className="grid grid-cols-2 gap-2"><Num label="Trim start (s)" v={plan.trim_start} min={0} step={0.1} on={(v: number) => setP("trim_start", v)} />
              <Num label="Trim end (s, 0 = to the end)" v={plan.trim_end ?? 0} min={0} step={0.1} on={(v: number) => setP("trim_end", v > 0 ? v : null)} /></div>
          </div></>)}
        <div className="card space-y-2">
          <div className="flex items-center justify-between"><b className="text-sm">Subtitles</b>
            <div className="flex flex-wrap items-center gap-2">
              <select className="input w-28" value={lang} onChange={(ev) => setLang(ev.target.value)} aria-label="Language"><option value="">Auto</option><option value="bn">Bengali</option><option value="en">English</option></select>
              <button className="btn" disabled={!!kind || !m?.has_audio} onClick={() => run("transcribe", () => post("/api/transcribe", { project_id: id, language: lang || null }), async () => { await load(); setSt((x) => (x ? { ...x, plan: { ...x.plan, subtitles: true } } : x)); setSaved(false); })}>Transcribe locally</button>
              <label className="btn cursor-pointer">Import SRT<input type="file" accept=".srt" hidden onChange={async (ev) => { const f = ev.target.files?.[0]; if (f) commit({ subs: parseSrt(await f.text()), plan: { ...plan, subtitles: true } }); }} /></label>
              <a className="btn" href={`${API}/api/projects/${id}/subtitles?format=srt`}>Export SRT</a><a className="btn" href={`${API}/api/projects/${id}/subtitles?format=ass`}>Export ASS</a></div></div>
          {kind === "transcribe" && job && <Bar p={job.progress} msg={job.message} />}
          {!subs.length && <div className="text-xs text-mute">No subtitles yet. Transcribe (needs a Whisper model from Model Manager) or import an SRT file.</div>}
          <div className="max-h-72 space-y-1 overflow-y-auto">{subs.map((c, i) => (
            <div key={i} className="grid grid-cols-[4.5rem_4.5rem_1fr_auto] items-center gap-1">
              <input className="input" type="number" step={0.1} value={+c.start.toFixed(2)} onChange={(ev) => upCue(i, { start: +ev.target.value })} aria-label="Start" />
              <input className="input" type="number" step={0.1} value={+c.end.toFixed(2)} onChange={(ev) => upCue(i, { end: +ev.target.value })} aria-label="End" />
              <input className="input" value={c.text} onChange={(ev) => upCue(i, { text: ev.target.value })} onFocus={() => { if (vid.current && !showOut) vid.current.currentTime = c.start; }} />
              <button className="btn" onClick={() => commit({ subs: subs.filter((_, j) => j !== i) })} aria-label="Delete cue">x</button></div>))}</div>
          {!!subs.length && <div className="text-xs text-mute">Editing a line's text clears its word timing, so karaoke highlight skips that line.</div>}
        </div>
      </div>

      <div className="space-y-3">
        <div className="card space-y-2"><b className="text-sm">Describe the edit</b>
          <textarea className="input h-20" value={prompt} onChange={(ev) => setPrompt(ev.target.value)} placeholder="vertical reel, remove long pauses, Bengali karaoke subtitles, gentle zoom, clean the voice  (বাংলাতেও লিখতে পারো)" />
          <button className="btn" disabled={!prompt.trim()} onClick={async () => { setE(null); try { setPreview(await post("/api/edit-plan", { prompt, base_plan: plan })); } catch (x: any) { setE(x.message); } }}>Preview plan</button>
          {preview && <div className="rounded border border-edge p-2 text-sm"><div className="text-xs text-mute">Parsed by: {preview.source === "llm" ? "local LLM (validated)" : "keyword rules"}</div>
            {Object.keys(preview.changes).length ? <ul className="my-1 list-disc pl-5">{Object.entries(preview.changes).map(([k, v]) => <li key={k}>{k}: <b>{String(v)}</b></li>)}</ul> : <div className="my-1">No changes recognised.</div>}
            {preview.notes.map((n: string, i: number) => <div key={i} className="text-xs text-amber-300">{n}</div>)}
            <button className="btn-primary mt-1" disabled={!Object.keys(preview.changes).length} onClick={() => { commit({ plan: preview.plan }); setPreview(null); }}>Apply to project</button></div>}
        </div>
        <div className="card grid grid-cols-2 gap-3"><b className="col-span-2 text-sm">Format and cuts</b>
          <Sel label="Aspect ratio" v={plan.aspect} on={(v) => setP("aspect", v)} opts={[["9:16", "9:16 vertical"], ["16:9", "16:9 landscape"], ["1:1", "1:1 square"]]} />
          <Sel label="Resolution" v={plan.resolution} on={(v) => setP("resolution", +v)} opts={[["720", "720p"], ["1080", "1080p"]]} />
          <Num label="FPS" v={plan.fps} min={12} max={60} on={(v: number) => setP("fps", Math.min(60, Math.max(12, v)))} />
          <Sel label="Codec" v={plan.codec} on={(v) => setP("codec", v)} opts={[["libx264", "H.264 (default)"], ...(encs.includes("h264_amf") ? [["h264_amf", "H.264 AMD AMF"]] : []), ...(encs.includes("libx265") ? [["libx265", "H.265"]] : [])] as [string, string][]} />
          <div className="col-span-2"><Toggle label="Remove long silent pauses" v={plan.remove_silence} on={(v) => setP("remove_silence", v)} /></div>
          {plan.remove_silence && <><Num label="Silence threshold (dB)" v={plan.silence_db} min={-60} max={-15} on={(v: number) => setP("silence_db", v)} /><Num label="Min pause (s)" v={plan.silence_min} min={0.2} max={3} step={0.1} on={(v: number) => setP("silence_min", v)} /></>}
        </div>
        <div className="card grid grid-cols-2 gap-3"><b className="col-span-2 text-sm">Motion, look and sound</b>
          <Sel label="Zoom" v={plan.zoom} on={(v) => setP("zoom", v)} opts={[["none", "None"], ["in", "Slow zoom in"], ["out", "Slow zoom out"]]} />
          <Num label="Zoom amount" v={plan.zoom_amount} min={0.02} max={0.3} step={0.02} on={(v: number) => setP("zoom_amount", v)} />
          <Num label="Fade in (s)" v={plan.fade_in} min={0} max={3} step={0.1} on={(v: number) => setP("fade_in", v)} /><Num label="Fade out (s)" v={plan.fade_out} min={0} max={3} step={0.1} on={(v: number) => setP("fade_out", v)} />
          <Num label="Speed" v={plan.speed} min={0.5} max={2} step={0.05} on={(v: number) => setP("speed", Math.min(2, Math.max(0.5, v)))} />
          <Num label="Brightness" v={plan.brightness} min={-0.3} max={0.3} step={0.02} on={(v: number) => setP("brightness", v)} />
          <Num label="Contrast" v={plan.contrast} min={0.5} max={2} step={0.05} on={(v: number) => setP("contrast", v)} /><Num label="Saturation" v={plan.saturation} min={0} max={2} step={0.05} on={(v: number) => setP("saturation", v)} />
          <Toggle label="Normalize volume" v={plan.normalize_audio} on={(v) => setP("normalize_audio", v)} /><Toggle label="Reduce background noise" v={plan.noise_reduction} on={(v) => setP("noise_reduction", v)} />
          <Toggle label="Fade audio with video" v={plan.audio_fade} on={(v) => setP("audio_fade", v)} />
        </div>
        <div className="card grid grid-cols-2 gap-3"><b className="col-span-2 text-sm">Subtitle style</b>
          <Toggle label="Burn subtitles into video" v={plan.subtitles} on={(v) => setP("subtitles", v)} /><Toggle label="Karaoke highlight" v={plan.karaoke} on={(v) => setP("karaoke", v)} />
          <Num label="Size" v={S.size} min={10} max={140} on={(v: number) => setStyle("size", Math.min(140, Math.max(10, v)))} />
          <Sel label="Position" v={S.position} on={(v) => setStyle("position", v)} opts={[["bottom", "Bottom"], ["center", "Center"], ["top", "Top"]]} />
          <label className="text-xs text-mute">Text<input type="color" className="mt-1 block h-8 w-full" value={S.color} onChange={(ev) => setStyle("color", ev.target.value)} /></label>
          <label className="text-xs text-mute">Highlight<input type="color" className="mt-1 block h-8 w-full" value={S.highlight} onChange={(ev) => setStyle("highlight", ev.target.value)} /></label>
          <label className="text-xs text-mute">Outline<input type="color" className="mt-1 block h-8 w-full" value={S.outline} onChange={(ev) => setStyle("outline", ev.target.value)} /></label>
          <Num label="Outline width" v={S.outline_width} min={0} max={12} on={(v: number) => setStyle("outline_width", Math.min(12, Math.max(0, v)))} />
          <label className="col-span-2 text-xs text-mute">Font name (must support Bengali for Bengali text)<input className="input mt-1" defaultValue={S.font} onBlur={(ev) => /^[\w .-]{1,60}$/.test(ev.target.value) && setStyle("font", ev.target.value)} /></label>
          <div className="col-span-2"><Toggle label="Dark background box" v={S.background} on={(v) => setStyle("background", v)} /></div>
        </div>
        <div className="card space-y-2"><b className="text-sm">Render and export</b>
          {kind === "render" && job ? <><Bar p={job.progress} msg={job.message} /><button className="btn" onClick={() => post(`/api/jobs/${job.id}/cancel`)}>Cancel render</button></> :
            <button className="btn-primary" disabled={!m || !!kind} onClick={() => run("render", () => post("/api/render", { project_id: id }), (j) => { setOutJob(j.id); setShowOut(true); })}>Render video</button>}
          {outJob && <a className="btn inline-block" href={`${API}/api/jobs/${outJob}/output?download=true`}>Download MP4</a>}
          <div className="text-xs text-mute">Rendering runs on your CPU (or AMD AMF if selected). Speed depends on your machine.</div>
        </div>
      </div>
    </div>
  );
}
