import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { resetNavigation } from "@/test/navigation";
import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import { ChatSessionList } from "./ChatSessionList";

const SESSIONS_PATH = "/api/v1/chat/sessions";
const FOLDERS_PATH = "/api/v1/chat/folders";

function aSession(overrides: Record<string, unknown> = {}) {
  return {
    id: "019fe000-0000-7000-8000-00000000000a",
    title: "New chat",
    is_archived: false,
    folder_id: null,
    last_message_at: "2026-08-16T12:00:00Z",
    created_at: "2026-08-16T12:00:00Z",
    updated_at: "2026-08-16T12:00:00Z",
    ...overrides,
  };
}

describe("searching conversations", () => {
  it("test_typing_a_query_calls_the_search_endpoint_and_shows_a_snippet", async () => {
    resetNavigation();
    const router = stubRouter((call) => {
      if (call.method === "GET" && call.path === FOLDERS_PATH) {
        return jsonResponse(200, { folders: [] });
      }
      if (call.method === "GET" && call.path === SESSIONS_PATH) {
        const q = call.url.searchParams.get("q");
        if (q === "leave policy") {
          return jsonResponse(200, {
            sessions: [
              aSession({
                id: "019fe000-0000-7000-8000-00000000000b",
                title: "New chat",
                snippet: "Carry-over of unused leave is capped at five days.",
              }),
            ],
            next_cursor: null,
          });
        }
        return jsonResponse(200, { sessions: [aSession()], next_cursor: null });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ChatSessionList />);
    await screen.findByRole("link", { name: "New chat" });

    await userEvent.type(
      screen.getByPlaceholderText("Search conversations"),
      "leave policy",
    );

    await waitFor(() =>
      expect(
        router.calls.some(
          (call) => call.path === SESSIONS_PATH && call.url.searchParams.get("q") === "leave policy",
        ),
      ).toBe(true),
    );
    expect(
      await screen.findByText("Carry-over of unused leave is capped at five days."),
    ).toBeInTheDocument();
  });

  it("test_a_search_with_no_matches_says_so", async () => {
    resetNavigation();
    stubRouter((call) => {
      if (call.method === "GET" && call.path === FOLDERS_PATH) {
        return jsonResponse(200, { folders: [] });
      }
      if (call.method === "GET" && call.path === SESSIONS_PATH) {
        const q = call.url.searchParams.get("q");
        if (q !== null) return jsonResponse(200, { sessions: [], next_cursor: null });
        return jsonResponse(200, { sessions: [aSession()], next_cursor: null });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ChatSessionList />);
    await screen.findByRole("link", { name: "New chat" });

    await userEvent.type(screen.getByPlaceholderText("Search conversations"), "nonexistent");

    expect(await screen.findByText("No conversations match.")).toBeInTheDocument();
  });
});
