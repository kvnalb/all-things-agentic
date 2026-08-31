# Semester Agent — Implementation Plan

**Branch:** `exp/semester-agent`  
**Baseline commit:** snapshot after donor port (see git log).  
**Verification:** `make check` — **PASS** (57 tests, frontend build OK) as of plan authoring.

## Current architecture (as-is)

| Path | What runs | Calendar output |
|------|-----------|-----------------|
| **Live** | `TaskmasterService.sync_semester()` → `analyze_all_courses()` → `_prepare_tasks()` → ADK estimates → `rebuild_calendar_and_brief(..., calendar_writer, run_id)` | **Study/work blocks only** via `CalendarWriter.sync_donor_blocks()` |
| **Dormant** | `CalendarWriter.sync(tasks, blocks)` + `studyagent/extraction.py` → `AcademicEventCandidate` | Due markers + study blocks; timed events default **+15 min** (`google.py`) |
| **Donor CLI** | `donor/taskmaster_calendar.py` | Separate local “Taskmaster” calendar; full wipe/rebuild |

**Firestore today:** `tasks`, `calendar_bindings`, `artifacts/{task_list,daily_view,syllabus_analysis}`, `extractions` (connectors path, not wired to `sync_semester`).

**Frontend today:** Setup saves `UserConfig` (courses + 3 prefs); URLs/syllabus upload UI is **not persisted**; dashboard is read-only daily view + sync + calibration feedback.

---

## Concern map → phases

| # | Concern | Root cause (code) | Primary phase |
|---|---------|-------------------|---------------|
| 1 | Normalized due-date DB + provenance → table view | Tasks lack unified due registry; no export API/UI | P1 |
| 1a | Auditable agent calendar events | `calendar_bindings` minimal; no reasoning/course link in UI | P1 |
| 2 | Lectures 15 min | `CalendarWriter.sync()` hardcodes `timedelta(minutes=15)`; path not in live sync | P2 |
| 3 | Office hours separate calendar/color/conflicts | Single `Settings.calendar_name`; no event-kind routing | P2 |
| 4 | Partial onboarding + no control center | `store.py` drops `non_canvas_courses`; React omits donor fields | P3 |
| 5 | Color coding | Documented in donor `_pick_color`; cloud path reuses colors for work blocks only | P3 |
| 6 | Duplicate calendar events | Dual writers (donor local vs cloud), key namespace, legacy manual events | P2 |
| 7 | 3/6 courses, sparse coverage | `selected_course_ids` filter, term regex in syllabus, past-due skip, teaching role skip | P1–P2 |

Recommended order: **P1 (truth + visibility) → P2 (calendar fidelity + dedupe) → P3 (UX/control) → P4 (hardening)**.

---

## Phase 1 — Source of truth: dues, provenance, audit table

### Goals

1. One **normalized due registry** (assignments + syllabus + manual + extracted events) with provenance.
2. **Spreadsheet/dashboard table** for dues (sort/filter by course, due date, source).
3. Extend **`calendar_bindings`** (or sibling collection) into an **agent event audit log** for every Google write.

### Data models (`backend/studyagent/taskmaster/models.py` + new `due_registry.py` or extend `Task`)

```python
# Conceptual — implement as Pydantic + Firestore serializers
class DueProvenance(str, Enum):
    canvas_assignment | syllabus_llm | syllabus_verified | manual | extraction | recurring

class NormalizedDue(BaseModel):
    id: str                    # stable: source:source_ref or uuid for manual
    course_id: str | None
    course_label: str
    title: str
    due_at: datetime
    date_only: bool
    kind: Literal["assignment", "exam", "project", "other"]
    provenance: DueProvenance
    source_url: str | None
    source_revision_id: str | None
    confidence: str | None     # for LLM rows
    superseded_by: str | None  # dedupe lineage

class CalendarEventAudit(BaseModel):
    binding_key: str           # work:|deadline:|lecture:|office:
    google_event_id: str
    calendar_id: str
    event_kind: str
    course_id: str | None
    course_label: str
    task_or_due_id: str | None
    reasoning_note: str        # human-readable: rank, color rule, placement slot
    run_id: str
    desired_hash: str
    synced_at: datetime
```

**Firestore layout**

- `due_items/{id}` — normalized dues (replace or mirror `tasks` for due-specific fields).
- `calendar_bindings/{doc_id}` — keep idempotent keys; add `event_kind`, `course_id`, `reasoning_note`, `due_item_id`, `calendar_role` (`study` | `academic` | `office_hours`).
- `artifacts/due_export` — optional cached CSV/JSON snapshot per run.

