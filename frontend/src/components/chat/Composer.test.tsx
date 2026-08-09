import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { Composer, type ComposerProps } from "./Composer";

/** Every prop defaulted, so a test names only what it is about. */
function renderComposer(overrides: Partial<ComposerProps> = {}) {
  const props: ComposerProps = {
    onSend: vi.fn(),
    onStop: vi.fn(),
    streaming: false,
    useDocuments: false,
    onUseDocumentsChange: vi.fn(),
    ...overrides,
  };
  return { ...render(<Composer {...props} />), props };
}

describe("the composer", () => {
  it("test_the_composer_sends_on_enter_and_newlines_on_shift_enter", async () => {
    const onSend = vi.fn();
    renderComposer({ onSend });
    const textarea = screen.getByRole("textbox", { name: "Message" });

    await userEvent.type(textarea, "line one");
    await userEvent.keyboard("{Shift>}{Enter}{/Shift}");
    await userEvent.type(textarea, "line two");

    // Shift+Enter inserted a newline and sent nothing.
    expect(textarea).toHaveValue("line one\nline two");
    expect(onSend).not.toHaveBeenCalled();

    await userEvent.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("line one\nline two");
    // Cleared after sending, so the next turn starts from an empty composer.
    expect(textarea).toHaveValue("");
  });

  it("does not send an empty or whitespace-only message", async () => {
    const onSend = vi.fn();
    renderComposer({ onSend });
    const textarea = screen.getByRole("textbox", { name: "Message" });

    await userEvent.type(textarea, "   ");
    await userEvent.keyboard("{Enter}");

    expect(onSend).not.toHaveBeenCalled();
  });

  it("test_the_composer_is_disabled_and_offers_stop_while_streaming", async () => {
    const onStop = vi.fn();
    renderComposer({ onStop, streaming: true });

    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Send message" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("test_the_use_documents_toggle_is_a_real_checkbox_and_reports_its_changes", async () => {
    const onUseDocumentsChange = vi.fn();
    renderComposer({ onUseDocumentsChange });

    // By role, so this fails if it is ever "simplified" into a styled div —
    // which would be unreachable by keyboard and silent to a screen reader.
    const toggle = screen.getByRole("checkbox", { name: "Use documents" });
    expect(toggle).not.toBeChecked();

    await userEvent.click(toggle);

    expect(onUseDocumentsChange).toHaveBeenCalledWith(true);
  });

  it("test_the_composer_has_no_axe_violations", async () => {
    const { container } = renderComposer();
    expect((await axe(container)).violations).toEqual([]);
  });
});
