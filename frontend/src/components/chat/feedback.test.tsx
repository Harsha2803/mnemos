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

describe("rating a message", () => {
  it("test_rating_an_answer_up_reports_the_message_and_rating", async () => {
    const onRate = vi.fn();
    renderWithProviders(<MessageList messages={[MESSAGE]} onRate={onRate} />);

    await userEvent.click(screen.getByRole("button", { name: "Good answer" }));

    expect(onRate).toHaveBeenCalledWith(MESSAGE, "up", undefined);
  });

  it("test_rating_an_answer_down_reveals_an_optional_comment_field", async () => {
    const onRate = vi.fn();
    renderWithProviders(<MessageList messages={[MESSAGE]} onRate={onRate} />);

    await userEvent.click(screen.getByRole("button", { name: "Bad answer" }));

    expect(onRate).toHaveBeenCalledWith(MESSAGE, "down", undefined);
    expect(screen.getByPlaceholderText("What went wrong? (optional)")).toBeInTheDocument();
  });

  it("test_typing_a_comment_and_pressing_enter_attaches_it_to_the_down_rating", async () => {
    const onRate = vi.fn();
    renderWithProviders(<MessageList messages={[MESSAGE]} onRate={onRate} />);

    await userEvent.click(screen.getByRole("button", { name: "Bad answer" }));
    const field = screen.getByPlaceholderText("What went wrong? (optional)");
    await userEvent.type(field, "made up a number{Enter}");

    expect(onRate).toHaveBeenLastCalledWith(MESSAGE, "down", "made up a number");
  });

  it("test_clicking_an_already_selected_thumb_clears_the_rating", async () => {
    const onRate = vi.fn();
    const rated: DisplayMessage = { ...MESSAGE, feedback: "up" };
    renderWithProviders(<MessageList messages={[rated]} onRate={onRate} />);

    await userEvent.click(screen.getByRole("button", { name: "Remove rating" }));

    expect(onRate).toHaveBeenCalledWith(rated, null, undefined);
  });

  it("test_a_user_turn_never_gets_rating_buttons", () => {
    renderWithProviders(
      <MessageList
        messages={[{ id: "msg-2", role: "user", content: "What is the capital of France?" }]}
        onRate={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /good answer|bad answer/i })).not.toBeInTheDocument();
  });
});
