import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";
import { resetSessionForTests, setAccessToken } from "@/lib/auth/session";

import SourcesPage from "./page";

const SOURCES_PATH = "/api/v1/connectors";
const JOBS_PATH = "/api/v1/connectors/jobs";

function aSource(overrides: Record<string, unknown> = {}) {
  return {
    id: "019fe000-0000-7000-8000-00000000000a",
    slug: "fixtures",
    name: "Fixtures",
    kind: "local_fs",
    is_enabled: true,
    created_at: "2026-08-16T12:00:00Z",
    ...overrides,
  };
}

function anItem(overrides: Record<string, unknown> = {}) {
  return {
    uri: "handbook.txt",
    name: "handbook.txt",
    size_bytes: 128,
    content_type: "text/plain",
    modified_at: null,
    ...overrides,
  };
}

function aJob(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    kind: "connector_ingest",
    status: "running",
    payload: { item_name: "handbook.txt", item_uri: "handbook.txt" },
    document_id: null,
    attempts: 1,
    max_attempts: 3,
    done_units: 2,
    total_units: 4,
    owner_id: "worker:1",
    heartbeat_at: "2026-08-16T12:04:00Z",
    lease_expires_at: "2026-08-16T12:05:00Z",
    started_at: "2026-08-16T12:03:00Z",
    finished_at: null,
    error_code: null,
    error_detail: null,
    created_at: "2026-08-16T12:02:00Z",
    updated_at: "2026-08-16T12:04:00Z",
    events: [],
    ...overrides,
  };
}

/**
 * A minimal `WebSocket` double: records what it was constructed with,
 * accepts listeners, and lets the test dispatch a server message by hand.
 * `useIngestionFeed` only ever calls `addEventListener` and `close`, so
 * that is all this needs to implement.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  protocols: string[];
  listeners: Record<string, ((event: unknown) => void)[]> = {};
  closed = false;

  constructor(url: string, protocols: string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: (event: unknown) => void): void {
    (this.listeners[type] ??= []).push(listener);
  }

  close(): void {
    this.closed = true;
    for (const listener of this.listeners["close"] ?? []) listener({});
  }

  emitOpen(): void {
    for (const listener of this.listeners["open"] ?? []) listener({});
  }

  emitMessage(data: unknown): void {
    for (const listener of this.listeners["message"] ?? []) {
      listener({ data: JSON.stringify(data) });
    }
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  setAccessToken("a-test-access-token");
});

afterEach(() => {
  resetSessionForTests();
  vi.unstubAllGlobals();
});

describe("the sources screen", () => {
  it("test_registering_a_local_fs_source_adds_it_to_the_list", async () => {
    let registered = false;
    stubRouter((call) => {
      if (call.method === "GET" && call.path === SOURCES_PATH) {
        return jsonResponse(200, registered ? [aSource()] : []);
      }
      if (call.method === "GET" && call.path === JOBS_PATH) {
        return jsonResponse(200, []);
      }
      if (call.method === "POST" && call.path === SOURCES_PATH) {
        registered = true;
        return jsonResponse(201, aSource());
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<SourcesPage />);

    await screen.findByText("No sources registered yet");

    await userEvent.type(screen.getByLabelText("Name"), "Fixtures");
    await userEvent.type(screen.getByLabelText("Slug"), "fixtures");
    await userEvent.type(screen.getByLabelText("Root directory"), "/fixtures/sources");
    await userEvent.click(screen.getByRole("button", { name: "Register source" }));

    await waitFor(() =>
      expect(screen.getByRole("list", { name: "Sources" })).toHaveTextContent("Fixtures"),
    );
  });

  it("test_ingesting_a_selected_item_shows_queued_then_updates_live_over_the_socket", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === SOURCES_PATH) {
        return jsonResponse(200, [aSource()]);
      }
      if (call.method === "GET" && call.path === JOBS_PATH) {
        return jsonResponse(200, []);
      }
      if (call.method === "GET" && call.path === `${SOURCES_PATH}/fixtures/items`) {
        return jsonResponse(200, [anItem()]);
      }
      if (call.method === "POST" && call.path === `${SOURCES_PATH}/fixtures/ingest`) {
        return jsonResponse(202, { job_id: "job-1", status: "queued", uri: "handbook.txt" });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<SourcesPage />);

    await userEvent.click(await screen.findByRole("button", { name: /Fixtures/ }));
    await userEvent.click(await screen.findByLabelText("Select handbook.txt"));
    await userEvent.click(screen.getByRole("button", { name: /Ingest 1/ }));

    // Optimistic: the UI's own "ingest requested" state, before any socket
    // message arrives (TRACKER §5 deliverable 4 recap — `queued` is never
    // itself published).
    const feed = await screen.findByRole("list", { name: "Ingestion activity" });
    await waitFor(() => expect(feed).toHaveTextContent("Queued"));
    expect(feed).toHaveTextContent("handbook.txt");

    const socket = FakeWebSocket.instances.at(-1);
    expect(socket).toBeDefined();
    expect(socket?.protocols).toEqual(["bearer", "a-test-access-token"]);
    socket?.emitOpen();
    socket?.emitMessage({
      type: "ingest_job",
      job_id: "job-1",
      status: "succeeded",
      kind: "connector_ingest",
      document_id: "019fe000-0000-7000-8000-00000000000b",
      error_code: null,
      error_detail: null,
      attempts: 1,
      max_attempts: 3,
      done_units: 4,
      total_units: 4,
      occurred_at: "2026-08-16T12:05:00Z",
    });

    // Same row, updated in place — not a second entry for the same job.
    await waitFor(() => expect(feed).toHaveTextContent("Succeeded"));
    expect(screen.getAllByText("handbook.txt").length).toBeGreaterThan(0);
    expect(feed.textContent).not.toContain("Queued");
  });

  it("test_recent_jobs_are_loaded_with_progress_after_a_reload", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === SOURCES_PATH) {
        return jsonResponse(200, [aSource()]);
      }
      if (call.method === "GET" && call.path === JOBS_PATH) {
        return jsonResponse(200, [aJob()]);
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<SourcesPage />);

    const feed = await screen.findByRole("list", { name: "Ingestion activity" });
    expect(feed).toHaveTextContent("handbook.txt");
    expect(feed).toHaveTextContent("Running");
    expect(feed).toHaveTextContent("Attempt 1/3");
    expect(feed).toHaveTextContent("50%");
    expect(screen.getByRole("progressbar", { name: "handbook.txt progress" })).toHaveAttribute(
      "aria-valuenow",
      "50",
    );
  });
});
