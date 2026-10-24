"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Editor from "../components/Editor";
import { About, Models, NewProject, Projects, SettingsView, Status, Templates } from "../components/Views";

const NAV = ["Home", "New Project", "My Projects", "Templates", "Model Manager", "Settings", "About"];

export default function App() {
  const [view, setView] = useState("Home"), [pid, setPid] = useState<string | null>(null), [info, setInfo] = useState<any>(null), [err, setErr] = useState<string | null>(null);
  useEffect(() => { api("/api/system/info").then(setInfo).catch((e) => setErr(e.message)); }, [view]);
  const open = (id: string) => { setPid(id); setView("Editor"); };
  const go = (v: string) => { setView(v); if (v !== "Editor") setPid(pid); };
  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex flex-1">
        <nav className="w-52 shrink-0 border-r border-edge bg-panel p-3" aria-label="Main">
          <div className="mb-4 bg-gradient-to-r from-violet to-sky bg-clip-text text-xl font-bold text-transparent">AutoEdit AI</div>
          {[...NAV, ...(pid ? ["Editor"] : [])].map((n) => (
            <button key={n} onClick={() => go(n)} aria-current={view === n} className={`mb-1 block w-full rounded-md px-3 py-2 text-left text-sm ${view === n ? "bg-violet/20 text-white" : "text-mute hover:bg-ink"}`}>{n === "Editor" ? "Current project" : n}</button>))}
        </nav>
        <main className="min-w-0 flex-1 p-5">
          {err && <div role="alert" className="mb-3 rounded-md border border-amber-500/50 bg-amber-500/10 p-2 text-sm text-amber-200">{err}</div>}
          {view === "Home" && <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]"><div className="space-y-4"><h1 className="text-lg font-semibold">Start with a video</h1><NewProject open={open} /><h2 className="font-semibold">Recent projects</h2><Projects open={open} limit={4} /></div><Status info={info} /></div>}
          {view === "New Project" && <div className="max-w-2xl space-y-3"><h1 className="text-lg font-semibold">New project</h1><NewProject open={open} /></div>}
          {view === "My Projects" && <div className="max-w-3xl space-y-3"><h1 className="text-lg font-semibold">My projects</h1><Projects open={open} /></div>}
          {view === "Templates" && <div className="space-y-3"><h1 className="text-lg font-semibold">Templates</h1><Templates open={open} /></div>}
          {view === "Model Manager" && <div className="max-w-3xl space-y-3"><h1 className="text-lg font-semibold">Model Manager</h1><Models /></div>}
          {view === "Settings" && <div className="space-y-3"><h1 className="text-lg font-semibold">Settings</h1><SettingsView info={info} /></div>}
          {view === "About" && <About />}
          {view === "Editor" && pid && <Editor id={pid} info={info} />}
        </main>
      </div>
      <footer className="border-t border-edge px-5 py-2 text-xs text-mute">Created by Rahul</footer>
    </div>
  );
}
