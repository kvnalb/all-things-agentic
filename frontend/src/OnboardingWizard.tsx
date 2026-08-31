import { useEffect, useState } from "react";
import "./taskmaster.css";

export type UserPreferences = {
  selected_course_ids: string[];
  priority_mode: string;
  lead_time_days: number;
  reminder_style: string;
  work_day_start: number;
  work_day_end: number;
  off_days: string[];
  priority_courses: string[];
  excluded_courses: string[];
  daily_cap_hours: number;
  effort_padding: number;
  calendar_writes_enabled: boolean;
  onboarding_complete: boolean;
};

const PRIORITY_OPTIONS = [
  { value: "grade", label: "Whatever's worth more of my grade" },
  { value: "urgency", label: "Whatever's due soonest" },
  { value: "effort", label: "Whatever takes longest" },
  { value: "avoidance", label: "Whatever I've been putting off" },
];

const LEAD_OPTIONS = [
  { value: 0, label: "The day of" },
  { value: 2, label: "1 to 2 days" },
  { value: 5, label: "3 to 5 days" },
  { value: 7, label: "A week or more" },
];

const REMINDER_OPTIONS = [
  { value: "minimal", label: "One heads-up and done" },
  { value: "ramping", label: "Gentle, ramping up as it gets close" },
  { value: "persistent", label: "Persistent for high-stakes work" },
  { value: "relentless", label: "Relentless until it's finished" },
];

const CAP_OPTIONS = [
  { value: 2, label: "1 to 2 hours" },
  { value: 4, label: "3 to 4 hours" },
  { value: 6, label: "5 or more hours" },
  { value: 24, label: "No limit" },
];

const PADDING_OPTIONS = [
  { value: 1.0, label: "Usually accurate" },
  { value: 1.3, label: "I tend to underestimate" },
  { value: 1.2, label: "No idea" },
];

const DAY_OPTIONS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const DEFAULTS: UserPreferences = {
  selected_course_ids: [],
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
  onboarding_complete: false,
};

type Props = {
  api: (path: string, options?: RequestInit) => Promise<unknown>;
  onComplete: () => void;
  editMode?: boolean;
  onCancel?: () => void;
};

