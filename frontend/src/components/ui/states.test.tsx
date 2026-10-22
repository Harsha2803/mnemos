import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import BookmarksPage from "@/app/(app)/bookmarks/page";
import KnowledgePage from "@/app/(app)/knowledge/page";
import { ChatSessionList } from "@/components/chat/ChatSessionList";
import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

const FAILURE = { error: { code: "internal", message: "internal error" } };

/**
 * A list whose request failed must say so. Rendering its empty state instead
 * ("No documents yet") would tell the reader something false — that the list
 * is empty — which is the confusion DesignSystem §4's empty-state rule exists
 * to prevent in the first place.
 */
describe("a failed load is never an empty state", () => {
  it("test_knowledge_says_the_documents_could_not_be_loaded_and_retries", async () => {
    let calls = 0;
    stubRouter((call) => {
      if (call.path.endsWith("/knowledge/documents")) {
        calls += 1;
        return calls <= 2 ? jsonResponse(500, FAILURE) : jsonResponse(200, []);
      }
      return jsonResponse(404, {});
    });
    renderWithProviders(<KnowledgePage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Your documents could not be loaded");
    expect(screen.queryByText("No documents yet")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
  });

  it("test_bookmarks_say_they_could_not_be_loaded", async () => {
    stubRouter(() => jsonResponse(500, FAILURE));
    renderWithProviders(<BookmarksPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Your bookmarks could not be loaded");
    expect(screen.queryByText("No bookmarks yet")).toBeNull();
  });

  it("test_the_sidebar_says_conversations_could_not_be_loaded", async () => {
    stubRouter(() => jsonResponse(500, FAILURE));
    renderWithProviders(<ChatSessionList />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Conversations could not be loaded");
    expect(screen.queryByText("No conversations yet")).toBeNull();
  });
});
