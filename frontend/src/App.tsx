import { useMemo, useState } from "react";
import LiveKitViewer from "./components/LiveKitViewer";
import {
  CreateSessionPayload,
  SessionResponse,
  createSession,
  sendText,
  stopSession
} from "./services/heygenApi";

const demoTexts = {
  en: "Hello from the React HeyGen viewer. I am a streaming avatar reading the message you just submitted.",
  fa: "سلام! این یک پیام آزمایشی از برنامه React شماست.",
  zh: "你好，這是一條來自 React 應用程式的測試訊息。"
};

const App = () => {
  const [avatarId, setAvatarId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [demoLang, setDemoLang] = useState<keyof typeof demoTexts>("en");
  const [text, setText] = useState(demoTexts.en);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isTalking, setIsTalking] = useState(false);
  const [isStopping, setIsStopping] = useState(false);

  const sessionReady = Boolean(session?.sessionId);
  const canTalk = sessionReady && text.trim().length > 0 && !isTalking;

  const placeholder = useMemo(
    () => "Leave blank to use language defaults configured in .env",
    []
  );

  const updateStatus = (message: string) => {
    setStatus(message);
    setError(null);
  };

  const handleCreateSession = async () => {
    setIsCreating(true);
    setStatus(null);
    setError(null);

    const payload: CreateSessionPayload = {};
    if (avatarId.trim()) {
      payload.avatar_id = avatarId.trim();
    }
    if (voiceId.trim()) {
      payload.voice_id = voiceId.trim();
    }

    try {
      const data = await createSession(payload);
      setSession(data);
      updateStatus("Session created. Click Connect to join the LiveKit room.");
    } catch (err) {
      console.error(err);
      setError(
        (err as Error).message || "Unable to create session. Check backend logs."
      );
    } finally {
      setIsCreating(false);
    }
  };

  const handleSendText = async () => {
    if (!session) {
      return;
    }
    setIsTalking(true);
    setError(null);
    try {
      await sendText(session.sessionId, text);
      updateStatus("Task submitted to HeyGen.");
    } catch (err) {
      console.error(err);
      setError("Failed to send text to avatar.");
    } finally {
      setIsTalking(false);
    }
  };

  const handleStop = async () => {
    if (!session) {
      return;
    }
    setIsStopping(true);
    try {
      await stopSession(session.sessionId);
      setSession(null);
      updateStatus("Session stopped.");
    } catch (err) {
      console.error(err);
      setError("Unable to stop session.");
    } finally {
      setIsStopping(false);
    }
  };

  const handleLangChange = (lang: keyof typeof demoTexts) => {
    setDemoLang(lang);
    setText(demoTexts[lang]);
  };

  return (
    <div className="app-shell">
      <header>
        <h1>HeyGen + LiveKit React Viewer</h1>
        <p>
          Use the controls below to request a streaming avatar session from your
          FastAPI backend and connect through LiveKit.
        </p>
      </header>

      <div className="card grid">
        <h2>Session Setup</h2>
        <label>
          Avatar ID
          <input
            value={avatarId}
            placeholder={placeholder}
            onChange={(e) => setAvatarId(e.target.value)}
          />
        </label>
        <label>
          Voice ID
          <input
            value={voiceId}
            placeholder={placeholder}
            onChange={(e) => setVoiceId(e.target.value)}
          />
        </label>
        <div className="row">
          <button onClick={handleCreateSession} disabled={isCreating}>
            {isCreating ? "Requesting…" : "Create Session"}
          </button>
          <button
            className="secondary"
            onClick={handleStop}
            disabled={!session || isStopping}
          >
            {isStopping ? "Stopping…" : "Stop Session"}
          </button>
        </div>
        {session && (
          <div className="status-pill success">
            Session ready: {session.sessionId.slice(0, 8)}…
          </div>
        )}
      </div>

      <LiveKitViewer
        livekitUrl={session?.livekitUrl}
        accessToken={session?.accessToken}
        disabled={!session}
      />

      <div className="card grid">
        <h2>Send Text To Avatar</h2>
        <label>
          Demo text preset
          <select
            value={demoLang}
            onChange={(e) => handleLangChange(e.target.value as "en" | "fa" | "zh")}
          >
            <option value="en">English</option>
            <option value="fa">Persian</option>
            <option value="zh">Chinese</option>
          </select>
        </label>
        <textarea value={text} onChange={(e) => setText(e.target.value)} />
        <button onClick={handleSendText} disabled={!canTalk}>
          {isTalking ? "Sending…" : "Send Text"}
        </button>
      </div>

      {(status || error) && (
        <div
          className={`status-pill ${error ? "error" : "success"}`}
          aria-live="polite"
        >
          {error || status}
        </div>
      )}
    </div>
  );
};

export default App;