export default function OnboardingWizard({ api, onComplete, editMode, onCancel }: Props) {
  const [step, setStep] = useState(0);
  const [prefs, setPrefs] = useState<UserPreferences>(DEFAULTS);
  const [priorityRaw, setPriorityRaw] = useState("");
  const [excludedRaw, setExcludedRaw] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const loaded = (await api("/api/config")) as UserPreferences;
        setPrefs({ ...DEFAULTS, ...loaded });
        setPriorityRaw((loaded.priority_courses || []).join(", "));
        setExcludedRaw((loaded.excluded_courses || []).join(", "));
      } catch {
        /* first-time setup uses defaults */
      }
    })();
  }, [api]);

  const steps = editMode ? 6 : 7;
  const lastStep = steps - 1;

  function update<K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) {
    setPrefs((prev) => ({ ...prev, [key]: value }));
  }

  function toggleOffDay(day: string) {
    setPrefs((prev) => {
      const off = new Set(prev.off_days);
      if (off.has(day)) off.delete(day);
      else off.add(day);
      return { ...prev, off_days: Array.from(off) };
    });
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const payload: UserPreferences = {
        ...prefs,
        priority_courses: priorityRaw
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        excluded_courses: excludedRaw
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        onboarding_complete: true,
      };
      await api("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      onComplete();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wrap">
      <div className="masthead">
        <p className="eyebrow">{editMode ? "Preferences" : "Taskmaster setup"}</p>
        <h1 className="today">{editMode ? "Scheduling preferences" : "How should I schedule you?"}</h1>
        <p className="load">
          {editMode
            ? "These settings control work blocks, quiet hours, and priority scoring. Times use Pacific (America/Los_Angeles)."
            : "A few questions so I never put study blocks in the middle of the night. Times use Pacific (America/Los_Angeles)."}
        </p>
      </div>

      <div className="setup-progress">
        {Array.from({ length: steps }, (_, i) => (
          <span key={i} className={`setup-dot${i <= step ? " setup-dot-on" : ""}`} />
        ))}
      </div>

      <div className="setup-panel">
        {step === 0 && (
          <>
            <h2 className="setup-q">When everything&apos;s due at once, what should I prioritize first?</h2>
            <div className="setup-choices">
              {PRIORITY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`setup-choice${prefs.priority_mode === opt.value ? " setup-choice-on" : ""}`}
                  onClick={() => update("priority_mode", opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <h2 className="setup-q">How far ahead of a deadline do you like to start big assignments?</h2>
            <div className="setup-choices">
              {LEAD_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`setup-choice${prefs.lead_time_days === opt.value ? " setup-choice-on" : ""}`}
                  onClick={() => update("lead_time_days", opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h2 className="setup-q">How aggressive should reminders be?</h2>
            <div className="setup-choices">
              {REMINDER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`setup-choice${prefs.reminder_style === opt.value ? " setup-choice-on" : ""}`}
                  onClick={() => update("reminder_style", opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h2 className="setup-q">When can I schedule work blocks?</h2>
            <p className="setup-hint">Quiet hours — I won&apos;t place blocks outside this window.</p>
            <div className="setup-row">
              <label>
                Start (24h)
                <input
                  type="number"
                  min={0}
                  max={23}
                  value={prefs.work_day_start}
                  onChange={(e) => update("work_day_start", Number(e.target.value))}
                />
              </label>
              <label>
                End (24h)
                <input
                  type="number"
                  min={1}
                  max={24}
                  value={prefs.work_day_end}
                  onChange={(e) => update("work_day_end", Number(e.target.value))}
                />
              </label>
            </div>
            <p className="setup-hint">Full days to keep clear</p>
            <div className="setup-days">
              {DAY_OPTIONS.map((day) => (
                <button
                  key={day}
                  type="button"
                  className={`setup-day${prefs.off_days.includes(day) ? " setup-day-on" : ""}`}
                  onClick={() => toggleOffDay(day)}
                >
                  {day}
                </button>
              ))}
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <h2 className="setup-q">Course priorities</h2>
            <label className="setup-field">
              Courses that matter most (comma separated, partial names OK)
              <input value={priorityRaw} onChange={(e) => setPriorityRaw(e.target.value)} placeholder="e.g. DATA 144, ECON 136" />
            </label>
            <label className="setup-field">
              Courses to ignore (e.g. classes you TA, not take)
              <input value={excludedRaw} onChange={(e) => setExcludedRaw(e.target.value)} placeholder="optional" />
            </label>
          </>
        )}

        {step === 5 && (
          <>
            <h2 className="setup-q">Daily workload &amp; estimates</h2>
            <p className="setup-hint">Max hours of coursework per day</p>
            <div className="setup-choices">
              {CAP_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`setup-choice${prefs.daily_cap_hours === opt.value ? " setup-choice-on" : ""}`}
                  onClick={() => update("daily_cap_hours", opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <p className="setup-hint">How good are you at estimating how long work takes?</p>
            <div className="setup-choices">
              {PADDING_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`setup-choice${prefs.effort_padding === opt.value ? " setup-choice-on" : ""}`}
                  onClick={() => update("effort_padding", opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </>
        )}

        {step === lastStep && !editMode && (
          <>
            <h2 className="setup-q">Here&apos;s how I&apos;ll work</h2>
            <ul className="setup-summary">
              <li>
                Priority: <b>{prefs.priority_mode}</b> · start <b>{prefs.lead_time_days}</b> day(s) before deadlines
              </li>
              <li>
                Window: <b>{prefs.work_day_start}:00 – {prefs.work_day_end}:00</b> Pacific
                {prefs.off_days.length > 0 && <> · off <b>{prefs.off_days.join(", ")}</b></>}
              </li>
              <li>
                Cap: <b>{prefs.daily_cap_hours}h</b>/day · reminders <b>{prefs.reminder_style}</b>
              </li>
            </ul>
          </>
        )}

        {error && <p className="setup-error">{error}</p>}

        <div className="setup-nav">
          {editMode && onCancel && (
            <button type="button" className="cal-btn setup-back" onClick={onCancel}>
              Cancel
            </button>
          )}
          {!editMode && step > 0 && (
            <button type="button" className="cal-btn setup-back" onClick={() => setStep((s) => s - 1)}>
              Back
            </button>
          )}
          {step < lastStep ? (
            <button type="button" className="cal-btn" onClick={() => setStep((s) => s + 1)}>
              Continue
            </button>
          ) : (
            <button type="button" className="cal-btn" onClick={() => void save()} disabled={busy}>
              {busy ? "Saving…" : editMode ? "Save preferences" : "Start scheduling"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
