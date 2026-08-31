import { useEffect, useRef, useState } from "react";
import OnboardingWizard from "./OnboardingWizard";
import { courseColor, courseFromEventTitle } from "./scheduleColors";
import "./taskmaster.css";

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: Array<{ isFinal: boolean; 0: { transcript: string } }>;
};

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type WindowWithSpeech = Window & {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
};

type TaskRow = {
  title: string;
  course?: string;
  due?: string;
  due_date: string;
  days_left: number;
  start_date: string;
  hours: number;
  tier?: string;
  color_id?: string;
  from_syllabus?: boolean;
  priority_course?: boolean;
  work_type?: string;
  overdue_start?: boolean;
  opens_in_days?: number;
};

type DailyBoard = {
  generated_at?: string;
  date: string;
  daily_cap_hours: number;
  active: TaskRow[];
  upcoming: TaskRow[];
  materials?: Array<{ title: string; course?: string; label?: string; url?: string }>;
  study_plan?: {
    cap_hours: number;
    deadline_minutes: number;
    planned_minutes: number;
    free_minutes: number;
    picks: Array<{ title: string; label?: string; url?: string; est_minutes?: number }>;
    not_today?: number;
  };
  calendar?: {
    events: Array<{ title: string; start: string; end: string; description?: string; color_id?: string }>;
    deadlines: Array<{ title: string; course?: string; due_label: string }>;
    has_calendar_access?: boolean;
  };
  courses?: Array<{
    course: string;
    work_type?: string;
    total_assignments?: number;
    upcoming?: number;
    has_work?: boolean;
  }>;
  manual?: { files?: Array<{ file: string; course_hint?: string }>; course_urls?: Record<string, string> };
};

const TIERS = [
  { key: "HIGH", label: "High priority", color: "var(--high)" },
  { key: "MEDIUM", label: "Medium priority", color: "var(--med)" },
  { key: "LOW", label: "Low priority", color: "var(--low)" },
];

function shortCourse(name?: string) {
  return (name || "")
    .replace(/\s*\((Fall|Spring|Summer|Winter)\s+\d{4}\)\s*$/i, "")
    .replace(/\s*-\s*DATA\/History\/STS\s*$/i, "")
    .trim();
}

function longDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

function shortDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function dueText(days: number) {
  if (days < 0) return "overdue";
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  return `${days} days left`;
}

function Runway({ task, today, color }: { task: TaskRow; today: string; color: string }) {
  const start = new Date(`${task.start_date}T00:00:00`);
  const due = new Date(`${task.due_date}T00:00:00`);
  const now = new Date(`${today}T00:00:00`);
  const span = Math.max(due.getTime() - start.getTime(), 1);
  const pct = Math.min(Math.max(((now.getTime() - start.getTime()) / span) * 100, 0), 100);
  return (
    <div className="runway">
      <div className="track">
        <div className="elapsed" style={{ width: `${pct}%`, background: color, opacity: 0.55 }} />
        <div className="now" style={{ left: `${pct}%` }} />
      </div>
      <div className="runway-labels">
        <span>start {shortDate(task.start_date)}</span>
        <span>due {shortDate(task.due_date)}</span>
      </div>
    </div>
  );
}

function TaskCard({ task, today, color }: { task: TaskRow; today: string; color: string }) {
  const accent = courseColor(task.course, color);
  const cc = courseColor(task.course);
  return (
    <div className="task" style={{ borderLeft: `3px solid ${accent}` }}>
      <div className="task-top">
        <div className="title">{task.title}</div>
        <div className="hours">{task.hours}h</div>
      </div>
      <div className="meta">
        <span style={{ color: cc }}>{shortCourse(task.course)}</span>
        <span>·</span>
        <span>{dueText(task.days_left)}</span>
        {task.priority_course && <span className="tag tag-pri">priority course</span>}
        {task.work_type === "teaching" && <span className="tag tag-teach">teaching</span>}
        {task.from_syllabus && <span className="tag tag-syl">from syllabus</span>}
        {task.overdue_start && <span className="tag tag-late">start date passed</span>}
      </div>
      <Runway task={task} today={today} color={accent} />
    </div>
  );
}

