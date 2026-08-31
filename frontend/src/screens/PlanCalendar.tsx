import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { courseCode, dayStamp, dueClock, parseWhen, startOfDay, toLocalInput } from "../lib";
import { courseColor, courseFromEventTitle } from "../scheduleColors";
import type { CalEvent, RegistryRow } from "../types";

type CalKind = "due" | "exam" | "class" | "work";

type CalItem = {
  id: string;
  googleId: string;
  title: string;
  course: string;
  at: Date;
  end?: Date;
  kind: CalKind;
  editable: boolean;
};

type Draft = { googleId: string; title: string; start: string; end: string };

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function classifyEvent(kind: unknown, title = ""): CalKind {
  const value = String(kind || "").toLowerCase();
  const text = title.toLowerCase();
  if (title.startsWith("[DUE]") || value === "due") return "due";
  if (text.startsWith("work:")) return "work";
  if (value === "exam" || value === "quiz" || text.startsWith("exam") || text.startsWith("quiz")) return "exam";
  return "class";
}

function monthDays(year: number, month: number): Array<Date | null> {
  const first = new Date(year, month, 1);
  const days = first.getDay();
  const last = new Date(year, month + 1, 0).getDate();
  const cells: Array<Date | null> = Array.from({ length: days }, () => null);
  for (let day = 1; day <= last; day += 1) cells.push(new Date(year, month, day));
  while (cells.length % 7) cells.push(null);
  return cells;
}

function defaultRange(day: string): { start: string; end: string } {
  const date = parseWhen(day) || startOfDay();
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 10, 0);
  const end = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 11, 0);
  return { start: toLocalInput(start), end: toLocalInput(end) };
}

