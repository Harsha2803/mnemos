import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/render";

import { MessageList } from "./MessageList";
import type { DisplayMessage } from "./MessageBubble";

const MESSAGE: DisplayMessage = {
  id: "msg-1",
  role: "assistant",
  content: "Paris is the capital of France.",
};

describe("bookmarking a message", () => {
  it("test_the_bookmark_button_reports_which_message_was_toggled", async () => {
    const onToggleBookmark = vi.fn();
    renderWithProviders(
      <MessageList messages={[MESSAGE]} onToggleBookmark={onToggleBookmark} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Bookmark this answer" }));

    expect(onToggleBookmark).toHaveBeenCalledWith(MESSAGE);
  });

  it("test_a_bookmarked_message_shows_pressed_state_and_the_remove_label", () => {
    renderWithProviders(
      <MessageList
        messages={[{ ...MESSAGE, bookmarked: true }]}
        onToggleBookmark={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "Remove bookmark" });
    expect(button).toHaveAttribute("aria-pressed", "true");
  });

  it("test_a_user_turn_never_gets_a_bookmark_button", () => {
    renderWithProviders(
      <MessageList
        messages={[{ id: "msg-2", role: "user", content: "What is the capital of France?" }]}
        onToggleBookmark={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /bookmark/i })).not.toBeInTheDocument();
  });
});
