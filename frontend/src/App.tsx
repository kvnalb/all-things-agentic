import { useEffect, useState } from "react";
import { ArrowRight, CalendarDays, CheckCircle2, RefreshCw } from "lucide-react";

type Course = { id: string; code: string; title: string; role: string };
type Status = { google_connected: boolean; canvas_connected: boolean; last_run?: { state: string; summary?: Record<string, number> }; next_sync_at: string };
type DailyTask = Record<string, string | number | boolean>;
type Daily = { active: DailyTask[]; upcoming: DailyTask[] };
type Calibration = {
  global_effort_multiplier: number;
  global_samples: number;
  by_course: Record<string, { effort_multiplier: number; samples: number }>;
};

const defaults = { priority_mode: "grade", lead_time_days: 5, reminder_style: "ramping", work_day_start: 9, work_day_end: 21, off_days: [], priority_courses: [], excluded_courses: [], daily_cap_hours: 4, effort_padding: 1.2 };

export default function App() {
  const [screen, setScreen] = useState<"login" | "setup" | "dashboard">("login");
  const [courses, setCourses] = useState<Course[]>([]), [selected, setSelected] = useState<string[]>([]);
  const [status, setStatus] = useState<Status | null>(null), [daily, setDaily] = useState<Daily>({ active: [], upcoming: [] });
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [activity, setActivity] = useState<Array<Record<string, unknown>>>([]), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [priorityMode, setPriorityMode] = useState("grade"), [lead, setLead] = useState(5), [cap, setCap] = useState(4);
  const [dataUrl, setDataUrl] = useState("https://data101.org/fa26/"), [mathUrl, setMathUrl] = useState("https://ethanebb.github.io/Teaching%20Pages/Math110Fall26.html");
  const [syllabus, setSyllabus] = useState<File | null>(null), [syllabusCourse, setSyllabusCourse] = useState("");
  const [actualHours, setActualHours] = useState<Record<string, string>>({});

  async function api(path: string, options?: RequestInit) {
    const response = await fetch(path, options);
    if (response.status === 401) { setScreen("login"); throw new Error("Connect Google to continue"); }
    if (!response.ok) {
      const text = await response.text();
      try { throw new Error(JSON.parse(text).detail || "Request failed"); }
      catch (error) { if (error instanceof SyntaxError) throw new Error(text || `Request failed (${response.status})`); throw error; }
    }
    return response.json();
  }
  async function refresh() {
    try {
      const nextStatus = await api("/api/status"); setStatus(nextStatus);
      if (nextStatus.canvas_connected) {
        const [view, runs, cal] = await Promise.all([api("/api/daily"), api("/api/activity"), api("/api/calibration")]);
        setDaily(view); setActivity(runs); setCalibration(cal); setScreen("dashboard");
      } else setScreen("setup");
    } catch { /* login screen is set by api */ }
  }
  useEffect(() => { void refresh(); }, []);

  async function discover() { setBusy(true); try { const result = await api("/api/connectors/canvas", { method: "POST" }); setCourses(result.courses); setMessage(`Canvas connected as ${result.identity_label}`); } catch (error) { setMessage(String(error)); } finally { setBusy(false); } }
  async function saveAndSync() {
    setBusy(true); setMessage("Starting the semester agent…");
    try {
      await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...defaults, selected_course_ids: selected, priority_mode: priorityMode, lead_time_days: lead, daily_cap_hours: cap }) });
      const dataCourse = courses.find(course => course.code.includes("C187")); const mathCourse = courses.find(course => course.code.includes("MATH 110"));
      if (dataCourse && dataUrl) await api("/api/sources/url", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course_id: dataCourse.id, label: "Data 101 Fall 2026", url: dataUrl }) });
      if (mathCourse && mathUrl) await api("/api/sources/url", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course_id: mathCourse.id, label: "Math 110 Fall 2026", url: mathUrl }) });
      if (syllabus && syllabusCourse) {
        const upload = new FormData(); upload.append("course_id", syllabusCourse); upload.append("file", syllabus);
        await api("/api/sources/upload", { method: "POST", body: upload });
      }
      await api("/api/sync", { method: "POST" }); await refresh();
    } catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  }
  async function syncNow() { setBusy(true); try { await api("/api/sync", { method: "POST" }); await refresh(); } catch (error) { setMessage(String(error)); } finally { setBusy(false); } }

  async function submitFeedback(task: DailyTask, rating: "too_low" | "about_right" | "too_high") {
    const taskKey = String(task.task_key || "");
    if (!taskKey) return;
    const estimated = Number(task.estimated_hours || task.hours || 2);
    const rawActual = actualHours[taskKey]?.trim();
    const parsedActual = rawActual ? Number(rawActual) : undefined;
    setBusy(true);
    try {
      const result = await api("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_key: taskKey,
          title: String(task.title),
          course: String(task.course || ""),
          estimated_hours: estimated,
          rating,
          actual_hours: parsedActual && parsedActual > 0 ? parsedActual : null,
        }),
      });
      setCalibration(result.calibration);
      setMessage("Thanks — future estimates for this course will adjust.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  const learnedCourses = calibration ? Object.entries(calibration.by_course).filter(([, value]) => value.samples > 0).length : 0;

  return <main className="shell">
    <aside className="signal-rail"><div className="wordmark">StudyAgent</div><div className="rail-copy"><p className="eyebrow">Fall 2026 · Taskmaster</p><h1>Your semester keeps itself current.</h1><p className="lede">Canvas and syllabi become a source-linked calendar and a daily answer to “what should I work on?”</p></div><ol className="steps"><li className="active"><span className="step-node">●</span><span className="step-number">01</span><span>Connect sources</span></li><li className={screen === "dashboard" ? "active" : ""}><span className="step-node">●</span><span className="step-number">02</span><span>Manage semester</span></li></ol></aside>
    <section className="workspace"><header className="workspace-header"><span className="status-chip">{busy ? "Agent working" : status?.last_run?.state || "Ready"}</span><span className="utility">Cloud Run · ADK 2</span></header><div className="setup-card">
      {screen === "login" && <><div className="icon-tile"><CalendarDays/></div><p className="eyebrow">Owner setup</p><h2>Connect your calendar</h2><p>StudyAgent creates one separate Fall ’26 calendar. It never touches your primary calendar.</p><a className="primary-action" href="/api/auth/google/start">Connect Google <ArrowRight size={18}/></a></>}
      {screen === "setup" && <><p className="eyebrow">One-time setup</p><h2>Choose your real courses</h2><p>Your Canvas token stays in Secret Manager. Teaching roles and submitted work are automatically excluded from scheduling.</p><button onClick={discover} disabled={busy}>Discover Fall ’26 courses</button><div className="course-list">{courses.map(course => <label key={course.id}><input type="checkbox" checked={selected.includes(course.id)} onChange={event => setSelected(event.target.checked ? [...selected, course.id] : selected.filter(id => id !== course.id))}/><span><b>{course.code}</b><small>{course.title} · {course.role}</small></span></label>)}</div>{courses.length > 0 && <><div className="preferences"><label>Prioritize<select value={priorityMode} onChange={e => setPriorityMode(e.target.value)}><option value="grade">Grade impact</option><option value="urgency">Urgency</option><option value="effort">Large tasks</option><option value="avoidance">Balanced</option></select></label><label>Start ahead<input type="number" min="0" max="21" value={lead} onChange={e => setLead(Number(e.target.value))}/><small>days</small></label><label>Daily cap<input type="number" min="1" max="12" value={cap} onChange={e => setCap(Number(e.target.value))}/><small>hours</small></label></div><div className="source-fields"><label>Data 101 site<input type="url" value={dataUrl} onChange={e => setDataUrl(e.target.value)}/></label><label>Math 110 context<input type="url" value={mathUrl} onChange={e => setMathUrl(e.target.value)}/></label><label>Optional private syllabus<select value={syllabusCourse} onChange={e => setSyllabusCourse(e.target.value)}><option value="">Choose course</option>{courses.filter(course => selected.includes(course.id)).map(course => <option key={course.id} value={course.id}>{course.code}</option>)}</select><input type="file" accept=".pdf,.md,.html,.txt" onChange={e => setSyllabus(e.target.files?.[0] || null)}/></label></div><button onClick={saveAndSync} disabled={busy || !selected.length}>Start managing my semester <ArrowRight size={18}/></button></>}</>}
      {screen === "dashboard" && <><div className="dashboard-head"><div><p className="eyebrow">Today</p><h2>What to work on</h2></div><button className="compact" onClick={syncNow} disabled={busy}><RefreshCw size={16}/> Sync now</button></div><div className="metrics">{Object.entries(status?.last_run?.summary || {}).slice(0,4).map(([key,value]) => <span key={key}><b>{value}</b><small>{key.replaceAll("_", " ")}</small></span>)}{calibration && <span><b>{calibration.global_effort_multiplier.toFixed(2)}×</b><small>learned effort</small></span>}{learnedCourses > 0 && <span><b>{learnedCourses}</b><small>courses calibrated</small></span>}</div><div className="task-stack">{daily.active.length ? daily.active.map((task, index) => {
        const taskKey = String(task.task_key || index);
        const dueLabel = task.due_date ? new Date(String(task.due_date)).toLocaleDateString() : String(task.due || "");
        return <article key={taskKey} className="task-card"><div className="task-card-head"><span className={`tier tier-${String(task.tier).toLowerCase()}`}>{String(task.tier)}</span>{index === 0 && <CheckCircle2 size={20}/>}</div><div><b>{String(task.title)}</b><small>{String(task.course)} · estimated {String(task.estimated_hours || task.hours)}h · planned {String(task.hours)}h · due {dueLabel}</small></div>{task.task_key && <div className="feedback-row"><span className="feedback-label">We estimated {String(task.estimated_hours || task.hours)}h — how was it?</span><div className="feedback-actions"><button type="button" className="feedback-btn" disabled={busy} onClick={() => void submitFeedback(task, "too_low")}>Too low</button><button type="button" className="feedback-btn" disabled={busy} onClick={() => void submitFeedback(task, "about_right")}>About right</button><button type="button" className="feedback-btn" disabled={busy} onClick={() => void submitFeedback(task, "too_high")}>Too high</button></div><label className="feedback-hours">Actually took<input type="number" min="0.25" max="40" step="0.25" placeholder="hours" value={actualHours[taskKey] || ""} onChange={e => setActualHours(current => ({ ...current, [taskKey]: e.target.value }))}/></label></div>}</article>;
      }) : <p className="empty">No active work right now.</p>}</div><h3>Agent activity</h3><div className="activity">{activity.slice(0,5).map((run, index) => <p key={String(run.run_id || index)}><b>{String(run.trigger || "sync")}</b> · {String(run.state)} <small>{run.started_at ? new Date(String(run.started_at)).toLocaleString() : ""}</small></p>)}</div><p className="footnote">Next automatic sync: {status?.next_sync_at ? new Date(status.next_sync_at).toLocaleString() : "hourly"}</p></>}
      {message && <p className="notice">{message}</p>}
    </div></section>
  </main>;
}
