import { act, createElement, useSyncExternalStore } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getServerSessionSnapshot,
  getSessionSnapshot,
  resetSessionForTests,
  subscribeToSession,
} from "./session";

function SessionStatus() {
  const snapshot = useSyncExternalStore(
    subscribeToSession,
    getSessionSnapshot,
    getServerSessionSnapshot,
  );
  return createElement("p", null, snapshot.status);
}

afterEach(() => {
  resetSessionForTests();
  vi.restoreAllMocks();
});

describe("the session store's server snapshot", () => {
  it("test_the_server_snapshot_is_the_same_object_on_every_call", () => {
    // React compares snapshots by identity. A new object per call is a
    // snapshot that "changed" on every read.
    expect(getServerSessionSnapshot()).toBe(getServerSessionSnapshot());
    expect(getServerSessionSnapshot()).toEqual({ status: "unknown", identity: null });
  });

  it("test_hydrating_a_session_reader_logs_no_uncached_snapshot_error", async () => {
    // The defect as a person saw it: every page's dev console said "The result
    // of getServerSnapshot should be cached to avoid an infinite loop". That
    // message is raised during hydration, so hydration is what this runs.
    const container = document.createElement("div");
    container.innerHTML = renderToString(createElement(SessionStatus));
    document.body.appendChild(container);
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});

    await act(async () => {
      hydrateRoot(container, createElement(SessionStatus));
    });

    const messages = errors.mock.calls.map((call) => String(call[0]));
    expect(messages.filter((message) => message.includes("getServerSnapshot"))).toEqual([]);
    container.remove();
  });
});
