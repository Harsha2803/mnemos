import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import AuditPage from "./page";

const EVENTS_PATH = "/api/v1/audit/events";

function anEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "019fe000-0000-7000-8000-00000000000a",
    actor_id: "019fe000-0000-7000-8000-00000000000b",
    actor_kind: "user",
    action: "auth.sign_in",
    resource_kind: "session",
    resource_id: null,
    outcome: "allow",
    reason: null,
    request_id: null,
    ip_address: null,
    user_agent: null,
    occurred_at: "2026-08-22T12:00:00Z",
    ...overrides,
  };
}

describe("the audit log page", () => {
  it("test_an_admin_sees_the_events_table", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === EVENTS_PATH) {
        return jsonResponse(200, { events: [anEvent()], next_cursor: null });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<AuditPage />);

    expect(await screen.findByRole("cell", { name: "auth.sign_in" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Outcome" })).toBeInTheDocument();
  });

  it("test_a_403_shows_the_specific_admin_only_message_not_a_generic_error", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === EVENTS_PATH) {
        return jsonResponse(403, {
          error: { code: "forbidden", message: "you are not allowed to perform this action" },
        });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<AuditPage />);

    // `retry: 1` (the app's real QueryClient config, deliberately reused
    // here rather than a test-only one) means one retry's backoff delay
    // passes before the error settles.
    expect(
      await screen.findByText(
        "Only administrators can view the audit log",
        {},
        { timeout: 3000 },
      ),
    ).toBeInTheDocument();
  });

  it("test_no_events_shows_the_empty_state_not_a_blank_table", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === EVENTS_PATH) {
        return jsonResponse(200, { events: [], next_cursor: null });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<AuditPage />);

    expect(await screen.findByText("No matching events")).toBeInTheDocument();
  });

  it("test_typing_an_action_filter_refetches_with_it", async () => {
    const router = stubRouter((call) => {
      if (call.method === "GET" && call.path === EVENTS_PATH) {
        return jsonResponse(200, { events: [anEvent()], next_cursor: null });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<AuditPage />);
    await screen.findByRole("cell", { name: "auth.sign_in" });

    await userEvent.type(screen.getByLabelText("Action"), "tool.invoke");

    await waitFor(() =>
      expect(
        router.calls.some(
          (call) =>
            call.path === EVENTS_PATH && call.url.searchParams.get("action") === "tool.invoke",
        ),
      ).toBe(true),
    );
  });
});
