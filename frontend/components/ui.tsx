import { ReactNode } from "react";
export const Field = ({ label, children }: { label: string; children: ReactNode }) => (<label className="block"><span className="label">{label}</span>{children}</label>);
export const Toggle = ({ label, v, on }: { label: string; v: boolean; on: (b: boolean) => void }) => (
  <label className="flex cursor-pointer items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-violet" checked={!!v} onChange={(e) => on(e.target.checked)} />{label}</label>);
export const Num = ({ label, v, on, min, max, step = 1 }: any) => (
  <Field label={label}><input type="number" className="input" value={v} min={min} max={max} step={step} onChange={(e) => on(parseFloat(e.target.value) || 0)} /></Field>);
export const Sel = ({ label, v, on, opts }: { label: string; v: any; on: (s: string) => void; opts: [string, string][] }) => (
  <Field label={label}><select className="input" value={v ?? ""} onChange={(e) => on(e.target.value)}>{opts.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></Field>);
export const Bar = ({ p, msg }: { p: number; msg?: string }) => (
  <div role="progressbar" aria-valuenow={Math.round(p * 100)} className="space-y-1"><div className="h-2 overflow-hidden rounded bg-ink"><div className="h-full bg-gradient-to-r from-violet to-sky" style={{ width: `${Math.round(p * 100)}%` }} /></div>
  <div className="text-xs text-mute">{msg} {Math.round(p * 100)}%</div></div>);
export const Err = ({ e }: { e: string | null }) => e ? <div role="alert" className="rounded-md border border-red-500/50 bg-red-500/10 p-2 text-sm text-red-300">{e}</div> : null;
