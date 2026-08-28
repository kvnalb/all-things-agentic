# Agent-merge workflow

Routine, unambiguous changes may be merged by an agent after deterministic CI succeeds on the current commit. CodeRabbit reviews asynchronously and never delays a merge by itself. Humans intervene for ambiguity, intent drift, undisclosed decisions, or unauthorized consequential actions.

```mermaid
flowchart TD
    H[Human defines outcome] --> I[Issue records outcome,<br/>constraints and acceptance criteria]
    I --> P[Agent posts preflight:<br/>intent, plan, assumptions, pause conditions]

    P --> Q{Intent unambiguous?}
    Q -->|No| C[Pause for human clarification]
    C --> U[Update canonical issue intent]
    U --> P
    Q -->|Yes| B[Implement focused change]

    B --> T[Run tests and inspect diff]
    T --> R[Open PR with intent, behavior change,<br/>decisions, evidence and limitations]

    R --> CI[Required CI]
    R -. asynchronous advisory review .-> CR[CodeRabbit]

    CI --> CIP{CI passes on current head?}
    CIP -->|No| F[Fix cause and add or update tests]
    F --> T

    CR --> ARR{Finding arrives<br/>before merge?}
    ARR -->|Yes| TRI[Agent triages substantive finding]
    TRI --> VALID{Finding valid?}
    VALID -->|Yes| F
    VALID -->|No| REPLY[Reply with verified rationale]
    REPLY --> CI
    ARR -->|No, after merge| FOLLOW[Valid finding becomes<br/>a focused follow-up]

    CIP -->|Yes| G{Intent clear, PR ready, and<br/>no needs-human-review label?}
    G -->|No| ESC[Pause for human clarification<br/>or authorization]
    ESC --> U
    G -->|Yes| D[Agent posts concise handoff digest]
    D --> M[Agent squash-merges and deletes branch]
```

## Responsibilities

- **Issue:** Canonical outcome, constraints, non-goals, and acceptance criteria. Material changes agreed in chat must be reflected here.
- **Agent preflight:** Restates intent, the smallest plan, material assumptions, and conditions that would cause a pause.
- **Pull request:** Records the behavior delta, material decisions, verification evidence, CodeRabbit disposition, and limitations.
- **CodeRabbit:** Asynchronously checks the implementation and tests against the issue and PR, then flags drift, omissions, and substantive defects.
- **Human:** Clarifies intent and authorizes consequential actions.

## Merge gates

An agent may squash-merge and delete the branch only when:

1. The requested behavior is covered by the issue and acceptance criteria.
2. No unresolved assumption changes scope or user-visible behavior.
3. Material decisions are disclosed and consequential actions are authorized.
4. `check` succeeds on the current head commit.
5. The PR is not a draft and `needs-human-review` is absent.

CodeRabbit does not control merge eligibility. Findings received before merge are triaged; valid findings received after merge become focused follow-up work.
