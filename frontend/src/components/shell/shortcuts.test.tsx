import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useInspectorSelection } from "@/lib/inspector/SelectionProvider";
import type { Citation } from "@/lib/knowledge/api";
import { setMediaQueries } from "@/test/harness";
import { jsonResponse, stubRouter } from "@/test/http";
import { navigation } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";

import { AppShell } from "./AppShell";
import { INSPECTOR_INLINE, SIDEBAR_INLINE } from "./useMediaQuery";

const CITATIONS: Citation[] = [1, 2, 3].map((marker) => ({
  id: `c${marker}`, message_id: "m1", marker, document_id: null, chunk_id: null,
  quoted_text: `Passage number ${marker}.`, start_char: null, end_char: null, page_number: marker, score: null,
}));

/** A page that can put an answer in the inspector, as a chat page would. */
function Page() {
  const { select } = useInspectorSelection();
  return (
    <>
      <button type="button" onClick={() => select({ kind: "message", message: { id: "m1", content: "x", citations: CITATIONS } })}>
        Select the answer
      </button>
      <label>
        Notes
        <input />
      </label>
    </>
  );
}

beforeEach(() => {
  setMediaQueries({ [INSPECTOR_INLINE]: true, [SIDEBAR_INLINE]: true });
  stubRouter((call) => {
    if (call.path.endsWith("/chat/sessions") && call.method === "POST") {
      return jsonResponse(201, { id: "new-session", title: "New conversation", folder_id: null, is_archived: false, created_at: "2026-10-22T10:00:00Z", updated_at: "2026-10-22T10:00:00Z", last_message_at: null });
    }
    if (call.path.endsWith("/chat/sessions")) return jsonResponse(200, { sessions: [], next_cursor: null });
    return jsonResponse(200, { status: "ready", checks: { postgres: "ok" } });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderShell() {
  return renderWithProviders(
    <AppShell>
      <Page />
    </AppShell>,
  );
}

describe("keyboard shortcuts", () => {
  it("test_n_starts_a_conversation_but_not_while_typing", async () => {
    renderShell();

    await userEvent.type(screen.getByRole("textbox", { name: "Notes" }), "n");
    expect(navigation.push).not.toHaveBeenCalled();

    await userEvent.click(document.body);
    await userEvent.keyboard("n");
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/chat/new-session"));
  });

  it("test_brackets_step_through_the_selected_answers_sources", async () => {
    renderShell();
    await userEvent.click(screen.getByRole("button", { name: "Select the answer" }));
    await userEvent.click(document.body);

    await userEvent.keyboard("]");
    expect(await screen.findByText("Source 1 of 3")).toBeInTheDocument();
    await userEvent.keyboard("]");
    expect(screen.getByText("Source 2 of 3")).toBeInTheDocument();
    // `[[` is user-event's escape for a literal "[" key.
    await userEvent.keyboard("[[");
    expect(screen.getByText("Source 1 of 3")).toBeInTheDocument();
  });

  it("test_escape_clears_the_selection_and_i_toggles_the_inspector", async () => {
    renderShell();
    await userEvent.click(screen.getByRole("button", { name: "Select the answer" }));
    await userEvent.click(document.body);
    expect(screen.getByText("Evidence for this answer")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Expand context inspector" })).toBeInTheDocument();

    await userEvent.keyboard("i");
    expect(screen.getByRole("complementary", { name: "Context inspector" })).toHaveClass("w-0");
    await userEvent.keyboard("i");
    expect(screen.getByRole("button", { name: "Expand context inspector" })).toBeInTheDocument();
  });

  it("test_question_mark_lists_every_shortcut", async () => {
    renderShell();
    await userEvent.click(document.body);
    await userEvent.keyboard("?");

    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(dialog).toHaveTextContent("Start a new conversation");
    expect(dialog).toHaveTextContent("Open the command palette");
  });

  it("test_the_palette_filters_and_runs_with_the_keyboard", async () => {
    renderShell();
    await userEvent.keyboard("{Control>}k{/Control}");

    const input = screen.getByRole("combobox", { name: "Go to or do" });
    expect(input).toHaveFocus();
    await userEvent.type(input, "go know");

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("Go to Knowledge");
    expect(input).toHaveAttribute("aria-activedescendant", options[0]?.id);

    await userEvent.keyboard("{Enter}");
    expect(navigation.push).toHaveBeenCalledWith("/knowledge");
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
