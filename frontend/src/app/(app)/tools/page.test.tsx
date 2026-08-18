import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetSessionForTests, setAccessToken } from "@/lib/auth/session";
import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import ToolsPage from "./page";

const SERVERS = "/api/v1/tools/servers";
const TOOLS = "/api/v1/tools";
const INVOCATIONS = "/api/v1/tools/invocations";

function invocation(overrides: Record<string, unknown> = {}) {
  return {
    id: "019fe000-0000-7000-8000-000000000010",
    tool_id: "019fe000-0000-7000-8000-000000000011",
    user_id: "019fe000-0000-7000-8000-000000000012",
    arguments: { message: "hello" },
    status: "pending_approval",
    caller_trust_tier: 20,
    denied_reason: null,
    offending_source: null,
    approved_by: null,
    approved_at: null,
    result: {},
    duration_ms: null,
    error_code: null,
    created_at: "2026-08-18T12:00:00Z",
    ...overrides,
  };
}

beforeEach(() => setAccessToken("tool-test-token"));
afterEach(() => {
  resetSessionForTests();
  vi.unstubAllGlobals();
});

describe("the Tool console", () => {
  it("test_a_pending_call_can_be_approved_and_its_result_is_shown", async () => {
    let state = invocation();
    stubRouter((call) => {
      if (call.method === "GET" && call.path === SERVERS) return jsonResponse(200, []);
      if (call.method === "GET" && call.path === TOOLS) return jsonResponse(200, []);
      if (call.method === "GET" && call.path === INVOCATIONS) return jsonResponse(200, [state]);
      if (call.method === "POST" && call.path.endsWith("/approve")) {
        state = invocation({
          status: "succeeded",
          approved_by: "019fe000-0000-7000-8000-000000000012",
          approved_at: "2026-08-18T12:01:00Z",
          result: { structuredContent: { echo: "hello" } },
        });
        return jsonResponse(200, state);
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ToolsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve and run" }));

    expect(await screen.findByText("Invocation succeeded.")).toBeInTheDocument();
    expect(await screen.findByText(/structuredContent/)).toBeInTheDocument();
  });

  it("test_a_trust_denial_names_the_offending_retrieved_source", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === SERVERS) return jsonResponse(200, []);
      if (call.method === "GET" && call.path === TOOLS) return jsonResponse(200, []);
      if (call.method === "GET" && call.path === INVOCATIONS) {
        return jsonResponse(200, [
          invocation({
            status: "denied",
            caller_trust_tier: 10,
            denied_reason: "trust_tier_insufficient",
            offending_source: "Employee Handbook 2024",
          }),
        ]);
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ToolsPage />);

    expect(
      await screen.findByText(/retrieved source “Employee Handbook 2024”/i),
    ).toBeInTheDocument();
  });
});

