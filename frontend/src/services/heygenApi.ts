import axios from "axios";

export interface CreateSessionPayload {
  avatar_id?: string;
  voice_id?: string;
}

export interface SessionResponse {
  sessionId: string;
  livekitUrl: string;
  accessToken: string;
}

const api = axios.create({
  baseURL: "/api/avatar",
  headers: {
    "Content-Type": "application/json"
  }
});

export async function createSession(
  payload: CreateSessionPayload
): Promise<SessionResponse> {
  const { data } = await api.post("/session", payload);
  return {
    sessionId: data.session_id,
    livekitUrl: data.livekit_url,
    accessToken: data.access_token
  };
}

export async function sendText(sessionId: string, text: string) {
  return api.post("/talk", {
    session_id: sessionId,
    text
  });
}

export async function stopSession(sessionId: string) {
  return api.post("/stop", { session_id: sessionId });
}
