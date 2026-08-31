/** Per-course palette — hash must match backend course_colors.py */
export const COURSE_PALETTE = [
  "#7EA6FF",
  "#FF8FA3",
  "#5FD3B4",
  "#FFC46B",
  "#C79BFF",
  "#6FD8E8",
  "#F0918C",
  "#9EDB6E",
];

export function courseColorIndex(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return hash % COURSE_PALETTE.length;
}

export function courseColor(name?: string, fallback = "var(--muted)") {
  if (!name) return fallback;
  return COURSE_PALETTE[courseColorIndex(name)];
}

/** Parse course from a calendar event title like "Work: Lab 1 (DATA 144)". */
export function courseFromEventTitle(title: string) {
  const match = title.match(/\(([^)]*)\)\s*$/);
  return match ? match[1].trim() : "";
}
