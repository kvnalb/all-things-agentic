export type Screen = "boot" | "login" | "onboarding" | "setup" | "dashboard";
export type DashboardTab = "today" | "calendar" | "schedule" | "claims" | "coverage" | "events";

export type Course = { id: string; code: string; title: string; role: string };

export type Status = {
  google_connected: boolean;
  canvas_connected: boolean;
  calendar_writes_enabled?: boolean;
  calendar_id?: string;
  calendar_url?: string;
  onboarding_complete?: boolean;
  preferences?: {
    priority_mode?: string;
    lead_time_days?: number;
    work_day_start?: number;
    work_day_end?: number;
    off_days?: string[];
    daily_cap_hours?: number;
    effort_padding?: number;
    priority_courses?: string[];
    excluded_courses?: string[];
  };
  registry?: Record<string, unknown>;
  last_run?: { state: string; summary?: Record<string, number>; trigger?: string; started_at?: string };
  next_sync_at: string;
};

export type DailyTask = Record<string, string | number | boolean>;
export type CalEvent = {
  id?: string;
  title: string;
  start: string;
  end?: string;
  description?: string;
  editable?: boolean;
};
export type Daily = {
  active: DailyTask[];
  upcoming: DailyTask[];
  daily_cap_hours?: number;
  calendar?: { events?: CalEvent[]; has_calendar_access?: boolean };
};

export type Calibration = {
  global_effort_multiplier: number;
  global_samples: number;
  by_course: Record<string, { effort_multiplier: number; samples: number }>;
};

export type RegistryRow = Record<string, unknown>;
export type CoverageCourse = Record<string, unknown>;

export const configDefaults = {
  priority_mode: "grade",
  lead_time_days: 5,
  reminder_style: "ramping",
  work_day_start: 9,
  work_day_end: 21,
  off_days: [] as string[],
  priority_courses: [] as string[],
  excluded_courses: [] as string[],
  daily_cap_hours: 4,
  effort_padding: 1.2,
  calendar_writes_enabled: false,
  onboarding_complete: false,
};
