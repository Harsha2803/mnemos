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
    useDatasource: false,
    onUseDatasourceChange: vi.fn(),
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

  it("test_the_answer_mode_control_is_a_real_radiogroup_and_reports_its_changes", async () => {
    const onUseDocumentsChange = vi.fn();
    renderComposer({ onUseDocumentsChange });

    // By role, so this fails if it is ever "simplified" into styled divs —
    // which would be unreachable by keyboard and silent to a screen reader.
    // `chat` is selected by default: a real, nameable third state, not the
    // absence of a choice.
    expect(screen.getByRole("radio", { name: "Chat" })).toHaveAttribute("aria-checked", "true");
    const documents = screen.getByRole("radio", { name: "Use documents" });
    expect(documents).toHaveAttribute("aria-checked", "false");

    await userEvent.click(documents);

    expect(onUseDocumentsChange).toHaveBeenCalledWith(true);
  });

  it("test_the_use_datasource_option_reports_its_changes", async () => {
    const onUseDatasourceChange = vi.fn();
    renderComposer({ onUseDatasourceChange });

    const toggle = screen.getByRole("radio", { name: "Ask your data" });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await userEvent.click(toggle);

    expect(onUseDatasourceChange).toHaveBeenCalledWith(true);
  });

  it("the three answer modes are mutually exclusive by construction", () => {
    // Reflects the backend's own rule: sending both `use_documents` and
    // `use_datasource` as `true` is a 422. A `radiogroup` cannot represent
    // two selections at once, so there is no separate "disable the sibling"
    // logic to test — the control itself makes the impossible state
    // unbuildable.
    const usingDocuments = renderComposer({ useDocuments: true });
    expect(screen.getByRole("radio", { name: "Use documents" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: "Ask your data" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    usingDocuments.unmount();

    renderComposer({ useDatasource: true });
    expect(screen.getByRole("radio", { name: "Ask your data" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: "Use documents" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("test_the_composer_has_no_axe_violations", async () => {
    const { container } = renderComposer();
    expect((await axe(container)).violations).toEqual([]);
  });
});
