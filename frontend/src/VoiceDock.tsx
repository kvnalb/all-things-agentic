import { Mic } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: Array<{ isFinal: boolean; 0: { transcript: string } }>;
};

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type WindowWithSpeech = Window & {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
};

const STATE_LABEL: Record<"idle" | "listening" | "thinking", string> = {
  idle: "Ready",
  listening: "Listening",
  thinking: "Thinking",
};

const SPEECH_CHUNK_CHARS = 280;

function chunkSpeechText(text: string): string[] {
  const normalized = text.trim().replace(/\s+/g, " ");
  if (!normalized) return [];
  if (normalized.length <= SPEECH_CHUNK_CHARS) return [normalized];

  const sentences = normalized.match(/[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$/g) || [normalized];
  const chunks: string[] = [];
  let current = "";

  const pushCurrent = () => {
    const trimmed = current.trim();
    if (trimmed) chunks.push(trimmed);
    current = "";
  };

  const pushWords = (value: string) => {
    let wordChunk = "";
    for (const word of value.split(" ")) {
      const next = wordChunk ? `${wordChunk} ${word}` : word;
      if (next.length > SPEECH_CHUNK_CHARS) {
        if (wordChunk) chunks.push(wordChunk);
        wordChunk = word;
      } else {
        wordChunk = next;
      }
    }
    if (wordChunk) current = wordChunk;
  };

  for (const sentence of sentences) {
    const part = sentence.trim();
    if (!part) continue;
    if (part.length > SPEECH_CHUNK_CHARS) {
      pushCurrent();
      pushWords(part);
      continue;
    }
    const combined = current ? `${current} ${part}` : part;
    if (combined.length > SPEECH_CHUNK_CHARS) {
      pushCurrent();
      current = part;
    } else {
      current = combined;
    }
  }
  pushCurrent();
  return chunks.length ? chunks : [normalized];
}

export function VoiceDock({ api }: { api: (path: string, options?: RequestInit) => Promise<unknown> }) {
  const [state, setState] = useState<"idle" | "listening" | "thinking">("idle");
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("");
  const recogRef = useRef<SpeechRecognitionLike | null>(null);
  const copyRef = useRef<HTMLDivElement | null>(null);

  const win = window as WindowWithSpeech;
  const SR = win.SpeechRecognition || win.webkitSpeechRecognition;
  const supported = Boolean(SR);

  useEffect(() => {
    const warm = () => window.speechSynthesis.getVoices();
    warm();
    window.speechSynthesis.onvoiceschanged = warm;
    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, []);

  useEffect(() => {
    const copy = copyRef.current;
    if (!copy) return;
    copy.scrollTop = 0;
  }, [reply, heard, state]);

  const pickVoice = () => {
    const voices = window.speechSynthesis.getVoices() || [];
    const prefs = [
      "Ava (Premium)",
      "Samantha (Enhanced)",
      "Ava",
      "Samantha",
      "Google US English",
      "Microsoft Aria Online (Natural) - English (United States)",
    ];
    for (const wanted of prefs) {
      const hit = voices.find((v) => v.name === wanted);
      if (hit) return hit;
    }
    const english = voices.filter((v) => v.lang?.startsWith("en"));
    return english.find((v) => !/compact/i.test(v.voiceURI || "")) || english[0] || null;
  };

  const speak = (text: string) => {
    try {
      const chunks = chunkSpeechText(text);
      if (!chunks.length) return;
      window.speechSynthesis.cancel();
      const voice = pickVoice();
      let index = 0;

      const speakNext = () => {
        if (index >= chunks.length) return;
        const utterance = new SpeechSynthesisUtterance(chunks[index]);
        if (voice) utterance.voice = voice;
        const advance = () => {
          index += 1;
          window.setTimeout(speakNext, 40);
        };
        utterance.onend = advance;
        utterance.onerror = advance;
        window.speechSynthesis.speak(utterance);
      };

      speakNext();
    } catch {
      /* text still visible */
    }
  };

  const send = async (question: string) => {
    setState("thinking");
    try {
      const result = (await api("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      })) as { answer?: string };
      const answer = result.answer || "";
      setReply(answer);
      setState("idle");
      speak(answer);
    } catch {
      setReply("I couldn't reach the agent.");
      setState("idle");
    }
  };

  const listen = () => {
    if (state === "listening") {
      recogRef.current?.stop();
      return;
    }
    if (!supported || !SR) return;
    window.speechSynthesis.cancel();
    const recognition = new SR();
    recogRef.current = recognition;
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    let finalText = "";
    recognition.onstart = () => {
      setState("listening");
      setHeard("");
      setReply("");
    };
    recognition.onresult = (event: SpeechRecognitionEventLike) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += text;
        else interim += text;
      }
      setHeard(finalText || interim);
    };
    recognition.onerror = () => {
      setState("idle");
      setReply("I didn't catch that.");
    };
    recognition.onend = () => {
      const question = finalText.trim();
      if (question) void send(question);
      else setState("idle");
    };
    recognition.start();
  };

  const hint =
    state === "listening" ? "Listening — tap to stop" : state === "thinking" ? "Working on your question…" : "Tap and ask about your work";

  return (
    <div className="voice-dock" aria-live="polite">
      <section className="glass voice-panel">
        <header className="voice-head">
          <p className="eyebrow">Study assistant</p>
          <span className={`voice-state ${state}`}>{STATE_LABEL[state]}</span>
        </header>
        <div className="voice-row">
          <button
            type="button"
            className={`voice-mic ${state}`}
            onClick={listen}
            disabled={!supported || state === "thinking"}
            aria-label={state === "listening" ? "Stop listening" : "Ask a question"}
          >
            <Mic size={20} strokeWidth={2.25} />
          </button>
          <div className="voice-copy" ref={copyRef}>
            {!supported ? (
              <p className="lede tight">Voice needs Chrome or Edge. Everything else works here.</p>
            ) : reply ? (
              <>
                {heard && (
                  <>
                    <p className="eyebrow">You asked</p>
                    <p className="voice-you">{heard}</p>
                  </>
                )}
                <p className="voice-reply">{reply}</p>
              </>
            ) : heard ? (
              <p className="voice-live">{heard}</p>
            ) : (
              <p className="lede tight">{hint}</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