### Service changes

- **`TaskmasterService.sync_semester()`** (`service.py`):
  - After `_prepare_tasks`, upsert `due_items` from Canvas + syllabus tasks (before estimates).
  - After placement, enrich each placement with `reasoning_note` (priority score, days-to-due, color rule name).
  - Pass notes into `sync_donor_blocks` / future `sync`.

- **`store.py`**: `save_due_items()`, `list_due_items()`, `list_calendar_audit(limit, course, kind)`.

- **Wire extraction read path**: After syllabus analyze, optionally merge `connectors/extractions` candidates into `due_items` with `provenance=extraction` (read-only until P2 writes calendar).

### API (`api.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/dues` | Paginated table JSON (`course`, `due_at`, `provenance`, `source_url`) |
| GET | `/api/dues/export.csv` | Dashboard download |
| GET | `/api/calendar-events` | Audit log (agent-created events + reasoning) |
| GET | `/api/coverage` | Per-course counts: canvas assignments, syllabus items, scheduled blocks, gaps |

### Frontend (`App.tsx`)

- New **“Due dates”** tab: sortable table, provenance badge, link to Canvas/source.
- New **“Calendar log”** tab: last N bindings with reasoning + Google event id.

### Tests

- `tests/test_taskmaster.py`: upsert idempotency, provenance fields, export shape.
- Regression: empty `selected_course_ids` vs explicit selection behavior documented in tests.

### Addresses

- **#1**, **#1a**, foundation for **#7** visibility (coverage endpoint).

---

## Phase 2 — Calendar fidelity: durations, calendars, dedupe

### 2a — Fix 15-minute lectures (#2)

- **Do not** use `CalendarWriter.sync()` due-line for lectures.
- In **`sync_semester`**, after P1 due registry is populated, run **extraction pipeline**:
  - Reuse `studyagent/extraction.py` + `AcademicEventCandidate` (`kind` includes lecture, office_hours, exam).
  - Map `EventKind` → `end_at` from model output; fallback: syllabus `recurring_work()` durations, then course-default (e.g. 50/80 min), never 15 unless explicit.
- New method: `CalendarWriter.sync_academic_events(events: list[AcademicCalendarEvent], run_id)` with keys `lecture:{candidate_id}` / `office:{candidate_id}`.

### 2b — Office hours calendar (#3)

- Extend **`Settings`** / `UserConfig`:
  - `office_hours_calendar_id` (optional secondary calendar) OR `calendar_roles: dict[str, str]` mapping kind → calendar id.
- **`Google._calendar()`**: support multiple markers (`CALENDAR_MARKER_STUDY`, `CALENDAR_MARKER_OFFICE`).
- Office hours events: `colorId` fixed (e.g. `9` blue); set `transparency` / do not mark busy if conflicts allowed (Google: `transparency: transparent` + separate calendar).
- Document: conflicts with personal calendar are OK; study calendar remains busy.

### 2c — Duplicate events (#6)

| Failure mode | Mitigation |
|--------------|------------|
| Cloud + old donor local calendar both active | One-time migration doc; delete local Taskmaster calendar or disable donor OAuth path in cloud deploy |
| Same assignment as `[DUE]` and `Work:` block | **By design** — different keys; UI explains pair |
| Re-insert on hash change | Keep `desired_hash`; ensure `summary`/`description` stable fields |
| Legacy events outside bindings | Admin script: list Google events with `extendedProperties.private.studyagent_key`; orphan cleanup endpoint `POST /api/calendar/reconcile` |

- Unify key namespace in code comments + `docs/architecture.md`.
- Optional: single `sync_all(run_id)` orchestrator calling `sync_donor_blocks` + `sync_academic_events` with shared `desired` set per calendar.

### 2d — Course coverage (#7)

- **`canvas_poller.py`**: Log skipped courses (not selected, teaching, no due, past due) into run summary → surfaced in `/api/coverage`.
- **`syllabus.py`**: Relax or parameterize term filter (`Fall 2026` regex); use Canvas enrollment term + config `term_label`.
- **`store.py`**: Persist `non_canvas_courses` and manual course URLs on `UserConfig`.
- **`_prepare_tasks`**: Include recurring syllabus work (`recurring_work()`) in cloud path (currently underused if cache empty).
- Frontend: show **6/6 courses** checklist with reason when a course has zero future dues.

