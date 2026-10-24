export const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  let r: Response;
  try { r = await fetch(API + path, opts); }
  catch { throw new Error("Cannot reach the AutoEdit backend at " + API + ". Is start.bat running?"); }
  const j = await r.json().catch(() => null);
  if (!r.ok) throw new Error(j?.error?.message || r.statusText);
  return j as T;
}
export const post = (p: string, body?: any) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
export const put = (p: string, body: any) => api(p, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function upload(file: File, onProgress: (p: number) => void): Promise<any> {
  return new Promise((res, rej) => {
    const x = new XMLHttpRequest(), fd = new FormData();
    fd.append("file", file);
    x.open("POST", API + "/api/media/upload");
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => { let j: any = null; try { j = JSON.parse(x.responseText); } catch {} x.status < 300 ? res(j) : rej(new Error(j?.error?.message || "Upload failed")); };
    x.onerror = () => rej(new Error("Cannot reach the AutoEdit backend. Is start.bat running?"));
    x.send(fd);
  });
}

export async function pollJob(id: string, on: (j: any) => void, stop?: () => boolean): Promise<any> {
  for (;;) {
    const j = await api("/api/jobs/" + id);
    on(j);
    if (["done", "failed", "cancelled"].includes(j.status) || stop?.()) return j;
    await new Promise((r) => setTimeout(r, 700));
  }
}
export const fmt = (s: number) => { s = Math.max(0, s || 0); return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`; };
