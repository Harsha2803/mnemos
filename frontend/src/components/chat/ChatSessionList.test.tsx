import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { navigation, resetNavigation, visit } from "@/test/navigation";
import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import { ChatSessionList } from "./ChatSessionList";

const SESSIONS_PATH = "/api/v1/chat/sessions";

function aSession(overrides: Record<string, unknown> = {}) {
  return {
    id: "019fe000-0000-7000-8000-00000000000a",
    title: "What is the capital of France?",
    is_archived: false,
    folder_id: null,
    last_message_at: "2026-08-16T12:00:00Z",
    created_at: "2026-08-16T12:00:00Z",
    updated_at: "2026-08-16T12:00:00Z",
    ...overrides,
  };
}

const FOLDERS_PATH = "/api/v1/chat/folders";

beforeEach(() => {
  resetNavigation();
});

describe("the conversation list", () => {
  it("test_a_conversation_shows_its_backend_assigned_title", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === FOLDERS_PATH) {
        return jsonResponse(200, { folders: [] });
      }
      if (call.method === "GET" && call.path === SESSIONS_PATH) {
        return jsonResponse(200, { sessions: [aSession()], next_cursor: null });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ChatSessionList />);

    expect(
      await screen.findByRole("link", { name: "What is the capital of France?" }),
    ).toBeInTheDocument();
  });

  it("test_renaming_a_conversation_sends_the_new_title_and_shows_it", async () => {
    let title = aSession().title;
    const router = stubRouter((call) => {
      if (call.method === "GET" && call.path === FOLDERS_PATH) {
        return jsonResponse(200, { folders: [] });
      }
      if (call.method === "GET" && call.path === SESSIONS_PATH) {
        return jsonResponse(200, { sessions: [aSession({ title })], next_cursor: null });
      }
      if (call.method === "PATCH" && call.path === `${SESSIONS_PATH}/${aSession().id}`) {
        title = "Renamed conversation";
        return jsonResponse(200, aSession({ title }));
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ChatSessionList />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Rename What is the capital of France?" }),
    );

    const field = screen.getByRole("textbox", { name: "Conversation name" });
    await userEvent.clear(field);
    await userEvent.type(field, "Renamed conversation{Enter}");

    await waitFor(() => expect(router.countOf(`${SESSIONS_PATH}/${aSession().id}`)).toBe(1));
    expect(
      await screen.findByRole("link", { name: "Renamed conversation" }),
    ).toBeInTheDocument();
  });

  it("test_escape_cancels_a_rename_without_sending_anything", async () => {
    const router = stubRouter((call) => {
      if (call.method === "GET" && call.path === FOLDERS_PATH) {
        return jsonResponse(200, { folders: [] });
      }
      if (call.method === "GET" && call.path === SESSIONS_PATH) {
        return jsonResponse(200, { sessions: [aSession()], next_cursor: null });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ChatSessionList />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Rename What is the capital of France?" }),
    );
    const field = screen.getByRole("textbox", { name: "Conversation name" });
    await userEvent.type(field, " — never mind{Escape}");

    expect(
      await screen.findByRole("link", { name: "What is the capital of France?" }),
    ).toBeInTheDocument();
    expect(router.countOf(`${SESSIONS_PATH}/${aSession().id}`)).toBe(0);
  });

  it("test_deleting_a_conversation_names_it_in_the_confirmation", async () => {
    const router = stubRouter((call) => {
      if (call.method === "GET" && call.path === FOLDERS_PATH) {
        return jsonResponse(200, { folders: [] });
      }
      if (call.method === "GET" && call.path === SESSIONS_PATH) {
        return jsonResponse(200, { sessions: [aSession()], next_cursor: null });
      }
      if (call.method === "DELETE") return new Response(null, { status: 204 });
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ChatSessionList />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete What is the capital of France?" }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Delete “What is the capital of France?”?");

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(router.countOf(`${SESSIONS_PATH}/${aSession().id}`)).toBe(1));
  });

  it("test_deleting_the_open_conversation_navigates_away_from_it", async () => {
    visit(`/chat/${aSession().id}`);
    stubRouter((call) => {
      if (call.method === "GET" && call.path === FOLDERS_PATH) {
        return jsonResponse(200, { folders: [] });
      }
      if (call.method === "GET" && call.path === SESSIONS_PATH) {
        return jsonResponse(200, { sessions: [aSession()], next_cursor: null });
      }
      if (call.method === "DELETE") return new Response(null, { status: 204 });
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<ChatSessionList />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete What is the capital of France?" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/chat"));
  });
});
