import { useEffect, useState } from "react";
import { ArrowRight, CalendarDays, CheckCircle2, RefreshCw } from "lucide-react";

type Course = { id: string; code: string; title: string; role: string };
type Status = {
  google_connected: boolean;
  canvas_connected: boolean;
  calendar_writes_enabled?: boolean;
  registry?: Record<string, unknown>;
  last_run?: { state: string; summary?: Record<string, number> };
  next_sync_at: string;
};
type DailyTask = Record<string, string | number | boolean>;
type Daily = { active: DailyTask[]; upcoming: DailyTask[] };
type Calibration = {
  global_effort_multiplier: number;
  global_samples: number;
  by_course: Record<string, { effort_multiplier: number; samples: number }>;
};
type RegistryRow = Record<string, unknown>;
type CoverageCourse = Record<string, unknown>;
type DashboardTab = "schedule" | "claims" | "coverage" | "events" | "today";

const defaults = {
  priority_mode: "grade",
  lead_time_days: 5,
  reminder_style: "ramping",
  work_day_start: 9,
  work_day_end: 21,
  off_days: [],
  priority_courses: [],
  excluded_courses: [],
  daily_cap_hours: 4,
  effort_padding: 1.2,
  calendar_writes_enabled: false,
};

function formatDue(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function statusClass(status: string) {
  if (status === "ready") return "status-ready";
  if (status === "conflicting") return "status-conflict";
  if (status === "review_required") return "status-review";
  return "status-muted";
}

export default function App() {
  const [screen, setScreen] = useState<"login" | "setup" | "dashboard">("login");
  const [courses, setCourses] = useState<Course[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [daily, setDaily] = useState<Daily>({ active: [], upcoming: [] });
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [activity, setActivity] = useState<Array<Record<string, unknown>>>([]);
  const [schedule, setSchedule] = useState<RegistryRow[]>([]);
  const [claims, setClaims] = useState<RegistryRow[]>([]);
  const [coverage, setCoverage] = useState<{ courses?: CoverageCourse[] }>({});
  const [timedEvents, setTimedEvents] = useState<RegistryRow[]>([]);
  const [tab, setTab] = useState<DashboardTab>("schedule");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [priorityMode, setPriorityMode] = useState("grade");
  const [lead, setLead] = useState(5);
  const [cap, setCap] = useState(4);
  const [dataUrl, setDataUrl] = useState("https://data101.org/fa26/");
  const [mathUrl, setMathUrl] = useState("https://ethanebb.github.io/Teaching%20Pages/Math110Fall26.html");
  const [syllabus, setSyllabus] = useState<File | null>(null);
  const [syllabusCourse, setSyllabusCourse] = useState("");
  const [actualHours, setActualHours] = useState<Record<string, string>>({});

  async function api(path: string, options?: RequestInit) {
    const response = await fetch(path, options);
    if (response.status === 401) {
      setScreen("login");
      throw new Error("Connect Google to continue");
    }
    if (!response.ok) {
      const text = await response.text();
      try {
        throw new Error(JSON.parse(text).detail || "Request failed");
      } catch (error) {
        if (error instanceof SyntaxError) throw new Error(text || `Request failed (${response.status})`);
        throw error;
      }
    }
    return response.json();
  }

  async function refresh() {
    try {
      const nextStatus = await api("/api/status");
      setStatus(nextStatus);
      if (nextStatus.canvas_connected) {
        const [view, runs, cal, scheduleRows, claimRows, coverageRows, timedRows] = await Promise.all([
          api("/api/daily"),
          api("/api/activity"),
          api("/api/calibration"),
          api("/api/schedule"),
          api("/api/claims"),
          api("/api/coverage"),
          api("/api/timed-events"),
        ]);
        setDaily(view);
        setActivity(runs);
        setCalibration(cal);
        setSchedule(scheduleRows);
        setClaims(claimRows);
        setCoverage(coverageRows);
        setTimedEvents(timedRows);
        setScreen("dashboard");
      } else setScreen("setup");
    } catch {
      /* login screen is set by api */
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function discover() {
    setBusy(true);
    try {
      const result = await api("/api/connectors/canvas", { method: "POST" });
      setCourses(result.courses);
      setMessage(`Canvas connected as ${result.identity_label}`);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function saveAndSync() {
    setBusy(true);
    setMessage("Building your semester registry…");
    try {
      await api("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...defaults,
          selected_course_ids: selected,
          priority_mode: priorityMode,
          lead_time_days: lead,
          daily_cap_hours: cap,
        }),
      });
      const dataCourse = courses.find((course) => course.code.includes("C187"));
      const mathCourse = courses.find((course) => course.code.includes("MATH 110"));
      if (dataCourse && dataUrl) {
        await api("/api/sources/url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ course_id: dataCourse.id, label: "Data 101 Fall 2026", url: dataUrl }),
        });
      }
      if (mathCourse && mathUrl) {
        await api("/api/sources/url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ course_id: mathCourse.id, label: "Math 110 Fall 2026", url: mathUrl }),
        });
      }
      if (syllabus && syllabusCourse) {
        const upload = new FormData();
        upload.append("course_id", syllabusCourse);
        upload.append("file", syllabus);
        await api("/api/sources/upload", { method: "POST", body: upload });
      }
      await api("/api/sync", { method: "POST" });
      await refresh();
      setMessage("Registry updated. Review the schedule queue before enabling calendar writes.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function syncNow() {
    setBusy(true);
    try {
      await api("/api/sync", { method: "POST" });
      await refresh();
      setMessage("Registry refreshed.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function enableCalendarWrites() {
    setBusy(true);
    setMessage("Scheduling work blocks, due markers, and exams…");
    try {
      await api("/api/config/calendar-writes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: true }),
      });
      await api("/api/sync", { method: "POST" });
      await refresh();
      setMessage("Calendar updated with [DUE] markers, exams/quizzes, and work blocks.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

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

  const registry = status?.registry || {};
  const metrics: Array<[string, number]> = [
    ["claims", Number(registry.claims ?? 0)],
    ["ready", Number(registry.canonical_ready ?? 0)],
    ["conflicts", Number(registry.conflicts ?? 0)],
    ["review", Number(registry.review_required ?? 0)],
    ["events", Number((registry.coverage as { timed_events_total?: number } | undefined)?.timed_events_total ?? timedEvents.length)],
  ];
  const learnedCourses = calibration ? Object.entries(calibration.by_course).filter(([, value]) => value.samples > 0).length : 0;

  return (
    <main className="shell">
      <aside className="signal-rail">
        <div className="wordmark">StudyAgent</div>
        <div className="rail-copy">
          <p className="eyebrow">Fall 2026 · Registry first</p>
          <h1>Truth before calendar.</h1>
          <p className="lede">Every due date is a proven claim. Merge, review conflicts, then let the agent schedule.</p>
        </div>
        <ol className="steps">
          <li className="active">
            <span className="step-node">●</span>
            <span className="step-number">01</span>
            <span>Connect sources</span>
          </li>
          <li className={screen === "dashboard" ? "active" : ""}>
            <span className="step-node">●</span>
            <span className="step-number">02</span>
            <span>Review registry</span>
          </li>
        </ol>
      </aside>
      <section className="workspace">
        <header className="workspace-header">
          <span className="status-chip">{busy ? "Working" : status?.last_run?.state || "Ready"}</span>
          <span className="utility">P1 · claims registry</span>
        </header>
        <div className={`setup-card ${screen === "dashboard" ? "dashboard-wide" : ""}`}>
          {screen === "login" && (
            <>
              <div className="icon-tile">
                <CalendarDays />
              </div>
              <p className="eyebrow">Owner setup</p>
              <h2>Connect your calendar</h2>
              <p>StudyAgent creates one separate Fall ’26 calendar when you enable writes. Until then, we only build the registry.</p>
              <a className="primary-action" href="/api/auth/google/start">
                Connect Google <ArrowRight size={18} />
              </a>
            </>
          )}
          {screen === "setup" && (
            <>
              <p className="eyebrow">One-time setup</p>
              <h2>Choose your real courses</h2>
              <p>Canvas token stays in Secret Manager. Teaching roles are excluded automatically.</p>
              <button onClick={discover} disabled={busy}>
                Discover Fall ’26 courses
              </button>
              <div className="course-list">
                {courses.map((course) => (
                  <label key={course.id}>
                    <input
                      type="checkbox"
                      checked={selected.includes(course.id)}
                      onChange={(event) =>
                        setSelected(event.target.checked ? [...selected, course.id] : selected.filter((id) => id !== course.id))
                      }
                    />
                    <span>
                      <b>{course.code}</b>
                      <small>
                        {course.title} · {course.role}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
              {courses.length > 0 && (
                <>
                  <div className="preferences">
                    <label>
                      Prioritize
                      <select value={priorityMode} onChange={(e) => setPriorityMode(e.target.value)}>
                        <option value="grade">Grade impact</option>
                        <option value="urgency">Urgency</option>
                        <option value="effort">Large tasks</option>
                        <option value="avoidance">Balanced</option>
                      </select>
                    </label>
                    <label>
                      Start ahead
                      <input type="number" min="0" max="21" value={lead} onChange={(e) => setLead(Number(e.target.value))} />
                      <small>days</small>
                    </label>
                    <label>
                      Daily cap
                      <input type="number" min="1" max="12" value={cap} onChange={(e) => setCap(Number(e.target.value))} />
                      <small>hours</small>
                    </label>
                  </div>
                  <button onClick={saveAndSync} disabled={busy || !selected.length}>
                    Build registry <ArrowRight size={18} />
                  </button>
                </>
              )}
            </>
          )}
          {screen === "dashboard" && (
            <>
              <div className="dashboard-head">
                <div>
                  <p className="eyebrow">Semester registry</p>
                  <h2>Review before scheduling</h2>
                </div>
                <div className="dashboard-actions">
                  <a className="export-link" href="/api/dues/export.csv">
                    Export CSV
                  </a>
                  <button className="compact" onClick={syncNow} disabled={busy}>
                    <RefreshCw size={16} /> Sync now
                  </button>
                </div>
              </div>
              {!status?.calendar_writes_enabled && (
                <div className="banner-off">
                  <span>Calendar writes are OFF. Review the registry, then schedule to Google Calendar.</span>
                  <button className="compact" type="button" onClick={enableCalendarWrites} disabled={busy}>
                    Write to calendar
                  </button>
                </div>
              )}
              <div className="metrics">
                {metrics.map(([key, value]) => (
                  <span key={key}>
                    <b>{value}</b>
                    <small>{key.replaceAll("_", " ")}</small>
                  </span>
                ))}
                {calibration && (
                  <span>
                    <b>{calibration.global_effort_multiplier.toFixed(2)}×</b>
                    <small>learned effort</small>
                  </span>
                )}
                {learnedCourses > 0 && (
                  <span>
                    <b>{learnedCourses}</b>
                    <small>courses calibrated</small>
                  </span>
                )}
              </div>
              <div className="tab-row">
                {(["schedule", "claims", "coverage", "events", "today"] as DashboardTab[]).map((name) => (
                  <button key={name} type="button" className={`tab-btn ${tab === name ? "active" : ""}`} onClick={() => setTab(name)}>
                    {name === "schedule"
                      ? "Schedule queue"
                      : name === "events"
                        ? "Timed events"
                        : name.charAt(0).toUpperCase() + name.slice(1)}
                  </button>
                ))}
              </div>
              {tab === "schedule" && (
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Course</th>
                        <th>Title</th>
                        <th>Due</th>
                        <th>Status</th>
                        <th>Sources</th>
                      </tr>
                    </thead>
                    <tbody>
                      {schedule.length ? (
                        schedule.map((row) => (
                          <tr key={String(row.id)}>
                            <td>{String(row.course_label || "")}</td>
                            <td>{String(row.title || "")}</td>
                            <td>{formatDue(row.due_at)}</td>
                            <td>
                              <span className={`status-pill ${statusClass(String(row.status || ""))}`}>{String(row.status || "")}</span>
                            </td>
                            <td>{(row.sources as string[] | undefined)?.join(", ") || "—"}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} className="empty">
                            No canonical items yet. Run Sync now.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
              {tab === "claims" && (
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Course</th>
                        <th>Title</th>
                        <th>Due</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {claims.length ? (
                        claims.map((row) => (
                          <tr key={String(row.id)}>
                            <td>{String(row.provenance || "")}</td>
                            <td>{String(row.course_label || "")}</td>
                            <td>{String(row.title || "")}</td>
                            <td>{formatDue(row.due_at)}</td>
                            <td>
                              <span className={`status-pill ${statusClass(String(row.status || ""))}`}>{String(row.status || row.skip_reason || "")}</span>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} className="empty">
                            No claims ingested yet.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
              {tab === "coverage" && (
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Course</th>
                        <th>Claims</th>
                        <th>Ready</th>
                        <th>Conflicts</th>
                        <th>Review</th>
                        <th>Needs review</th>
                        <th>Weights</th>
                        <th>Timed</th>
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(coverage.courses || []).length ? (
                        coverage.courses!.map((row) => (
                          <tr key={String(row.course_id || row.course_label)}>
                            <td>{String(row.course_label || row.course_id)}</td>
                            <td>{String(row.claims ?? 0)}</td>
                            <td>{String(row.canonical_ready ?? 0)}</td>
                            <td>{String(row.conflicts ?? 0)}</td>
                            <td>{String(row.review_required ?? 0)}</td>
                            <td>{String(row.needs_review_assignments ?? 0)}</td>
                            <td>{row.grade_weights_complete ? "100%" : "incomplete"}</td>
                            <td>{String(row.timed_events ?? 0)}</td>
                            <td>{((row.notes as string[] | undefined) || []).join("; ") || "—"}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={9} className="empty">
                            No coverage data yet.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
              {tab === "events" && (
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Course</th>
                        <th>Title</th>
                        <th>Kind</th>
                        <th>Start</th>
                        <th>End</th>
                        <th>Optional</th>
                      </tr>
                    </thead>
                    <tbody>
                      {timedEvents.length ? (
                        timedEvents.slice(0, 200).map((row) => (
                          <tr key={String(row.id)}>
                            <td>{String(row.course_label || "—")}</td>
                            <td>{String(row.title || "—")}</td>
                            <td>{String(row.kind || "—")}</td>
                            <td>{formatDue(row.start_at)}</td>
                            <td>{formatDue(row.end_at)}</td>
                            <td>{row.optional ? "yes" : "no"}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={6} className="empty">
                            No timed events loaded yet.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
              {tab === "today" && (
                <div className="task-stack">
                  {daily.active.length ? (
                    daily.active.map((task, index) => {
                      const taskKey = String(task.task_key || index);
                      const dueLabel = task.due_date ? new Date(String(task.due_date)).toLocaleDateString() : String(task.due || "");
                      return (
                        <article key={taskKey} className="task-card">
                          <div className="task-card-head">
                            <span className={`tier tier-${String(task.tier).toLowerCase()}`}>{String(task.tier)}</span>
                            {index === 0 && <CheckCircle2 size={20} />}
                          </div>
                          <div>
                            <b>{String(task.title)}</b>
                            <small>
                              {String(task.course)} · due {dueLabel}
                            </small>
                          </div>
                        </article>
                      );
                    })
                  ) : (
                    <p className="empty">Nothing active in the schedule queue for today.</p>
                  )}
                </div>
              )}
              <h3>Agent activity</h3>
              <div className="activity">
                {activity.slice(0, 5).map((run, index) => (
                  <p key={String(run.run_id || index)}>
                    <b>{String(run.trigger || "sync")}</b> · {String(run.state)}{" "}
                    <small>{run.started_at ? new Date(String(run.started_at)).toLocaleString() : ""}</small>
                  </p>
                ))}
              </div>
            </>
          )}
          {message && <p className="notice">{message}</p>}
        </div>
      </section>
    </main>
  );
}
