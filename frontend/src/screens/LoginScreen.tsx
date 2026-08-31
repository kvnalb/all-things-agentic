import { ArrowRight } from "lucide-react";

export function LoginScreen() {
  return (
    <div className="landing">
      <div className="landing-inner">
        <p className="eyebrow">Your Fall 2026 plan</p>
        <h1>
          Canvas in.
          <br />
          Calendar out.
        </h1>
        <p className="lede">
          StudyAgent watches your courses, ranks what matters, and keeps one Google Calendar current — after you
          review.
        </p>
        <a className="btn btn-primary" href="/api/auth/google/start">
          Continue with Google <ArrowRight size={18} />
        </a>
        <div className="proofs">
          <span className="chip">Your Canvas</span>
          <span className="chip">Ranked work</span>
          <span className="chip">One calendar</span>
        </div>
      </div>
    </div>
  );
}
