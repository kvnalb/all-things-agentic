import { ArrowRight, CalendarDays, Circle } from "lucide-react";

const steps = ["Google", "Canvas", "Ed", "Course sources", "First import"];

export default function App() {
  return (
    <main className="shell">
      <aside className="signal-rail" aria-label="Setup progress">
        <div className="wordmark">StudyAgent</div>
        <div className="rail-copy">
          <p className="eyebrow">Fall 2026 setup</p>
          <h1>Build a semester you can trust.</h1>
          <p className="lede">
            Bring scattered course sources into one calendar, with every event
            linked back to where it came from.
          </p>
        </div>
        <ol className="steps">
          {steps.map((step, index) => (
            <li className={index === 0 ? "active" : ""} key={step}>
              <span className="step-node"><Circle size={10} fill="currentColor" /></span>
              <span className="step-number">0{index + 1}</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </aside>

      <section className="workspace">
        <header className="workspace-header">
          <span className="status-chip">Not connected</span>
          <span className="utility">About 4 minutes</span>
        </header>
        <div className="setup-card">
          <div className="icon-tile"><CalendarDays size={28} /></div>
          <p className="eyebrow">Step 1 of 5</p>
          <h2>Start with your calendar</h2>
          <p>
            Connect the Google account that should own your private StudyAgent
            calendar. Your primary calendar stays untouched.
          </p>
          <button type="button" disabled>
            Connect Google <ArrowRight size={18} />
          </button>
          <p className="footnote">Connector implementation follows in issue #13.</p>
        </div>
      </section>
    </main>
  );
}
