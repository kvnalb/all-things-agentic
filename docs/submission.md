# Devpost submission copy — Taskmaster track

Source of truth for the tagline, project description, and demo narration. Every
claim here maps to shipped code. See `docs/demo-script.md` for the recording
checklist and `docs/architecture.md` for the diagram judges will see.

---

## 1. Tagline

**Recommended**

> Your syllabi, course sites, and Canvas become one calendar the agent keeps current all semester.

**Alternates**

> Canvas in. Calendar out. Rebuilt every hour, all semester.

> An agent that reads every source your deadlines hide in, then books the study time.

Rationale: the recommended line names the input mess and the output artifact,
which is what the Taskmaster track rewards. The second alternate reuses the
in-product headline from `frontend/src/screens/LoginScreen.tsx`, so the video and
the app say the same thing.

---

## 2. Project description

### The problem

A semester's deadlines never live in one place. Data 101 publishes its schedule
on its own website and leaves Canvas empty. Math 110 buries two midterms in a
paragraph of the syllabus PDF. Data 144 uses Canvas the way it was designed.
The real schedule is spread across a REST API, an HTML table, and prose, and
instructors move dates mid-term. Copying it into a calendar costs an evening and
goes stale by Friday.

### What StudyAgent does

StudyAgent is an owner-only service on Cloud Run that Cloud Scheduler wakes
every hour. On each wake it:

1. Pulls Fall 2026 assignments from Canvas over the REST API, skipping courses
   where the user holds a teaching role.
2. Reads attached course websites and uploaded syllabus files, storing an
   immutable snapshot of each revision in Cloud Storage.
3. Writes every deadline it finds to Firestore as a claim carrying its
   provenance, so any date can be traced to the source that asserted it.
4. Merges claims into one canonical schedule, recording corroboration and
   conflicts instead of silently picking a winner.
5. Estimates effort for each item with a Gemini 3.7 Flash call routed through
   Google's Agent Development Kit.
6. Scores and ranks work with deterministic Python, then places study blocks
   inside the user's declared work hours under a daily-hour cap.
7. Syncs deadline events and color-coded study blocks to a dedicated
   `StudyAgent — Fall 2026` calendar, keyed so reruns never duplicate.
8. Persists the run, the tasks, and every calendar binding under one `run_id`.

A React dashboard renders the result: today's ranked work, an editable month
calendar, per-course coverage, and timed events. A voice dock answers spoken
questions using the persisted daily view, so answers describe the plan the agent
already wrote rather than improvising a new one.

### Where the model reasons, and where it does not

Gemini does two narrow jobs. It estimates hours for a task, and it extracts
events from unstructured course text. Everything consequential is deterministic
code:

- Priority scoring lives in `donor/scoring.py`. Identical input yields identical
  ranking on every run.
- Block placement lives in `donor/taskmaster_calendar.py` and respects work
  hours, off days, lead time, and the daily cap.
- Calendar writes happen in `taskmaster/google.py`, never from a tool the model
  can call.

Exactly one tool is exposed to the model, `emit_reminder_alert`, and it writes a
structured log line. A wrong model response can shift an estimate. It cannot
scramble a semester.

### Reliability decisions a reviewer can verify

- **Idempotent writes.** Each event carries a stable `studyagent_key` in
  `extendedProperties.private`, and Firestore stores a SHA-256 hash of the
  intended body. A rerun compares hashes and skips, patches, or inserts. An
  unchanged sync reports `created: 0, updated: 0`.
- **Bounded model calls.** Effort estimation runs at concurrency 6 with a 25s
  timeout per task, clamps results to 0.25–20 hours, and falls back to a 2-hour
  default while counting the failure.
- **Extraction fails closed.** A candidate event survives only if its evidence
  quote appears verbatim in the source text. Invalid model output yields zero
  candidates rather than a plausible guess.
