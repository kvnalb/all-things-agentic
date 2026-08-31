import { useEffect, useState } from "react";
import { api } from "./lib";
import { Dashboard } from "./screens/Dashboard";
import { LoginScreen } from "./screens/LoginScreen";
import { SetupScreen } from "./screens/SetupScreen";
import { configDefaults, type Calibration, type Course, type CoverageCourse, type Daily, type DailyTask, type DashboardTab, type RegistryRow, type Screen, type Status } from "./types";

type Theme = "light" | "dark";

function readTheme(): Theme {
  const stored = localStorage.getItem("studyagent-theme");
  if (stored === "light" || stored === "dark") return stored;
  return "light";
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("boot");
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [courses, setCourses] = useState<Course[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [daily, setDaily] = useState<Daily>({ active: [], upcoming: [] });
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [schedule, setSchedule] = useState<RegistryRow[]>([]);
  const [coverage, setCoverage] = useState<{ courses?: CoverageCourse[] }>({});
  const [timedEvents, setTimedEvents] = useState<RegistryRow[]>([]);
  const [tab, setTab] = useState<DashboardTab>("today");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const [priorityMode, setPriorityMode] = useState("grade");
  const [lead, setLead] = useState(5);
  const [cap, setCap] = useState(4);
  const [dataUrl, setDataUrl] = useState("https://data101.org/fa26/");
  const [mathUrl, setMathUrl] = useState("https://ethanebb.github.io/Teaching%20Pages/Math110Fall26.html");
  const [syllabus, setSyllabus] = useState<File | null>(null);
  const [syllabusCourse, setSyllabusCourse] = useState("");
  const [actualHours, setActualHours] = useState<Record<string, string>>({});

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("studyagent-theme", theme);
  }, [theme]);

  function note(text: string, isError = false) {
    setMessage(text);
    setError(isError);
  }

  async function request(path: string, options?: RequestInit) {
    try {
      return await api(path, options);
    } catch (caught) {
      const failed = caught as Error & { status?: number };
      if (failed.status === 401) setScreen("login");
      throw failed;
    }
  }

  async function refresh(): Promise<Status | null> {
    try {
      const nextStatus = (await request("/api/status")) as Status;
      setStatus(nextStatus);
      if (!nextStatus.canvas_connected) {
        setScreen("setup");
        return nextStatus;
      }
      setScreen("dashboard");
      const [view, cal, scheduleRows, coverageRows, timedRows] = await Promise.all([
        request("/api/daily"),
        request("/api/calibration"),
        request("/api/schedule"),
        request("/api/coverage"),
        request("/api/timed-events"),
      ]);
      setDaily(view as Daily);
      setCalibration(cal as Calibration);
      setSchedule(scheduleRows as RegistryRow[]);
      setCoverage(coverageRows as { courses?: CoverageCourse[] });
      setTimedEvents(timedRows as RegistryRow[]);
      return nextStatus;
    } catch {
      setScreen((current) => (current === "boot" ? "login" : current));
      return null;
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function discover() {
    setBusy(true);
    try {
      const result = (await request("/api/connectors/canvas", { method: "POST" })) as { courses: Course[]; identity_label: string };
      setCourses(result.courses);
      note(`Canvas connected as ${result.identity_label}`);
    } catch (caught) {
      note(String(caught), true);
    } finally {
      setBusy(false);
    }
  }

  async function saveAndSync() {
    setBusy(true);
    note("Building your semester plan…");
    try {
      await request("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...configDefaults,
          selected_course_ids: selected,
          priority_mode: priorityMode,
          lead_time_days: lead,
          daily_cap_hours: cap,
        }),
      });
      const dataCourse = courses.find((course) => course.code.includes("C187"));
      const mathCourse = courses.find((course) => course.code.includes("MATH 110"));
      if (dataCourse && dataUrl) {
        await request("/api/sources/url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ course_id: dataCourse.id, label: "Data 101 Fall 2026", url: dataUrl }),
        });
      }
      if (mathCourse && mathUrl) {
        await request("/api/sources/url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ course_id: mathCourse.id, label: "Math 110 Fall 2026", url: mathUrl }),
        });
      }
      if (syllabus && syllabusCourse) {
        const upload = new FormData();
        upload.append("course_id", syllabusCourse);
        upload.append("file", syllabus);
        await request("/api/sources/upload", { method: "POST", body: upload });
      }
      await request("/api/sync", { method: "POST" });
      await refresh();
      note("Plan updated. Add it to Google Calendar when it looks right.");
    } catch (caught) {
      note(String(caught), true);
    } finally {
      setBusy(false);
    }
  }

  async function syncNow() {
    setBusy(true);
    try {
      await request("/api/sync", { method: "POST" });
      await refresh();
      note("Plan refreshed.");
    } catch (caught) {
      note(String(caught), true);
    } finally {
      setBusy(false);
    }
  }

  async function enableCalendarWrites() {
    setBusy(true);
    note("Adding due dates and study blocks to Google Calendar…");
    try {
      await request("/api/config/calendar-writes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: true }),
      });
      await request("/api/sync", { method: "POST" });
      const next = await refresh();
      const url = next?.calendar_url || "https://calendar.google.com/calendar/r";
      window.open(url, "_blank", "noopener,noreferrer");
      note("Opened StudyAgent — Fall 2026 in Google Calendar.");
    } catch (caught) {
      note(String(caught), true);
    } finally {
      setBusy(false);
    }
  }

  async function deleteCalendarEvent(id: string) {
    setBusy(true);
    try {
      await request(`/api/calendar/events/${encodeURIComponent(id)}`, { method: "DELETE" });
      await refresh();
      note("Event removed from Google Calendar.");
    } catch (caught) {
      note(String(caught), true);
    } finally {
      setBusy(false);
    }
  }

  async function saveCalendarEvent(payload: { id?: string; title: string; start: string; end: string }) {
    setBusy(true);
    try {
      if (payload.id) {
        await request(`/api/calendar/events/${encodeURIComponent(payload.id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ summary: payload.title, start: payload.start, end: payload.end }),
        });
      } else {
        await request("/api/calendar/events", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ summary: payload.title, start: payload.start, end: payload.end }),
        });
      }
      await refresh();
      note("Saved to Google Calendar.");
    } catch (caught) {
      note(String(caught), true);
    } finally {
      setBusy(false);
    }
  }

  async function submitFeedback(task: DailyTask, rating: "too_low" | "about_right" | "too_high") {
    const taskKey = String(task.task_key || "");
    if (!taskKey) return;
    const estimated = Number(task.estimated_hours || task.hours || 2);
    const parsedActual = actualHours[taskKey]?.trim() ? Number(actualHours[taskKey]) : undefined;
    setBusy(true);
    try {
      const result = (await request("/api/feedback", {
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
      })) as { calibration: Calibration };
      setCalibration(result.calibration);
      note("Got it — future estimates for this class will adjust.");
    } catch (caught) {
      note(String(caught), true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <a className="skip-link" href="#workspace">
        Skip to content
      </a>
      <div className="shell">
        <section className="workspace" id="workspace">
          <header className="chrome">
            <div className="brand">
              <strong>StudyAgent</strong>
              <span>Fall 2026</span>
            </div>
            {screen !== "dashboard" && (
              <button className="icon-btn" type="button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle color theme">
                {theme === "dark" ? "Light" : "Dark"}
              </button>
            )}
          </header>
          {screen === "boot" && (
            <div className="landing">
              <div className="landing-inner">
                <p className="eyebrow">Your Fall 2026 plan</p>
                <h1>Opening your plan…</h1>
              </div>
            </div>
          )}
          {screen === "login" && <LoginScreen />}
          {screen === "setup" && (
            <SetupScreen
              busy={busy}
              courses={courses}
              selected={selected}
              priorityMode={priorityMode}
              lead={lead}
              cap={cap}
              dataUrl={dataUrl}
              mathUrl={mathUrl}
              syllabusCourse={syllabusCourse}
              syllabusName={syllabus?.name || ""}
              onDiscover={discover}
              onToggleCourse={(id, checked) => setSelected((current) => (checked ? [...current, id] : current.filter((item) => id !== item)))}
              onPriority={setPriorityMode}
              onLead={setLead}
              onCap={setCap}
              onDataUrl={setDataUrl}
              onMathUrl={setMathUrl}
              onSyllabusCourse={setSyllabusCourse}
              onSyllabus={setSyllabus}
              onSave={saveAndSync}
            />
          )}
          {screen === "dashboard" && (
            <Dashboard
              busy={busy}
              tab={tab}
              theme={theme}
              status={status}
              daily={daily}
              coverage={coverage}
              schedule={schedule}
              timedEvents={timedEvents}
              query={query}
              actualHours={actualHours}
              onTab={setTab}
              onQuery={setQuery}
              onTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
              onSync={syncNow}
              onEnableWrites={enableCalendarWrites}
              onActualHours={(taskKey, value) => setActualHours((current) => ({ ...current, [taskKey]: value }))}
              onFeedback={submitFeedback}
              onSaveEvent={saveCalendarEvent}
              onDeleteEvent={deleteCalendarEvent}
            />
          )}
          {message && (
            <p className="toast" data-kind={error ? "error" : "info"} role="status">
              {message}
            </p>
          )}
        </section>
      </div>
    </>
  );
}
