const REQUEST_TIMEOUT_MS = 30_000;

export async function api(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { ...options, signal: options?.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  if (response.status === 401) {
    const error = new Error("Connect Google to continue") as Error & { status?: number };
    error.status = 401;
    throw error;
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

export function formatDue(value: unknown): string {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function dueClock(value: unknown): string {
  if (!value) return "";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function dueIn(value: unknown): string {
  if (!value) return "";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return "";
  const hours = Math.round((date.getTime() - Date.now()) / 36e5);
  if (hours >= 0 && hours < 24) return hours <= 1 ? "Due in ~1 hour" : `Due in ${hours} hours`;
  if (hours < 0 && hours > -24) return "Overdue";
  const days = Math.round(hours / 24);
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days > 1) return `Due in ${days} days`;
  return `${-days} days overdue`;
}

export function dayLabel(value: unknown): string {
  if (!value) return "No date";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return "No date";
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diff = Math.round((target.getTime() - start.getTime()) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return date.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

export function courseCode(label: unknown): string {
  const text = String(label || "");
  const match = text.match(/[A-Z]{2,}\s?\d+[A-Z]*/i);
  return match ? match[0].toUpperCase() : text.slice(0, 18);
}

export function prettyLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export function humanSync(run?: { state?: string; trigger?: string; started_at?: string } | null): { ok: boolean; text: string } {
  if (!run?.started_at) return { ok: true, text: "Not synced yet" };
  const when = new Date(String(run.started_at)).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  if (run.state === "failed") return { ok: false, text: `Couldn’t update · ${when}` };
  if (run.trigger === "scheduler") return { ok: true, text: `Updated on schedule · ${when}` };
  return { ok: true, text: `Updated ${when}` };
}

export function groupByDay(rows: Array<Record<string, unknown>>, field = "due_at"): Array<{ label: string; items: Array<Record<string, unknown>> }> {
  const groups = new Map<string, Array<Record<string, unknown>>>();
  for (const row of rows) {
    const label = dayLabel(row[field]);
    const list = groups.get(label) || [];
    list.push(row);
    groups.set(label, list);
  }
  return [...groups.entries()].map(([label, items]) => ({ label, items }));
}

export function parseWhen(value: unknown): Date | null {
  if (value == null || value === "") return null;
  if (typeof value === "object" && value !== null && "seconds" in value) {
    const seconds = Number((value as { seconds: number }).seconds);
    if (Number.isFinite(seconds)) return new Date(seconds * 1000);
  }
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    const [year, month, day] = text.split("-").map(Number);
    return new Date(year, month - 1, day);
  }
  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function dayStamp(value: unknown): string | null {
  const date = parseWhen(value);
  if (!date) return null;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function startOfDay(date = new Date()): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function toLocalInput(value: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

export function effortHours(row: Record<string, unknown>): number {
  const n = Number(row.estimated_hours ?? row.hours ?? 0);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export type CourseLoad = { label: string; count: number };
export type NextExam = { title: string; course: string; at: Date };

export function planStats(
  schedule: Array<Record<string, unknown>>,
  daily: { active: Array<Record<string, unknown>>; upcoming?: Array<Record<string, unknown>>; daily_cap_hours?: number },
  timedEvents: Array<Record<string, unknown>>,
) {
  const today = startOfDay();
  const todayKey = dayStamp(today);
  const weekEnd = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 7);
  let dueToday = 0;
  let nextSeven = 0;
  let overdue = 0;
  const courseCounts = new Map<string, number>();

  for (const row of schedule) {
    const due = parseWhen(row.due_at);
    if (!due) continue;
    if (due < today) overdue += 1;
    if (dayStamp(due) === todayKey) dueToday += 1;
    if (due >= today && due < weekEnd) {
      nextSeven += 1;
      const label = String(row.course_label || row.course || "Class");
      courseCounts.set(label, (courseCounts.get(label) || 0) + 1);
    }
  }

  let hoursOpen = 0;
  for (const task of daily.active) hoursOpen += effortHours(task);

  const byCourse: CourseLoad[] = [...courseCounts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);

  let nextExam: NextExam | null = null;
  for (const row of timedEvents) {
    const kind = String(row.kind || "").toLowerCase();
    if (kind !== "exam" && kind !== "quiz") continue;
    const at = parseWhen(row.start_at);
    if (!at || at < today) continue;
    if (!nextExam || at < nextExam.at) {
      nextExam = { title: String(row.title || "Exam"), course: String(row.course_label || ""), at };
    }
  }

  const cap = Number(daily.daily_cap_hours || 0);
  return { dueToday, nextSeven, overdue, hoursOpen, byCourse, nextExam, cap };
}
