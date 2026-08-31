import { useCallback, useEffect, useState } from "react";
import OnboardingWizard from "./OnboardingWizard";
import TodayBoard from "./TodayBoard";

type Status = {
  google_connected: boolean;
  onboarding_complete?: boolean;
  last_run?: { state: string; completed_at?: string };
};

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [onboardingDone, setOnboardingDone] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastRun, setLastRun] = useState<string | undefined>();

  const api = useCallback(async (path: string, options?: RequestInit) => {
    const response = await fetch(path, options);
    if (response.status === 401) {
      setAuthed(false);
      throw new Error("Connect Google to continue");
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
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const status = (await api("/api/status")) as Status;
        setAuthed(status.google_connected);
        setOnboardingDone(Boolean(status.onboarding_complete));
        if (status.last_run?.completed_at) {
          setLastRun(new Date(status.last_run.completed_at).toLocaleString());
        }
      } catch {
        setAuthed(false);
        setOnboardingDone(false);
      }
    })();
  }, [api]);

  async function syncNow() {
    setBusy(true);
    try {
      await api("/api/sync", { method: "POST" });
      const status = (await api("/api/status")) as Status;
      if (status.last_run?.completed_at) {
        setLastRun(new Date(status.last_run.completed_at).toLocaleString());
      }
    } finally {
      setBusy(false);
    }
  }

  if (authed === null || onboardingDone === null) {
    return (
      <div className="wrap">
        <div className="masthead">
          <p className="eyebrow">Taskmaster</p>
          <h1 className="today">Loading</h1>
        </div>
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="wrap">
        <div className="masthead">
          <p className="eyebrow">Taskmaster · Fall 2026</p>
          <h1 className="today">Connect to begin</h1>
          <p className="load">Sign in with Google to load your semester board and voice assistant.</p>
          <p style={{ marginTop: 24 }}>
            <a className="cal-btn" href="/api/auth/google/start" style={{ textDecoration: "none", display: "inline-block" }}>
              Connect Google
            </a>
          </p>
        </div>
      </div>
    );
  }

  if (!onboardingDone) {
    return (
      <OnboardingWizard
        api={api}
        onComplete={() => {
          setOnboardingDone(true);
        }}
      />
    );
  }

  return <TodayBoard api={api} onSync={syncNow} busy={busy} lastRun={lastRun} />;
}