function CalendarSection({ data }: { data?: DailyBoard["calendar"] }) {
  const [offset, setOffset] = useState(0);
  if (!data) return null;
  const events = data.events || [];
  const deadlines = data.deadlines || [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay() + offset * 7);
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    return d;
  });
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const parseDue = (label: string) => {
    const parsed = new Date(`${label} ${weekStart.getFullYear()}`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  };
  const rangeLabel = `${days[0].toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${days[6].toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
  const courseNames = Array.from(
    new Set(
      [
        ...events.map((e) => courseFromEventTitle(e.title)),
        ...deadlines.map((d) => d.course || ""),
      ].filter(Boolean),
    ),
  );
  const anythingThisWeek = days.some(
    (d) =>
      events.some((e) => sameDay(new Date(e.start), d)) ||
      deadlines.some((dl) => {
        const parsed = parseDue(dl.due_label);
        return parsed && sameDay(parsed, d);
      }),
  );

  return (
    <section className="cal">
      <div className="tier-head">
        <span className="dot" style={{ background: "var(--accent)" }} />
        <span className="tier-name" style={{ color: "var(--accent)" }}>
          Calendar
        </span>
        <span className="tier-count">{events.length} blocks</span>
      </div>
      <div className="cal-nav">
        <button type="button" className="cal-btn" onClick={() => setOffset(offset - 1)}>
          ← prev
        </button>
        <button type="button" className="cal-btn" onClick={() => setOffset(0)}>
          this week
        </button>
        <button type="button" className="cal-btn" onClick={() => setOffset(offset + 1)}>
          next →
        </button>
        <span className="cal-range">{rangeLabel}</span>
      </div>
      <div className="cal-grid">
        {!anythingThisWeek && offset === 0 && (
          <div className="cal-empty">
            {data.has_calendar_access
              ? "Nothing scheduled this week."
              : "No calendar blocks yet — enable calendar writes and sync."}
          </div>
        )}
        {(anythingThisWeek || offset !== 0) &&
          days.map((d, i) => {
            const isToday = sameDay(d, today);
            const isPast = d < today && !isToday;
            const dayEvents = events.filter((e) => sameDay(new Date(e.start), d));
            const dayDue = deadlines.filter((dl) => {
              const parsed = parseDue(dl.due_label);
              return parsed && sameDay(parsed, d);
            });
            return (
              <div className={`cal-day${isToday ? " today" : ""}${isPast ? " past" : ""}`} key={i}>
                <div className="cal-dow">{d.toLocaleDateString(undefined, { weekday: "short" })}</div>
                <div className="cal-date">{d.getDate()}</div>
                {dayDue.map((dl, j) => {
                  const dc = courseColor(dl.course);
                  return (
                    <div className="cal-due" key={`d${j}`} style={{ color: dc, borderColor: dc }} title={`${dl.title} due`}>
                      DUE {dl.title}
                    </div>
                  );
                })}
                {dayEvents.map((e, j) => {
                  const evCourse = courseFromEventTitle(e.title);
                  const start = new Date(e.start);
                  const label = start.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
                  const blockColor = courseColor(evCourse);
                  return (
                    <div
                      className="cal-block"
                      key={`e${j}`}
                      style={{ borderLeftColor: blockColor }}
                      title={e.title}
                    >
                      {label} {e.title.replace(/^Work:\s*/, "").replace(/\s*\([^)]*\)\s*$/, "")}
                    </div>
                  );
                })}
              </div>
            );
          })}
      </div>
      <div className="cal-legend">
        {courseNames.map((c) => (
          <span key={c}>
            <i style={{ background: courseColor(c) }} />
            {shortCourse(c)}
          </span>
        ))}
        <span>solid = work block · dashed = deadline</span>
      </div>
    </section>
  );
}

function VoiceDock({ api }: { api: (path: string, options?: RequestInit) => Promise<unknown> }) {
  const [state, setState] = useState<"idle" | "listening" | "thinking">("idle");
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("");
  const recogRef = useRef<SpeechRecognitionLike | null>(null);

  const win = window as WindowWithSpeech;
  const SR = win.SpeechRecognition || win.webkitSpeechRecognition;
  const supported = Boolean(SR);

  useEffect(() => {
    const warm = () => window.speechSynthesis.getVoices();
    warm();
    window.speechSynthesis.onvoiceschanged = warm;
    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, []);

  const pickVoice = () => {
    const voices = window.speechSynthesis.getVoices() || [];
    const prefs = [
      "Ava (Premium)",
      "Samantha (Enhanced)",
      "Ava",
      "Samantha",
      "Google US English",
      "Microsoft Aria Online (Natural) - English (United States)",
    ];
    for (const wanted of prefs) {
      const hit = voices.find((v) => v.name === wanted);
      if (hit) return hit;
    }
    const english = voices.filter((v) => v.lang?.startsWith("en"));
    return english.find((v) => !/compact/i.test(v.voiceURI || "")) || english[0] || null;
  };

  const speak = (text: string) => {
    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      const voice = pickVoice();
      if (voice) utterance.voice = voice;
      window.speechSynthesis.speak(utterance);
    } catch {
      /* text still visible */
    }
  };

  const send = async (question: string) => {
    setState("thinking");
    try {
      const result = (await api("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      })) as { answer?: string };
      const answer = result.answer || "";
      setReply(answer);
      setState("idle");
      speak(answer);
    } catch {
      setReply("I couldn't reach the agent.");
      setState("idle");
    }
  };

  const listen = () => {
    if (state === "listening") {
      recogRef.current?.stop();
      return;
    }
    if (!supported || !SR) return;
    window.speechSynthesis.cancel();
    const recognition = new SR();
    recogRef.current = recognition;
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    let finalText = "";
    recognition.onstart = () => {
      setState("listening");
      setHeard("");
      setReply("");
    };
    recognition.onresult = (event: SpeechRecognitionEventLike) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += text;
        else interim += text;
      }
      setHeard(finalText || interim);
    };
    recognition.onerror = () => {
      setState("idle");
      setReply("I didn't catch that.");
    };
    recognition.onend = () => {
      const question = finalText.trim();
      if (question) void send(question);
      else setState("idle");
    };
    recognition.start();
  };

  const label =
    state === "listening" ? "Listening — tap to stop" : state === "thinking" ? "Thinking" : "Tap and ask about your work";

  return (
    <div className="voice-dock">
      <div className="voice-inner">
        <button
          type="button"
          className={`mic ${state}`}
          onClick={listen}
          disabled={!supported || state === "thinking"}
          aria-label={state === "listening" ? "Stop listening" : "Ask a question"}
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="9" y="2" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0" />
            <path d="M12 18v4" />
          </svg>
        </button>
        <div className="voice-text">
          {!supported ? (
            <span className="voice-unsupported">Voice needs Chrome or Edge. Everything else works here.</span>
          ) : reply ? (
            <>
              {heard && <div className="voice-you">"{heard}"</div>}
              <div>{reply}</div>
            </>
          ) : heard ? (
            <div>{heard}</div>
          ) : (
            <span className="voice-hint">{label}</span>
          )}
        </div>
      </div>
    </div>
  );
}

type TodayBoardProps = {
  api: (path: string, options?: RequestInit) => Promise<unknown>;
  onSync: () => Promise<void>;
  busy: boolean;
  lastRun?: string;
};

export default function TodayBoard({ api, onSync, busy, lastRun }: TodayBoardProps) {
  const [data, setData] = useState<DailyBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [showPrefs, setShowPrefs] = useState(false);

  useEffect(() => {
    let stop = false;
    let prev = "";
    const load = async () => {
      try {
        const next = (await api("/api/daily")) as DailyBoard;
        if (stop) return;
        const stamp = JSON.stringify(next);
        if (stamp !== prev) {
          prev = stamp;
          setData(next);
        }
        setLastSync(new Date());
        setError(null);
      } catch (err) {
        if (!stop) setError(String(err));
      }
    };
    void load();
    const id = window.setInterval(() => void load(), 30000);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) void load();
    });
    return () => {
      stop = true;
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [api]);

  if (error && !data) {
    return (
      <div className="wrap">
        <div className="masthead">
          <p className="eyebrow">Taskmaster</p>
          <h1 className="today">No data yet</h1>
        </div>
        <div className="empty">
          <h3>Run the agent first</h3>
          <p>
            Sync your semester registry to populate today&apos;s board.
            <br />
            <button type="button" className="cal-btn" onClick={() => void onSync()} disabled={busy}>
              {busy ? "Syncing…" : "Sync now"}
            </button>
          </p>
        </div>
        <VoiceDock api={api} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="wrap">
        <div className="masthead">
          <p className="eyebrow">Taskmaster</p>
          <h1 className="today">Loading</h1>
        </div>
      </div>
    );
  }

  const active = data.active || [];
  const later = data.upcoming || [];
  const loadHours = active.reduce((sum, task) => sum + (task.hours || 0), 0);
  const cap = data.daily_cap_hours;

  if (showPrefs) {
    return (
      <OnboardingWizard
        api={api}
        editMode
        onComplete={() => setShowPrefs(false)}
        onCancel={() => setShowPrefs(false)}
      />
    );
  }

  return (
    <div className="wrap">
      <header className="masthead">
        <p className="eyebrow">Taskmaster · what&apos;s open right now</p>
        <h1 className="today">{longDate(data.date)}</h1>
        <p className="load">
          {active.length === 0 ? (
            "Nothing open yet"
          ) : (
            <>
              <b>{active.length}</b> {active.length === 1 ? "task" : "tasks"} open · <b>{Math.round(loadHours * 10) / 10}h</b> of work · cap{" "}
              <b>{cap}h</b>/day
              {loadHours > cap && <span className="over"> · spread across several days</span>}
            </>
          )}
        </p>
        <p className="load" style={{ marginTop: 8 }}>
          <button type="button" className="cal-btn" onClick={() => void onSync()} disabled={busy}>
            {busy ? "Syncing…" : "Sync now"}
          </button>
          <button type="button" className="cal-btn setup-prefs-btn" onClick={() => setShowPrefs(true)}>
            Preferences
          </button>
          {lastRun && <span style={{ marginLeft: 12 }}>last run {lastRun}</span>}
        </p>
      </header>

      <CalendarSection data={data.calendar} />

      {active.length === 0 && (
        <div className="empty">
          <h3>Nothing to start today</h3>
          <p>Everything on your plate is still far enough out, or you need to sync the registry first.</p>
        </div>
      )}

      {TIERS.map((tier) => {
        const rows = active.filter((task) => task.tier === tier.key);
        if (!rows.length) return null;
        return (
          <section className="tier" key={tier.key}>
            <div className="tier-head">
              <span className="dot" style={{ background: tier.color }} />
              <span className="tier-name" style={{ color: tier.color }}>
                {tier.label}
              </span>
              <span className="tier-count">{rows.length}</span>
            </div>
            {rows.map((task, i) => (
              <TaskCard key={`${task.title}${i}`} task={task} today={data.date} color={tier.color} />
            ))}
          </section>
        );
      })}

      {later.length > 0 && (
        <section className="later">
          <div className="tier-head">
            <span className="tier-name" style={{ color: "var(--muted)" }}>
              Opens later
            </span>
            <span className="tier-count">{later.length}</span>
          </div>
          {Object.entries(
            later.reduce<Record<string, TaskRow[]>>((acc, task) => {
              const key = task.course || "Other";
              acc[key] = acc[key] || [];
              acc[key].push(task);
              return acc;
            }, {}),
          ).map(([course, rows]) => {
            const color = courseColor(course);
            return (
              <div className="course-group" key={course}>
                <div className="course-head">
                  <span className="course-swatch" style={{ background: color }} />
                  <span className="course-name" style={{ color }}>
                    {shortCourse(course)}
                  </span>
                  <span className="course-count">{rows.length}</span>
                </div>
                {rows.map((task, i) => (
                  <div className="later-row" key={`${task.title}${i}`} style={{ borderLeft: `2px solid ${color}`, paddingLeft: 12 }}>
                    <div>{task.title}</div>
                    <div className="later-when">
                      {task.opens_in_days === 1 ? "starts tomorrow" : `starts in ${task.opens_in_days} days`}
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </section>
      )}

      {data.courses && data.courses.length > 0 && (
        <section className="roster">
          <div className="tier-head">
            <span className="tier-name" style={{ color: "var(--muted)" }}>
              Your courses
            </span>
            <span className="tier-count">{data.courses.length}</span>
          </div>
          {data.courses.map((course, i) => {
            const color = courseColor(course.course);
            return (
              <div className={`roster-row${course.has_work ? "" : " roster-quiet"}`} key={i}>
                <span className="course-swatch" style={{ background: color }} />
                <div>
                  <div>{shortCourse(course.course)}</div>
                </div>
                <span className="roster-state">
                  {course.upcoming && course.upcoming > 0
                    ? `${course.upcoming} upcoming`
                    : course.total_assignments && course.total_assignments > 0
                      ? "nothing upcoming"
                      : "nothing posted yet"}
                </span>
              </div>
            );
          })}
        </section>
      )}

      <footer className="foot">
        <span className="pulse" />
        Live · checked {lastSync ? lastSync.toLocaleTimeString() : "—"}
        {data.generated_at && <> · board built {new Date(data.generated_at).toLocaleString()}</>}
      </footer>

      <VoiceDock api={api} />
    </div>
  );
}