export function PlanCalendar({
  schedule,
  timedEvents,
  googleEvents,
  writesOn,
  busy,
  focusDay,
  onSave,
  onDelete,
}: {
  schedule: RegistryRow[];
  timedEvents: RegistryRow[];
  googleEvents: CalEvent[];
  writesOn: boolean;
  busy: boolean;
  focusDay?: string | null;
  onSave: (payload: { id?: string; title: string; start: string; end: string }) => void;
  onDelete: (id: string) => void;
}) {
  const today = startOfDay();
  const [cursor, setCursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [selected, setSelected] = useState(() => dayStamp(today) || "");
  const [draft, setDraft] = useState<Draft | null>(null);

  const items = useMemo(() => {
    const rows: CalItem[] = [];
    if (googleEvents.length) {
      googleEvents.forEach((event, index) => {
        const at = parseWhen(event.start);
        if (!at) return;
        rows.push({
          id: String(event.id || `gcal-${index}`),
          googleId: String(event.id || ""),
          title: String(event.title || "Event"),
          course: courseFromEventTitle(String(event.title || "")),
          at,
          end: parseWhen(event.end) || undefined,
          kind: classifyEvent("", event.title),
          editable: Boolean(event.id && event.editable !== false),
        });
      });
      return rows.sort((a, b) => a.at.getTime() - b.at.getTime());
    }
    schedule.forEach((row, index) => {
      const at = parseWhen(row.due_at);
      if (!at) return;
      rows.push({
        id: String(row.id || `due-${index}`),
        googleId: "",
        title: String(row.title || "Assignment"),
        course: String(row.course_label || ""),
        at,
        kind: "due",
        editable: false,
      });
    });
    timedEvents.forEach((row, index) => {
      const at = parseWhen(row.start_at);
      if (!at) return;
      rows.push({
        id: String(row.id || `event-${index}`),
        googleId: "",
        title: String(row.title || "Class"),
        course: String(row.course_label || ""),
        at,
        end: parseWhen(row.end_at) || undefined,
        kind: classifyEvent(row.kind),
        editable: false,
      });
    });
    return rows.sort((a, b) => a.at.getTime() - b.at.getTime());
  }, [googleEvents, schedule, timedEvents]);

  const byDay = useMemo(() => {
    const map = new Map<string, CalItem[]>();
    for (const item of items) {
      const key = dayStamp(item.at);
      if (!key) continue;
      const list = map.get(key) || [];
      list.push(item);
      map.set(key, list);
    }
    return map;
  }, [items]);

  useEffect(() => {
    if (focusDay) {
      const date = parseWhen(focusDay);
      if (date) {
        setCursor(new Date(date.getFullYear(), date.getMonth(), 1));
        setSelected(focusDay);
      }
    }
  }, [focusDay]);

  useEffect(() => {
    const prefix = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}`;
    if (selected.startsWith(prefix)) return;
    const firstBusy = [...byDay.keys()].find((key) => key.startsWith(prefix));
    setSelected(firstBusy || `${prefix}-01`);
    setDraft(null);
  }, [cursor, byDay, selected]);

  const selectedItems = byDay.get(selected) || [];
  const cells = monthDays(cursor.getFullYear(), cursor.getMonth());
  const monthLabel = cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const selectedDate = parseWhen(selected);
  const canEdit = writesOn;
  const courseNames = [...new Set(items.map((item) => item.course).filter(Boolean))];

  function openDraft(item?: CalItem) {
    if (item?.googleId) {
      setDraft({
        googleId: item.googleId,
        title: item.title,
        start: toLocalInput(item.at),
        end: toLocalInput(item.end || new Date(item.at.getTime() + 36e5)),
      });
      return;
    }
    const range = defaultRange(selected);
    setDraft({ googleId: "", title: "", ...range });
  }

  return (
    <div className="cal-wrap">
      <div className="cal-nav">
        <button className="icon-btn" type="button" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))} aria-label="Previous month">
          <ChevronLeft size={18} />
        </button>
        <h3>{monthLabel}</h3>
        <button className="icon-btn" type="button" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))} aria-label="Next month">
          <ChevronRight size={18} />
        </button>
      </div>
      <div className="cal-legend">
        {courseNames.length ? (
          courseNames.map((name) => (
            <span key={name}>
              <i className="cal-dot" style={{ background: courseColor(name) }} /> {name}
            </span>
          ))
        ) : (
          <>
            <span>
              <i className="cal-dot due" /> Due
            </span>
            <span>
              <i className="cal-dot work" /> Study
            </span>
            <span>
              <i className="cal-dot class" /> Class
            </span>
            <span>
              <i className="cal-dot exam" /> Exam
            </span>
          </>
        )}
      </div>
      <div className="cal-grid" role="grid" aria-label={monthLabel}>
        {WEEKDAYS.map((day) => (
          <div key={day} className="cal-dow">
            {day}
          </div>
        ))}
        {cells.map((date, index) => {
          if (!date) return <div key={`empty-${index}`} className="cal-cell empty" />;
          const key = dayStamp(date) || "";
          const dayItems = byDay.get(key) || [];
          const extra = Math.max(0, dayItems.length - 3);
          return (
            <div key={key} className={`cal-cell ${dayStamp(today) === key ? "today" : ""} ${selected === key ? "on" : ""}`}>
              <button type="button" className="cal-date" onClick={() => { setSelected(key); setDraft(null); }}>
                {date.getDate()}
              </button>
              {dayItems.slice(0, 3).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`cal-chip ${item.kind}`}
                  style={{ borderLeft: `3px solid ${courseColor(item.course || courseFromEventTitle(item.title))}` }}
                  onClick={() => {
                    setSelected(key);
                    if (item.editable) openDraft(item);
                  }}
                >
                  {dueClock(item.at) ? `${dueClock(item.at)} ` : ""}
                  {item.title.replace(/^\[DUE\]\s*/, "")}
                </button>
              ))}
              {extra > 0 && (
                <button type="button" className="cal-more" onClick={() => { setSelected(key); setDraft(null); }}>
                  +{extra} more
                </button>
              )}
            </div>
          );
        })}
      </div>
      <section className="cal-agenda">
        <header>
          <div>
            <p className="eyebrow">{selectedDate ? selectedDate.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }) : "Pick a day"}</p>
            <h3>{selectedItems.length ? `${selectedItems.length} on this day` : "Nothing on this day yet"}</h3>
          </div>
          {canEdit && (
            <button className="btn btn-primary btn-sm" type="button" onClick={() => openDraft()} disabled={busy}>
              Add event
            </button>
          )}
        </header>
        {selectedItems.length > 0 && (
          <div className="day-list">
            {selectedItems.map((item) => (
              <article key={item.id} className="item">
                <span className="rail" style={{ background: courseColor(item.course || courseFromEventTitle(item.title)) }} />
                <div>
                  <b>{item.title.replace(/^\[DUE\]\s*/, "")}</b>
                  <small>
                    {courseCode(item.course) || item.course || (item.kind === "due" ? "Due" : item.kind === "exam" ? "Exam" : item.kind === "work" ? "Study block" : "Class")}
                  </small>
                </div>
                <div className="when">
                  <strong>{dueClock(item.at) || "All day"}</strong>
                  {item.editable && (
                    <button type="button" className="text-btn" onClick={() => openDraft(item)}>
                      Edit
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
        {draft && canEdit && (
          <form
            className="cal-editor"
            onSubmit={(event) => {
              event.preventDefault();
              if (!draft.title.trim()) return;
              onSave({
                id: draft.googleId || undefined,
                title: draft.title.trim(),
                start: draft.start,
                end: draft.end,
              });
              setDraft(null);
            }}
          >
            <p className="effort-label">{draft.googleId ? "Edit event" : "New event"}</p>
            <label>
              Title
              <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required />
            </label>
            <div className="field-grid three">
              <label>
                Starts
                <input type="datetime-local" value={draft.start} onChange={(event) => setDraft({ ...draft, start: event.target.value })} required />
              </label>
              <label>
                Ends
                <input type="datetime-local" value={draft.end} onChange={(event) => setDraft({ ...draft, end: event.target.value })} required />
              </label>
            </div>
            <div className="cal-editor-actions">
              <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
                Save to Google
              </button>
              {draft.googleId && (
                <button
                  className="btn btn-ghost btn-sm"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    onDelete(draft.googleId);
                    setDraft(null);
                  }}
                >
                  Delete
                </button>
              )}
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setDraft(null)}>
                Cancel
              </button>
            </div>
          </form>
        )}
        {!canEdit && (
          <p className="cal-empty">Add the plan to Google Calendar to edit events here.</p>
        )}
      </section>
    </div>
  );
}
