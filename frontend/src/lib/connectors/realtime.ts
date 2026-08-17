"use client";

/**
 * The ingestion WebSocket client — `entrypoints/realtime/main.py`'s `/ws/
 * ingestion` contract (`B1` deliverable 3), verbatim: the token travels as a
 * `Sec-WebSocket-Protocol` offer (`["bearer", token]`), never a query
 * parameter, because a query string is the one place a credential ends up
 * in access logs, proxy logs and browser history. The channel is always the
 * caller's own org — this client never asks for one.
 *
 * **No reconnect-with-replay.** A dropped connection here just goes
 * `"closed"`; catching back up on what was missed while disconnected is the
 * consumer-group depth TRACKER's `B1` deliverable 2 note reserves for `B2`.
 * The event bus already durably records everything this socket only relays
 * live.
 */

import { useEffect, useRef, useState } from "react";

import { getAccessToken } from "@/lib/auth/session";

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8001";

/** The one subprotocol value the gateway understands (`realtime/main.py`). */
const BEARER_SUBPROTOCOL = "bearer";

export type IngestJobStatus = "queued" | "running" | "succeeded" | "failed" | "stuck";

export type IngestionEvent = {
  type: "ingest_job";
  job_id: string;
  status: IngestJobStatus;
  kind: string;
  document_id: string | null;
  error_code: string | null;
  error_detail: string | null;
  attempts: number | null;
  max_attempts: number | null;
  done_units: number | null;
  total_units: number | null;
  occurred_at: string;
};

export type ConnectionState = "connecting" | "open" | "closed";

function isIngestionEvent(payload: unknown): payload is IngestionEvent {
  if (typeof payload !== "object" || payload === null) return false;
  const body = payload as Record<string, unknown>;
  return (
    body["type"] === "ingest_job" &&
    typeof body["job_id"] === "string" &&
    (body["status"] === "queued" ||
      body["status"] === "running" ||
      body["status"] === "succeeded" ||
      body["status"] === "failed" ||
      body["status"] === "stuck")
  );
}

/**
 * Subscribes for the lifetime of the calling component and calls `onEvent`
 * once per `ingest_job` transition. A callback rather than a returned array:
 * each transition names the job it belongs to (`job_id`), and a caller
 * wants to fold that into *one row per job* that moves through its states in
 * place, not an ever-appended log — merging is the caller's business, since
 * only the caller knows what a row looks like.
 *
 * `onEvent` is read through a ref and does not need to be memoised — the
 * socket subscribes exactly once per mount regardless of how often the
 * caller re-renders.
 *
 * `connection` is exposed so a denied handshake (closed before the first
 * "subscribed" ack) reads as its own state rather than as a feed that never
 * shows anything.
 */
export function useIngestionFeed(onEvent: (event: IngestionEvent) => void): {
  connection: ConnectionState;
} {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const token = getAccessToken();
    if (token === null) {
      setConnection("closed");
      return;
    }

    setConnection("connecting");
    const socket = new WebSocket(`${WS_BASE_URL}/ws/ingestion`, [BEARER_SUBPROTOCOL, token]);

    socket.addEventListener("open", () => setConnection("open"));
    socket.addEventListener("close", () => setConnection("closed"));
    socket.addEventListener("error", () => setConnection("closed"));
    socket.addEventListener("message", (message: MessageEvent<string>) => {
      let payload: unknown;
      try {
        payload = JSON.parse(message.data);
      } catch {
        return;
      }
      if (isIngestionEvent(payload)) onEventRef.current(payload);
    });

    return () => socket.close();
  }, []);

  return { connection };
}
