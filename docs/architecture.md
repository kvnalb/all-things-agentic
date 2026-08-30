# StudyAgent architecture

## System design

```mermaid
flowchart LR
    C[Canvas] --> R[Cloud Run / FastAPI]
    W[Course sites and syllabi] --> R
    S[Cloud Scheduler] -->|OIDC hourly wake| R
    UI[React setup and dashboard] --> R
    SM[Secret Manager] --> R
    R --> A[ADK 2 workflow]
    A --> V[Gemini 3.5 Flash / Vertex AI]
    A --> P[Deterministic planner]
    P --> G[Dedicated Google Calendar]
    R <--> F[Firestore config, tasks, bindings, runs]
    R <--> B[Private GCS source revisions]
```

Cloud Run is stateless and may scale to zero. Firestore carries semester state
across wakes. GCS preserves immutable source revisions. Secrets never enter
Firestore or the browser.

## Agent design

```mermaid
flowchart TD
    T[Manual or scheduled trigger] --> O[Observe Canvas and sources]
    O --> D[Normalize, deduplicate, skip submitted]
    D --> X[Grounded source extraction]
    X --> E[ADK effort estimator]
    E --> C[Clamp to 0.25–20 hours]
    C --> P[Deterministic priority score]
    P --> B[Budget and place study blocks]
    B --> K{Stable Calendar binding?}
    K -->|Missing| I[Create]
    K -->|Changed| U[Patch]
    K -->|Unchanged| N[Skip]
    I --> R[Persist run]
    U --> R
    N --> R
```

Gemini extracts evidenced schedule facts and estimates effort. Dates,
submission filtering, priority, study windows, colors, idempotency, and writes
are deterministic. Writes are restricted to the dedicated calendar.
