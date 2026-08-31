import { ArrowRight } from "lucide-react";
import type { Course } from "../types";

type Props = {
  busy: boolean;
  courses: Course[];
  selected: string[];
  priorityMode: string;
  lead: number;
  cap: number;
  dataUrl: string;
  mathUrl: string;
  syllabusCourse: string;
  syllabusName: string;
  onDiscover: () => void;
  onToggleCourse: (id: string, checked: boolean) => void;
  onPriority: (value: string) => void;
  onLead: (value: number) => void;
  onCap: (value: number) => void;
  onDataUrl: (value: string) => void;
  onMathUrl: (value: string) => void;
  onSyllabusCourse: (value: string) => void;
  onSyllabus: (file: File | null) => void;
  onSave: () => void;
};

export function SetupScreen({
  busy,
  courses,
  selected,
  priorityMode,
  lead,
  cap,
  dataUrl,
  mathUrl,
  syllabusCourse,
  syllabusName,
  onDiscover,
  onToggleCourse,
  onPriority,
  onLead,
  onCap,
  onDataUrl,
  onMathUrl,
  onSyllabusCourse,
  onSyllabus,
  onSave,
}: Props) {
  return (
    <div className="setup">
      <p className="eyebrow">Step 02 · courses</p>
      <h2>What should it watch?</h2>
      <p className="subcopy">Pick Fall ’26 student courses. Teaching roles stay out. Optional sites ground the registry.</p>
      <div className="setup-grid">
        <div className="glass">
          <button className="btn btn-ghost btn-block" type="button" onClick={onDiscover} disabled={busy}>
            Discover Fall ’26 courses
          </button>
          {courses.length ? (
            <div className="course-list" role="group" aria-label="Fall 2026 courses">
              {courses.map((course) => (
                <label key={course.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(course.id)}
                    onChange={(event) => onToggleCourse(course.id, event.target.checked)}
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
          ) : (
            <div className="empty" role="status">
              <h3>Nothing loaded</h3>
              <p>Discover first. Only Fall 2026 student enrollments appear.</p>
            </div>
          )}
        </div>
        <div className="glass">
          <div className="field-grid">
            <label>
              Prioritize
              <select value={priorityMode} onChange={(e) => onPriority(e.target.value)}>
                <option value="grade">Grade impact</option>
                <option value="urgency">Urgency</option>
                <option value="effort">Large tasks</option>
                <option value="avoidance">Balanced</option>
              </select>
            </label>
            <div className="field-grid three">
              <label>
                Start ahead
                <input type="number" min={0} max={21} value={lead} onChange={(e) => onLead(Number(e.target.value))} />
              </label>
              <label>
                Daily cap
                <input type="number" min={1} max={12} value={cap} onChange={(e) => onCap(Number(e.target.value))} />
              </label>
            </div>
            <label>
              Data 101 site
              <input value={dataUrl} onChange={(e) => onDataUrl(e.target.value)} />
            </label>
            <label>
              Math 110 site
              <input value={mathUrl} onChange={(e) => onMathUrl(e.target.value)} />
            </label>
            <label>
              Syllabus for
              <select value={syllabusCourse} onChange={(e) => onSyllabusCourse(e.target.value)}>
                <option value="">Select a course</option>
                {courses
                  .filter((course) => selected.includes(course.id))
                  .map((course) => (
                    <option key={course.id} value={course.id}>
                      {course.code}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Upload syllabus
              <input type="file" accept=".pdf,.html,.htm,.md,.txt" onChange={(e) => onSyllabus(e.target.files?.[0] ?? null)} />
              {syllabusName ? <small>{syllabusName}</small> : null}
            </label>
          </div>
          <button className="btn btn-primary btn-block save" type="button" onClick={onSave} disabled={busy || selected.length === 0}>
            Build registry ({selected.length}) <ArrowRight size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
