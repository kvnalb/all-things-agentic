import { useMemo, useState } from "react";
import { CalendarDays, Moon, RefreshCw, Settings, Sun } from "lucide-react";
import { courseCode, dayLabel, dayStamp, dueClock, dueIn, formatDue, groupByDay, humanSync, planStats } from "../lib";
import { courseColor } from "../scheduleColors";
import type { CoverageCourse, Daily, DailyTask, DashboardTab, RegistryRow, Status } from "../types";
import { VoiceDock } from "../VoiceDock";
import { PlanCalendar } from "./PlanCalendar";

type Theme = "light" | "dark";

type Props = {
  busy: boolean;
  tab: DashboardTab;
  theme: Theme;
  status: Status | null;
  daily: Daily;
  coverage: { courses?: CoverageCourse[] };
  schedule: RegistryRow[];
  timedEvents: RegistryRow[];
  query: string;
  actualHours: Record<string, string>;
  onTab: (tab: DashboardTab) => void;
  onQuery: (value: string) => void;
  onTheme: () => void;
  onSync: () => void;
  onEnableWrites: () => void;
  onPrefs: () => void;
  onAsk: (path: string, options?: RequestInit) => Promise<unknown>;
  onActualHours: (taskKey: string, value: string) => void;
  onFeedback: (task: DailyTask, rating: "too_low" | "about_right" | "too_high") => void;
  onSaveEvent: (payload: { id?: string; title: string; start: string; end: string }) => void;
  onDeleteEvent: (id: string) => void;
};

const TABS: Array<{ id: DashboardTab; label: string }> = [
  { id: "today", label: "Today" },
  { id: "calendar", label: "Calendar" },
  { id: "schedule", label: "Upcoming" },
  { id: "coverage", label: "Classes" },
  { id: "events", label: "Events" },
];

function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty" role="status">
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

