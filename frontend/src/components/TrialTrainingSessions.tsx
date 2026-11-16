import { FormEvent, useEffect, useState } from "react";

type Skater = { id: string; display_name: string; name: string };
type Session = { id: string; session_date: string; location: string; duration_minutes: number; note: string };
async function request(path: string, method = "GET", data?: object) {
  const response = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: data ? JSON.stringify(data) : undefined });
  if (!response.ok) throw new Error(`保存或读取失败（HTTP ${response.status}），请重试并记录反馈。`);
  return response.json();
}

/** R0 keeps only the existing training CRUD API; no upload/analysis component is mounted. */
export default function TrialTrainingSessions() {
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [skater, setSkater] = useState("");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [date, setDate] = useState(new Date().toLocaleDateString("sv-SE"));
  const [location, setLocation] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    request("/api/skaters/").then((items: Skater[]) => {
      if (!Array.isArray(items)) throw new Error("无法读取选手资料。");
      if (active) { setSkaters(items); setSkater(items[0]?.id ?? ""); }
    }).catch(error => { if (active) setMessage(String(error)); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    setSessions([]); setEditing(null);
    if (skater) request(`/api/skaters/${skater}/sessions`).then(items => { if (active) setSessions(items); }).catch(error => { if (active) setMessage(String(error)); });
    return () => { active = false; };
  }, [skater]);
  async function save(event: FormEvent) {
    event.preventDefault(); if (busy || !skater) return;
    setBusy(true); setMessage("");
    try {
      await request(editing ? `/api/sessions/${editing}` : `/api/skaters/${skater}/sessions`, editing ? "PATCH" : "POST", {
        session_date: date, location, duration_minutes: minutes, note,
      });
      setSessions(await request(`/api/skaters/${skater}/sessions`));
      setEditing(null); setNote(""); setMessage("课次已保存。刷新或重启试用容器后可检查持久化。");
    } catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  }
  async function remove(id: string) {
    if (busy || !window.confirm("删除这条试用训练课次？")) return;
    setBusy(true);
    try { await request(`/api/sessions/${id}`, "DELETE"); setSessions(items => items.filter(item => item.id !== id)); if (editing === id) setEditing(null); setMessage("课次已删除。"); }
    catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  }
  return <section className="app-card mt-6 p-5" style={{color: "#172033"}}>
    <h3 className="text-xl font-semibold">训练课次（R0 可用）</h3>
    <p className="my-3">仅记录训练资料，不上传视频、不生成分析。首次试用请使用明显标为 NAS TRIAL 的合成记录。</p>
    <form onSubmit={save} className="grid gap-3">
      <label>选手<select className="app-select" value={skater} disabled={busy} onChange={event => setSkater(event.target.value)}>{skaters.map(item => <option key={item.id} value={item.id}>{item.display_name || item.name}</option>)}</select></label>
      <label>训练日期<input className="app-input" type="date" required value={date} onChange={event => setDate(event.target.value)} /></label>
      <label>训练地点<input className="app-input" required maxLength={200} value={location} onChange={event => setLocation(event.target.value)} /></label>
      <label>训练分钟<input className="app-input" type="number" min={1} max={1440} required value={minutes} onChange={event => setMinutes(Number(event.target.value))} /></label>
      <label>训练备注<textarea className="app-input" maxLength={2000} value={note} onChange={event => setNote(event.target.value)} /></label>
      <button className="app-pill min-h-[44px]" type="submit" disabled={busy || !skater}>{busy ? "正在保存…" : editing ? "保存课次修改" : "新建训练课次"}</button>
      {editing && <button type="button" disabled={busy} onClick={() => {setEditing(null);setNote("");}}>取消修改</button>}
    </form>
    <p role="status" className="my-3">{message}</p>
    <ul className="grid gap-3">{sessions.map(item => <li className="rounded-xl border p-3" key={item.id}>
      <p>{item.session_date} · {item.location} · {item.duration_minutes} 分钟</p><p>{item.note}</p>
      <button type="button" className="app-pill min-h-[44px] mr-3" disabled={busy} onClick={() => {setEditing(item.id);setDate(item.session_date);setLocation(item.location);setMinutes(item.duration_minutes);setNote(item.note || "");}}>修改课次</button>
      <button type="button" className="app-pill min-h-[44px]" disabled={busy} onClick={() => void remove(item.id)}>删除课次</button>
    </li>)}</ul>
    {!sessions.length && <p>还没有训练课次。</p>}
  </section>;
}
