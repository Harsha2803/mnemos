import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/components/shell/AppShell";
import type { Citation } from "@/lib/knowledge/api";
import { INSPECTOR_INLINE, SIDEBAR_INLINE } from "@/components/shell/useMediaQuery";
import { setMediaQueries } from "@/test/harness";
import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";
import { useInspectorSelection } from "@/lib/inspector/SelectionProvider";

import { MessageList } from "./MessageList";

const CITATION: Citation = {
  id: "cite-1",
  message_id: "msg-1",
  marker: 1,
  document_id: "doc-1",
  chunk_id: "chunk-1",
  quoted_text: "Carry-over of unused discretionary leave is capped at five working days.",
  start_char: 0,
  end_char: 71,
  page_number: 3,
  score: 0.92,
};

/** The chat surface and the inspector, in the same tree the app renders. */
function ChatWithInspector() {
  const { select } = useInspectorSelection();
  return (
    <AppShell>
      <MessageList
        messages={[
          {
            id: "msg-1",
            role: "assistant",
            content: "You can carry over five days [1].",
            citations: [CITATION],
          },
        ]}
        onCitationClick={(citation) => select({ kind: "citation", citation })}
      />
    </AppShell>
  );
}

describe("citations", () => {
  it("test_the_citation_marker_opens_the_source_in_the_inspector", async () => {
    /**
     * End to end across the layout, not against `MessageBubble` alone: the
     * marker is in the content column and the panel it fills is a sibling of
     * the shell, so a test of the bubble in isolation would prove the click
     * handler fires and nothing about the thing it is for.
     */
    setMediaQueries({ [INSPECTOR_INLINE]: true, [SIDEBAR_INLINE]: true });
    stubRouter(() => jsonResponse(200, { status: "ready", checks: { postgres: "ok" } }));

    renderWithProviders(<ChatWithInspector />);

    // Before the click, the inspector says there is nothing to inspect.
    expect(screen.getByRole("heading", { name: "No message selected" })).toBeInTheDocument();

    // A real button, not a styled span — reachable by keyboard, announced as
    // a control (DesignSystem §3).
    await userEvent.click(screen.getByRole("button", { name: "Show source 1" }));

    expect(screen.queryByRole("heading", { name: "No message selected" })).toBeNull();
    expect(screen.getByText(CITATION.quoted_text)).toBeInTheDocument();
    expect(screen.getByText("Page 3")).toBeInTheDocument();
    // The char span is what makes this provenance rather than a document name.
    expect(screen.getByText(/Characters 0–71/)).toBeInTheDocument();
  });

  it("a marker with no matching citation stays plain text rather than a dead control", async () => {
    setMediaQueries({ [INSPECTOR_INLINE]: true, [SIDEBAR_INLINE]: true });
    stubRouter(() => jsonResponse(200, { status: "ready", checks: { postgres: "ok" } }));

    renderWithProviders(
      <MessageList
        messages={[
          {
            id: "msg-2",
            role: "assistant",
            content: "As established [7], the answer is five [1].",
            citations: [CITATION],
          },
        ]}
        onCitationClick={() => undefined}
      />,
    );

    expect(screen.getByRole("button", { name: "Show source 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show source 7" })).toBeNull();
  });
});