- **Guarded ingestion.** URL sources must be HTTPS, resolve to a public address,
  follow no redirects, and stay under 10 MB with a 10s fetch timeout.
- **Calendar writes default to off.** The user enables them explicitly, and
  writes only ever touch the calendar the agent created.
- **Scoped credentials.** OAuth uses PKCE against a single allowed email. The
  Calendar scope is `calendar.app.created`. The Canvas token and OAuth refresh
  tokens live in Secret Manager.
- **Authenticated wake.** The Cloud Scheduler endpoint requires an OIDC bearer
  token, not the browser session cookie.
- **Bounded deletes.** Stale-binding cleanup caps at 50 per run and defers the
  remainder.

Ninety-nine tests across eleven modules cover the agent graph, claim merging,
calendar idempotency, rate-limit retry, ingestion safety, and OAuth.
`make check` runs the suite, the frontend build, and a secret scan.

### Technologies used

Gemini 3.7 Flash through Vertex AI, running at `thinking_level: LOW` so effort
estimates and spoken answers stay fast and cheap. Google Agent Development Kit 2
for the effort workflow, and the Google GenAI SDK for direct calls. Cloud Run hosts one
container serving FastAPI and the compiled React build. Firestore holds runs,
claims, canonical items, tasks, and calendar bindings. Cloud Storage holds
source snapshots. Secret Manager holds credentials. Cloud Scheduler drives the
hourly wake. Google Calendar API performs the writes. Python 3.12, FastAPI, and
Pydantic on the backend. React, TypeScript, Vite, and Tailwind on the frontend,
with the browser Web Speech API for voice input and speech synthesis for replies.

### Other data sources used

Real Berkeley bCourses Fall 2026 enrollments via the Canvas LMS REST API. Public
course websites fetched over HTTPS. Syllabus PDFs uploaded by the owner. Google
Calendar as both a write target and a read source for existing deadlines. A
sanitized SQLite fixture of roughly 80 assignments across five courses backs
demo mode so the project can be reviewed without live credentials.

### Findings and learnings

Idempotency turned out to be the whole product. An agent that reruns hourly is
only tolerable if a rerun is boring, so hashing each event's intended body and
comparing before writing mattered more than any prompt work.

Shrinking the model's job made the system trustworthy. An earlier version let
the model rank tasks, and identical input produced different orderings across
runs. Moving ranking into a scoring function fixed that and left the model doing
the thing it is actually good at, which is guessing how long a problem set takes.

Requiring verbatim evidence for extracted events cost recall and bought
correctness. Some real dates get dropped. No invented ones survive.

Pointing the agent at a calendar we personally rely on changed the defaults.
Writes ship off, scoped to a calendar the agent created, with a per-run delete
cap.

### Known limitations

- Owner-only. Access is restricted to a single allowed email.
- Uploaded and fetched sources persist with full revision history, and the
  extraction code is tested, but extraction results do not yet merge into the
  canonical registry automatically.
- Reminder escalation writes a structured log line rather than sending mail.
- Conflicting claims surface in the UI as a read-only view. Resolution is manual.
- Sync runs inside the request that triggers it. There is no separate worker.
- Demo mode reads the SQLite fixture, not live Canvas.

---

## 3. Demo video script (~4:00)

Record unedited in one pass. Narration is written to be read aloud at a normal
pace. Complete every item under "Before recording" in `docs/demo-script.md`
first.

### 0:00–0:20 — Open on the outcome

**Screen:** Google Calendar, week view, `StudyAgent — Fall 2026` selected and
populated with `[DUE]` events and colored `Work:` blocks.

> This is my fall semester. Six courses, every deadline in one calendar, study
> time already booked around them. I never typed any of it in. An agent built
> this, and it rebuilds it every hour.

### 0:20–0:50 — Name the mess

**Screen:** Three quick cuts. The Canvas course list. A course website showing
its deadline table. A syllabus PDF with midterm dates written into a paragraph.