### Addresses

- **#2**, **#3**, **#6**, **#7** (data ingestion side).

---

## Phase 3 — Onboarding parity + control center (#4, #5)

### Onboarding parity

Extend **`UserConfig`** (`models.py`) to match donor `onboarding.py`:

- `non_canvas_courses: str`
- `excluded_courses`, `priority_courses` (already partial)
- `work_day_start`, `work_day_end`, `off_days`, `reminder_style`, `effort_padding`
- `course_source_urls: dict[str, str]` (Data 101, Math 110, etc.)
- `syllabus_artifact_refs: dict[str, str]` (GCS/Firestore blob ids)

**`store.py`**: Remove hardcoded `"non_canvas_courses": ""`; round-trip all fields in `save_config_dict`.

**`api.py`**: `POST /api/config` already accepts `UserConfig` — expand schema.

**`App.tsx`**: Multi-step setup wizard (courses → schedule prefs → exclusions → manual courses → sources/upload) OR “Advanced” drawer on dashboard for post-onboarding edits.

### Control center (post-onboarding)

Dashboard sections:

1. **Sync status** (existing) + per-stage errors from run doc.
2. **Course coverage** (P1 API).
3. **Preferences** — edit and `POST /api/config` without re-running full OAuth.
4. **Calibration** (existing feedback).
5. **Calendar log** (P1).

### Color coding (#5)

- Add `docs/color-legend.md` (or section in `architecture.md`):
  - Work blocks: donor constants `COLOR_CRITICAL` … `COLOR_PRIORITY` (`taskmaster_calendar.py`).
  - Academic events: propose fixed map by `EventKind` (lecture=green, exam=red, office_hours=blue).
- **`_pick_color`**: Export as `pick_work_block_color(task, cfg, due_local)`; unit test thresholds (2/5/14 days).
- API: `GET /api/calendar/colors` returns legend for UI chips.

### Addresses

- **#4**, **#5**.

---

## Phase 4 — Hardening & ops

- **Idempotent sync**: Persist run stages; retry failed estimate without duplicating calendar rows.
- **Scheduled sync**: `internal/sync` — verify auth header + document Cloud Scheduler.
- **Observability**: Structured logs with `run_id`; never log Canvas tokens.
- **Manual verification checklist** (demo): 6 courses selected → coverage 6/6 → table shows dues → calendar shows work blocks + lectures with correct duration → office hours on secondary calendar → no duplicate orphan events.

---

## File touch list (by phase)

| Phase | Backend | Frontend | Docs/tests |
|-------|---------|----------|------------|
| P1 | `service.py`, `store.py`, `models.py`, `google.py`, `api.py`, `cloud.py` | `App.tsx`, `styles.css` | `test_taskmaster.py`, `architecture.md` |
| P2 | `extraction.py` (adapter), `google.py`, `donor/syllabus.py`, `donor/canvas_poller.py`, `donor/taskmaster_calendar.py`, new `calendar_sync.py` | Coverage UI | `test_sources.py`, new `test_calendar_sync.py` |
| P3 | `store.py`, `models.py`, `api.py`, `calibration.py` | Wizard + control center | `color-legend.md`, `demo-script.md` |
| P4 | `runner.py`, `api.py` | — | `devlog.md` |

---

## Suggested first PR slice (when leaving experimental branch)

1. P1 `due_items` + `GET /api/dues` + table UI (no calendar behavior change).
2. P1a enrich `calendar_bindings` + audit GET.
3. P2 wire extraction → `sync_academic_events` with real durations.
4. P3 config round-trip + control center prefs.

---

## Open decisions (confirm before P2)

1. **Single vs dual calendar** for office hours — recommend secondary calendar + transparent busy.
2. **Due markers on calendar** — enable `deadline:` keys in live sync or keep dues table-only?
3. **Term filter** — config-driven `term_patterns` vs Canvas API term id.

---

## References

- Live sync entry: `backend/studyagent/taskmaster/service.py` — `sync_semester`
- 15-minute default: `backend/studyagent/taskmaster/google.py` — `CalendarWriter.sync`
- Color rules: `backend/studyagent/taskmaster/donor/taskmaster_calendar.py` — `_pick_color`
- Config gap: `backend/studyagent/taskmaster/store.py` — `non_canvas_courses` forced empty
- Extraction: `backend/studyagent/extraction.py`, `studyagent/models.py` — `AcademicEventCandidate`