function Effort({
  task,
  hours,
  busy,
  onHours,
  onFeedback,
}: {
  task: DailyTask;
  hours: string;
  busy: boolean;
  onHours: (value: string) => void;
  onFeedback: (rating: "too_low" | "about_right" | "too_high") => void;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const current = Number(hours || task.estimated_hours || task.hours || 2);
  const shown = hours || String(task.estimated_hours || task.hours || 2);
  return (
    <div className="effort">
      <p className="effort-label">Was the time estimate right?</p>
      <div className="segment" role="group" aria-label="Estimate feedback">
        {(
          [
            ["too_low", "Easier"],
            ["about_right", "Right"],
            ["too_high", "Harder"],
          ] as const
        ).map(([rating, label]) => (
          <button
            key={rating}
            type="button"
            className={picked === rating ? "on" : ""}
            aria-pressed={picked === rating}
            disabled={busy}
            onClick={() => {
              setPicked(rating);
              onFeedback(rating);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="hours-block">
        <p className="effort-label">Hours it actually took</p>
        <span className="stepper">
          <button type="button" aria-label="Decrease hours" onClick={() => onHours(String(Math.max(0.25, current - 0.5)))}>
            −
          </button>
          <input inputMode="decimal" value={shown} onChange={(e) => onHours(e.target.value)} />
          <button type="button" aria-label="Increase hours" onClick={() => onHours(String(current + 0.5))}>
            +
          </button>
        </span>
        <p className="effort-hint">Tap Easier, Right, or Harder to save this.</p>
      </div>
    </div>
  );
}

export function Dashboard({
  busy,
  tab,
  theme,
  status,
  daily,
  coverage,
  schedule,
  timedEvents,
  query,
  actualHours,
  onTab,
  onQuery,
  onTheme,
  onSync,
  onEnableWrites,
  onPrefs,
  onAsk,
  onActualHours,
  onFeedback,
  onSaveEvent,
  onDeleteEvent,
}: Props) {
  const [focusDay, setFocusDay] = useState<string | null>(null);
  const needle = query.trim().toLowerCase();
  const upcoming = needle
    ? schedule.filter((row) => `${row.course_label} ${row.title}`.toLowerCase().includes(needle))
    : schedule;
  const lead = daily.active[0];
  const rest = daily.active.slice(1);
  const sync = humanSync(status?.last_run);
  const calendarUrl = status?.calendar_url || "https://calendar.google.com/calendar/r";
  const writesOn = Boolean(status?.calendar_writes_enabled);
  const googleEvents = daily.calendar?.events || [];
  function jump(next: DashboardTab, day?: string) {
    if (day) setFocusDay(day);
    onTab(next);
  }
  const stats = useMemo(() => planStats(schedule, daily, timedEvents), [schedule, daily, timedEvents]);
  const maxLoad = Math.max(...stats.byCourse.map((row) => row.count), 1);
  const hoursLabel = stats.hoursOpen ? (Number.isInteger(stats.hoursOpen) ? String(stats.hoursOpen) : stats.hoursOpen.toFixed(1)) : "0";
  const daysNeeded = stats.hoursOpen && stats.cap ? Math.max(1, Math.ceil(stats.hoursOpen / stats.cap)) : 0;
  const pace =
    stats.hoursOpen && stats.cap
      ? `About ${hoursLabel} hours open. At ${stats.cap} hours a day, that’s roughly ${daysNeeded} day${daysNeeded === 1 ? "" : "s"}.`
      : stats.hoursOpen
        ? `About ${hoursLabel} hours of open work.`
        : stats.nextSeven
          ? `${stats.nextSeven} due in the next week.`
          : "Nothing pressing this week.";

  return (
    <div className="dash">
      <div className="dash-head">
        <div>
          <p className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
          <p className="lede tight">
            {daily.active.length ? `${daily.active.length} up next` : "You’re clear for now"} · {schedule.length} on the calendar
          </p>
        </div>
        <div className="actions">
          <button className="icon-btn" type="button" onClick={onTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button className="btn btn-ghost btn-sm" type="button" onClick={onPrefs} disabled={busy}>
            <Settings size={16} /> Preferences
          </button>
          <button className="btn btn-ghost btn-sm" type="button" onClick={onSync} disabled={busy}>
            <RefreshCw size={16} /> Refresh
          </button>
          {writesOn ? (
            <a className="btn btn-primary btn-sm" href={calendarUrl} target="_blank" rel="noreferrer">
              <CalendarDays size={16} /> Open Calendar
            </a>
          ) : (
            <button className="btn btn-primary btn-sm" type="button" onClick={onEnableWrites} disabled={busy}>
              <CalendarDays size={16} /> Add to Google Calendar
            </button>
          )}
        </div>
      </div>

      <div className={`sync-chip ${sync.ok ? "" : "bad"} ${busy ? "busy" : ""}`}>
        <span>{busy ? "Updating your plan…" : sync.text}</span>
        {!sync.ok && (
          <button type="button" onClick={onSync} disabled={busy}>
            Retry
          </button>
        )}
      </div>

      {!writesOn && (
        <div className="banner">
          Due dates and study blocks are not on Google Calendar yet. Add them when the list looks right.
        </div>
      )}

      <div className="stats-grid">
        <button type="button" className="stat-card" onClick={() => jump("calendar", dayStamp(new Date()) || undefined)}>
          <b>{stats.dueToday}</b>
          <small>Due today</small>
        </button>
        <button type="button" className="stat-card" onClick={() => jump("schedule")}>
          <b>{stats.nextSeven}</b>
          <small>Next 7 days</small>
        </button>
        <button type="button" className={`stat-card ${stats.overdue ? "alert" : ""}`} onClick={() => jump("schedule")}>
          <b>{stats.overdue}</b>
          <small>Overdue</small>
        </button>
        <button type="button" className="stat-card" onClick={() => jump("today")}>
          <b>{hoursLabel}</b>
          <small>Hours open</small>
        </button>
      </div>
      <p className="stats-note">{pace}</p>
      {stats.nextExam && (
        <p className="stats-note exam">
          Next exam: {stats.nextExam.title} · {stats.nextExam.course} ·{" "}
          {stats.nextExam.at.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
        </p>
      )}
      {stats.byCourse.length > 0 && (
        <div className="load-list">
          {stats.byCourse.map((row) => (
            <div key={row.label} className="load-row">
              <span>{courseCode(row.label)}</span>
              <span className="load-track" aria-hidden="true">
                <span className="load-bar" style={{ width: `${Math.max(12, (row.count / maxLoad) * 100)}%`, background: courseColor(row.label) }} />
              </span>
              <em>{row.count} this week</em>
            </div>
          ))}
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Plan views">
        {TABS.map((item) => (
          <button key={item.id} type="button" role="tab" className="tab" aria-selected={tab === item.id} onClick={() => onTab(item.id)}>
            {item.label}
          </button>
        ))}
      </div>

      {tab === "schedule" && (
        <input className="filter" type="search" value={query} onChange={(e) => onQuery(e.target.value)} placeholder="Search a class or assignment" aria-label="Search upcoming work" />
      )}

      {tab === "calendar" && (
        <PlanCalendar
          schedule={schedule}
          timedEvents={timedEvents}
          googleEvents={googleEvents}
          writesOn={writesOn}
          busy={busy}
          focusDay={focusDay}
          onSave={onSaveEvent}
          onDelete={onDeleteEvent}
        />
      )}

      {tab === "today" &&
        (lead ? (
          <div className="today">
            <article className="hero">
              <div className="meta-row">
                <span className="course-chip" style={{ borderColor: courseColor(String(lead.course)), background: courseColor(String(lead.course)) }}>
                  {courseCode(lead.course)}
                </span>
                <span>{dueIn(lead.due_date || lead.due)}</span>
              </div>
              <h3>{String(lead.title)}</h3>
              <p className="meta-line">
                <span>{String(lead.course)}</span>
                <span>{formatDue(lead.due_date || lead.due)}</span>
                {lead.estimated_hours ? <span>About {lead.estimated_hours} hours</span> : null}
              </p>
              <Effort
                key={String(lead.task_key || lead.title)}
                task={lead}
                hours={actualHours[String(lead.task_key || "")] || ""}
                busy={busy}
                onHours={(value) => onActualHours(String(lead.task_key || ""), value)}
                onFeedback={(rating) => onFeedback(lead, rating)}
              />
            </article>
            {rest.length > 0 && (
              <div className="day-list">
                {rest.map((task, index) => (
                  <article key={String(task.task_key || index)} className="item">
                    <span className="rail" style={{ background: courseColor(String(task.course)) }} />
                    <div>
                      <b>{String(task.title)}</b>
                      <small>{String(task.course)}</small>
                    </div>
                    <div className="when">
                      <strong>{dueClock(task.due_date || task.due) || dayLabel(task.due_date || task.due)}</strong>
                      <span>{dueIn(task.due_date || task.due)}</span>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        ) : (
          <Empty title="You’re clear for today" detail="Upcoming work will show here after the next refresh." />
        ))}

      {tab === "schedule" &&
        (upcoming.length ? (
          <div className="groups">
            {groupByDay(upcoming).map((group) => (
              <section key={group.label}>
                <h4 className="group-head">
                  <span>{group.label}</span>
                  <span className="count-pill">{group.items.length}</span>
                </h4>
                <div className="day-list">
                  {group.items.map((row) => (
                    <article key={String(row.id)} className="item">
                      <span className="rail" style={{ background: courseColor(String(row.course_label || "")) }} />
                      <div>
                        <b>{String(row.title || "")}</b>
                        <small>{String(row.course_label || "")}</small>
                      </div>
                      <div className="when">
                        <strong>{dueClock(row.due_at) || "—"}</strong>
                        <span>{dueIn(row.due_at)}</span>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <Empty title="No upcoming work" detail="Refresh after choosing courses." />
        ))}

      {tab === "coverage" &&
        ((coverage.courses || []).length ? (
          <div className="cover-grid">
            {(coverage.courses || []).map((row) => (
              <article key={String(row.course_id || row.course_label)} className="cover-card">
                <span className="course-chip" style={{ borderColor: courseColor(String(row.course_label || row.course_id)), background: courseColor(String(row.course_label || row.course_id)) }}>
                  {courseCode(row.course_label || row.course_id)}
                </span>
                <b>{String(row.course_label || row.course_id)}</b>
                <p>
                  {String(row.canonical_ready ?? 0)} due · {String(row.timed_events ?? 0)} class times
                </p>
              </article>
            ))}
          </div>
        ) : (
          <Empty title="No classes yet" detail="Discover Canvas courses in setup." />
        ))}

      {tab === "events" &&
        (timedEvents.length ? (
          <div className="groups">
            {groupByDay(timedEvents.slice(0, 80), "start_at").map((group) => (
              <section key={group.label}>
                <h4 className="group-head">
                  <span>{group.label}</span>
                  <span className="count-pill">{group.items.length}</span>
                </h4>
                <div className="day-list">
                  {group.items.map((row) => (
                    <article key={String(row.id)} className="item">
                      <span className="rail" style={{ background: courseColor(String(row.course_label || "")) }} />
                      <div>
                        <b>{String(row.title || "—")}</b>
                        <small>{String(row.course_label || "Class")}</small>
                      </div>
                      <div className="when">
                        <strong>{dueClock(row.start_at)}</strong>
                        <span>{prettyEvent(row.kind)}</span>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <Empty title="No class times yet" detail="Lectures and exams appear here after a refresh." />
        ))}
      <VoiceDock api={onAsk} />
    </div>
  );
}

function prettyEvent(kind: unknown): string {
  const value = String(kind || "event").replaceAll("_", " ");
  return value.charAt(0).toUpperCase() + value.slice(1);
}