> Here's why that's hard. Data 101 posts deadlines on its own site and leaves
> Canvas empty. Math 110 hides two midterms in a paragraph of the syllabus.
> Data 144 uses Canvas properly. So my actual schedule is scattered across an
> API, a webpage, and a PDF, and it changes during the term.

### 0:50–1:35 — Show the agent working

**Screen:** Setup screen with discovered Fall '26 courses, the Data 101 and
Math 110 URLs, and the attached syllabus. Click **Sync now**. Let the sync
summary land, then highlight the created, updated, skipped, and submitted counts.

> StudyAgent reads all three. Canvas over its REST API, the course sites over
> HTTPS, the syllabus file I uploaded. Every deadline it finds becomes a claim in
> Firestore that remembers which source asserted it, and the claims merge into
> one canonical schedule. Then for each item, a Gemini 3.7 Flash call through
> Google's Agent Development Kit estimates how many hours the work will take.
>
> That estimate is the only judgment the model makes. Ranking, block placement,
> and calendar writes are deterministic Python, so a bad model response can move
> one number. It can't scramble my semester.

### 1:35–2:20 — Show the consequence

**Screen:** In Google Calendar, open one `[DUE]` event and show the source link
in its description, then the colored `Work:` blocks leading up to it. Cut to the
dashboard **Today** tab and its hero card.

> Here's what the agent actually did. A due-date event that links back to the
> source that justified it, and study blocks placed inside the work hours I
> chose, under my daily cap, colored by course. The dashboard shows the same
> plan ranked, with the one thing I should start now.

**Screen:** Tap the voice dock mic. Ask: "What should I work on today?" Let the
spoken answer play.

> And I can just ask. That answer comes from the plan the agent already wrote,
> not from a fresh guess.

### 2:20–3:00 — Prove it is long-running and idempotent

**Screen:** Cloud Scheduler console showing the hourly job. Firestore `runs`
collection showing a document with `trigger: scheduler`. Then click **Sync now**
again with nothing changed.

> This is what makes it an agent instead of a button. Cloud Scheduler wakes the
> service every hour and posts to an authenticated internal endpoint. Firestore
> holds the semester's state between wakes, so Cloud Run scales to zero and
> costs nothing while I'm asleep. Watch what happens when nothing changed:
> created zero, updated zero, everything skipped. Every event carries a stable
> key and a hash of its intended contents, so a rerun does nothing.

**Screen:** Apply the changed-deadline fixture and sync once more.

> Move one deadline, and it patches that one event instead of leaving a second
> copy behind.

### 3:00–3:35 — Prove it runs on Google Cloud

**Screen:** `docs/architecture.md` diagram, then the Cloud Run service and its
active revision, a sanitized Vertex AI log line showing a `run_id`, and the
Firestore `tasks`, `calendar_bindings`, and `runs` collections.

> All of this runs on Google Cloud. FastAPI and the React build ship in one
> Cloud Run container. Gemini runs through Vertex AI. Firestore holds state,
> Cloud Storage holds source snapshots, Secret Manager holds the Canvas token
> and my OAuth refresh tokens. A single run ID threads through the logs, the
> claims, and every calendar binding, so I can trace any event on my calendar
> back to the sync that created it and the source that justified it.

### 3:35–4:00 — Close

**Screen:** Return to the calendar, then the dashboard.

> Calendar writes stay off until I turn them on, and they only ever touch the
> calendar the agent created for itself. A semester isn't a prompt. It's a
> four-month task. StudyAgent watches it, decides what matters, books the time,
> records what it did, and goes back to sleep.

### Recording notes

- Judging requires visible proof the backend runs on Google Cloud. The 3:00–3:35
  segment carries that, so do not cut it for time.
- Use the sanitized fixture names and counts. No tokens, private course bodies,
  or OAuth payloads on screen.
- If the live sync is slow, start it, keep narrating, and return to the counts.
  Do not cut away and back, since an unedited take reads as more credible.
