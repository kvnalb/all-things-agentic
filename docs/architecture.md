# StudyAgent architecture

StudyAgent is an owner-only academic Taskmaster. Cloud Scheduler wakes it every
hour, it observes Canvas and course sources, reasons about effort with Gemini
through ADK 2, plans deterministically, and reconciles a dedicated Google
Calendar. Firestore carries semester state between wakes so Cloud Run can scale
to zero.

## 1. Deployment and trust boundaries

**Figure 1. StudyAgent system architecture on Google Cloud.** Canvas, course
sources, and an hourly Cloud Scheduler wake all feed one Cloud Run container.
Gemini 3.7 Flash on Vertex AI estimates effort and extracts schedule facts, a
deterministic planner ranks and places the work, and `CalendarWriter` reconciles
a single dedicated Google Calendar. Firestore and Cloud Storage hold all durable
state, so Cloud Run carries none and can scale to zero between wakes.

```mermaid
---
title: "Figure 1 — StudyAgent system architecture on Google Cloud"
---
flowchart LR
    subgraph IN["Inputs"]
        UI["React SPA<br/>dashboard · calendar · voice dock"]
        WS["Web Speech API<br/>speech-to-text · playback"]
        CANVAS["Canvas LMS<br/>bCourses REST"]
        SITES["Course sites<br/>syllabus uploads"]
        SCHED["Cloud Scheduler<br/>hourly wake"]
    end

    subgraph GCP["Google Cloud project"]
        subgraph CR["Cloud Run · scales to zero"]
            API["FastAPI<br/>session + /internal/sync"]
            SVC["sync_semester"]
            EXT["Source ingestion<br/>fetch · normalize · extract"]
            ADK["ADK 2 Workflow<br/>effort_agent"]
            PLAN["Deterministic planner<br/>scoring · block placement"]
            CW["CalendarWriter"]
        end
        VX["Vertex AI<br/>Gemini 3.7 Flash"]
        SM[("Secret Manager<br/>Canvas + OAuth tokens")]
        FS[("Firestore<br/>runs · claims · canonical<br/>tasks · calendar_bindings")]
        GCS[("Cloud Storage<br/>source revisions")]
    end

    subgraph OUT["Action"]
        GCAL["Google Calendar<br/>StudyAgent — Fall 2026"]
    end

    WS --> UI
    UI -->|"session cookie"| API
    SCHED -->|"OIDC"| API
    API --> SVC
    CANVAS --> SVC
    SITES --> EXT
    SM -.-> SVC

    SVC --> EXT
    SVC --> ADK
    SVC --> PLAN
    ADK -->|"effort estimate"| VX
    EXT -->|"extract events"| VX
    EXT -->|"snapshot revision"| GCS
    SVC -->|"claims · canonical"| FS
    PLAN --> CW
    CW <--> FS
    CW -->|"insert · patch · skip"| GCAL
```

Secrets stay in Secret Manager and never reach Firestore or the browser. The
Calendar scope is `calendar.app.created`, so writes cannot touch the owner's
personal calendars. Cloud Run is stateless; every durable fact lives in
Firestore or Cloud Storage.

## 2. One sync run

**Figure 2. One hourly sync run, end to end.** Cloud Scheduler wakes the service
over an authenticated endpoint. Gemini is called twice, once to analyze syllabus
and course text and once per task to estimate effort, and both calls are bounded
by timeouts and clamps. Priority, block placement, and the Calendar writes stay
deterministic. When calendar writes are disabled the run stops after persisting
the registry.

```mermaid
---
title: "Figure 2 — One hourly sync run"
---
sequenceDiagram
    autonumber
    participant S as Cloud Scheduler
    participant A as FastAPI
    participant T as TaskmasterService
    participant F as Firestore
    participant C as Canvas
    participant G as Gemini 3.7 Flash
    participant P as Planner
    participant K as Google Calendar

    S->>A: POST /internal/sync (OIDC)
    A->>A: verify scheduler service account
    A->>T: sync_semester(trigger="scheduler")
    T->>F: start_run() → run_id
    T->>C: fetch Fall '26 assignments
    T->>G: analyze syllabus and course sources
    G-->>T: difficulty + evidenced facts
    T->>F: save claims · canonical · coverage

    alt calendar_writes_enabled = false
        T->>F: save daily view only
        T-->>A: registry_mode — no writes
    else calendar_writes_enabled = true
        loop per ready task · 6 concurrent · 25s timeout
            T->>G: estimate hours
            G-->>T: hours + confidence
            T->>T: clamp 0.25–20h · apply calibration
        end
        T->>P: score and place study blocks
        P-->>T: desired event set
        T->>K: reconcile events
        T->>F: save tasks · bindings · daily view · run state
        T-->>A: created / updated / skipped / deleted
    end
```

Gemini estimates effort and extracts evidenced schedule facts. Dates,
submission filtering, priority, study windows, colors, idempotency, and the
writes themselves are deterministic code, so a bad model response can shift one
estimate without corrupting the schedule.

## 3. Idempotent write decision

```mermaid
flowchart TD
    D["Desired event body<br/>title · time · description · color"] --> H["studyagent_key<br/>stable per task identity"]
    H --> L{"Firestore binding<br/>exists for key?"}
    L -->|"no"| INS["events().insert<br/>store google_event_id + desired_hash"]
    L -->|"yes"| CMP{"stored desired_hash<br/>equals sha256(body)?"}
    CMP -->|"yes"| SKIP["skip — no API call"]
    CMP -->|"no"| PAT["events().patch<br/>refresh desired_hash"]
    INS --> R["record action under run_id"]
    SKIP --> R
    PAT --> R
    R --> ST{"binding dropped<br/>from desired set?"}
    ST -->|"yes · under 50 per run"| DEL["events().delete"]
    ST -->|"cap reached"| DEF["delete_deferred<br/>retried next wake"]
```

Because the key is derived from task identity and the hash from the intended
body, an unchanged rerun performs no Calendar API calls at all and reports
`created: 0, updated: 0`. Deletes are capped at 50 per run so a bad upstream
change cannot cascade into mass removal. Rate-limited calls retry with
exponential backoff behind a 30-second HTTP timeout.

## Rendering diagram images

```bash
pnpm dlx @mermaid-js/mermaid-cli -i docs/architecture.md -o docs/architecture.png -t neutral -b white --scale 3
```

Each block exports as `docs/architecture-1.png` through `docs/architecture-3.png`.
