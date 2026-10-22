import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Citation } from "@/lib/knowledge/api";
import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import { MessageBubble, type DisplayMessage } from "./MessageBubble";
import { MessageList } from "./MessageList";

const CITATION: Citation = {
  id: "cite-1",
  message_id: "answer-1",
  marker: 1,
  document_id: null,
  chunk_id: "chunk-1",
  quoted_text: "Carried-over days not used by 31 March lapse.",
  start_char: 10,
  end_char: 56,
  page_number: 4,
  score: 0.8,
};

const ANSWER: DisplayMessage = {
  id: "answer-1",
  role: "assistant",
  content: "Days lapse on 31 March [1].\n\nAn exception needs approval in writing.",
  flow: "rag",
  routeReason: "Asks about documents or cited knowledge.",
  citations: [CITATION],
};

describe("an answer as a document", () => {
  it("test_each_paragraph_is_its_own_block_of_reading_text", () => {
    render(<MessageBubble message={ANSWER} />);
    const answer = screen.getByRole("article", { name: "Answer from Mnemos" });
    expect(answer.querySelectorAll("p.font-serif")).toHaveLength(2);
  });

  it("test_a_numeral_hugs_the_word_it_cites", () => {
    // "March [1]." in the model's text is set "March¹." — no space before a
    // superscript, the way a printed note mark sits.
    render(<MessageBubble message={ANSWER} onCitationClick={() => undefined} />);
    const paragraph = screen.getByRole("button", { name: "Show source 1" }).closest("p");
    expect(paragraph?.textContent).toBe("Days lapse on 31 March1.");
  });

  it("test_the_latest_answer_shows_its_context_budget_as_a_meter", async () => {
    stubRouter((call) =>
      call.path.endsWith("/context/messages/answer-1/bundle")
        ? jsonResponse(200, {
            id: "b", digest: "d", flow: "rag", token_budget: 800, tokens_consumed: 412,
            compiled_prompt: "", budget_report: {}, explain: {}, admitted: [], rejections: [],
            lineage: [], created_at: "2026-10-22T08:00:00Z",
          })
        : jsonResponse(404, {}),
    );
    renderWithProviders(<MessageBubble message={ANSWER} showBudget />);

    const meter = await screen.findByRole("meter", { name: "Context budget used" });
    expect(meter).toHaveAttribute("aria-valuenow", "412");
    expect(meter).toHaveAttribute("aria-valuemax", "800");
    expect(meter).toHaveAttribute("aria-valuetext", "412 of 800 tokens");
  });

  it("test_on_a_narrow_transcript_a_numeral_discloses_its_source_inline", async () => {
    // Nothing floats over the text being read: on a narrow pane the source
    // opens under its paragraph, and the inspector is one deliberate press on.
    const onCitationClick = vi.fn();
    render(<MessageBubble message={ANSWER} wide={false} onCitationClick={onCitationClick} />);

    const marker = screen.getByRole("button", { name: "Show source 1" });
    expect(marker).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(marker);
    expect(marker).toHaveAttribute("aria-expanded", "true");
    const note = document.getElementById(marker.getAttribute("aria-controls") as string);
    expect(note).toHaveTextContent(CITATION.quoted_text);
    expect(onCitationClick).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Open source 1 in the inspector" }));
    expect(onCitationClick).toHaveBeenCalledWith(CITATION);

    await userEvent.click(marker);
    expect(marker).toHaveAttribute("aria-expanded", "false");
  });

  it("test_on_a_wide_transcript_a_numeral_opens_the_inspector_directly", async () => {
    const onCitationClick = vi.fn();
    render(<MessageBubble message={ANSWER} wide onCitationClick={onCitationClick} />);

    const marker = screen.getByRole("button", { name: "Show source 1" });
    expect(marker).not.toHaveAttribute("aria-expanded");
    await userEvent.click(marker);
    expect(onCitationClick).toHaveBeenCalledWith(CITATION);
  });

  it("test_the_route_stamp_reveals_its_rationale_on_demand", async () => {
    render(<MessageBubble message={ANSWER} />);

    const stamp = screen.getByRole("button", {
      name: "Routed to Documents: Asks about documents or cited knowledge.",
    });
    const why = document.getElementById(stamp.getAttribute("aria-controls") as string);
    expect(stamp).toHaveTextContent("Documents");
    expect(why).not.toBeVisible();

    await userEvent.click(stamp);
    expect(stamp).toHaveAttribute("aria-expanded", "true");
    expect(why).toBeVisible();
    expect(why).toHaveTextContent("Answered from your documents.");
  });

  it("test_a_failed_answer_says_so_and_offers_to_ask_again", async () => {
    const onRetry = vi.fn();
    render(
      <MessageBubble
        message={{ id: "answer-2", role: "assistant", content: "the model is unavailable", failed: true }}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("Not answered")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ask again" }));
    expect(onRetry).toHaveBeenCalledOnce();
    // No bookmark or rating controls on something that is not an answer.
    expect(screen.queryByRole("button", { name: "Bookmark this answer" })).toBeNull();
  });

  it("test_a_rolled_back_action_is_explained_where_it_was_pressed", () => {
    render(
      <MessageBubble
        message={{ ...ANSWER, bookmarked: false, actionError: "The bookmark was not saved. Try again." }}
        onToggleBookmark={() => undefined}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("The bookmark was not saved. Try again.");
  });
});

describe("the transcript", () => {
  it("test_completion_is_announced_once_rather_than_token_by_token", () => {
    const streaming: DisplayMessage = { id: "pending-1", role: "assistant", content: "Hel", streaming: true };
    const { rerender } = renderWithProviders(<MessageList messages={[streaming]} />);

    const region = screen.getAllByRole("status").find((element) => element.getAttribute("aria-live") === "polite");
    expect(region).toHaveTextContent("Mnemos is answering.");
    expect(screen.getByRole("article", { name: "Answer from Mnemos" }).querySelector("[aria-busy='true']")).not.toBeNull();

    rerender(<MessageList messages={[{ ...streaming, content: "Hello", streaming: false }]} />);
    expect(region).toHaveTextContent("Answer complete.");
  });

  it("test_new_text_does_not_pull_a_reader_who_scrolled_up", () => {
    const first: DisplayMessage = { id: "q-1", role: "user", content: "First question" };
    const { rerender, container } = renderWithProviders(
      <div className="overflow-y-auto">
        <MessageList messages={[first]} />
      </div>,
    );
    const pane = container.querySelector(".overflow-y-auto") as HTMLElement;
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;

    // The reader is far from the end: 2000px of content, 400px of view, at 0.
    Object.defineProperty(pane, "scrollHeight", { configurable: true, value: 2000 });
    Object.defineProperty(pane, "clientHeight", { configurable: true, value: 400 });
    pane.scrollTop = 0;
    fireEvent.scroll(pane);

    rerender(
      <div className="overflow-y-auto">
        <MessageList messages={[first, { id: "a-1", role: "assistant", content: "New text", streaming: true }]} />
      </div>,
    );

    expect(scrollIntoView).not.toHaveBeenCalled();
    const jump = screen.getByRole("button", { name: "Jump to latest" });
    act(() => jump.click());
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "end", behavior: "smooth" });
    expect(screen.queryByRole("button", { name: "Jump to latest" })).toBeNull();
    // jsdom has no scrollIntoView; leave it that way for whoever runs next.
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });
});
