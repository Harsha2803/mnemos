import { act, screen } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/components/shell/AppShell";
import type { Citation } from "@/lib/knowledge/api";
import { INSPECTOR_INLINE, SIDEBAR_INLINE } from "@/components/shell/useMediaQuery";
import { setMediaQueries } from "@/test/harness";
import { jsonResponse, stubRouter } from "@/test/http";
import { navigation } from "@/test/navigation";
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

/** Re-render the tree after the test moves `navigation.pathname`. */
let rerenderTree: () => void = () => undefined;

/** The chat surface and the inspector, in the same tree the app renders. */
function ChatWithInspector() {
  const { select } = useInspectorSelection();
  const [, setTick] = useState(0);
  rerenderTree = () => setTick((tick) => tick + 1);
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
        onCitationClick={(citation) =>
          select({
            kind: "citation",
            message: {
              id: "msg-1",
              content: "You can carry over five days [1].",
              citations: [CITATION],
            },
            citation,
          })
        }
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

    // Before the click, there is nothing to inspect, so the inspector is a rail.
    expect(screen.getByRole("button", { name: "Expand context inspector" })).toBeInTheDocument();

    // A real button, not a styled span — reachable by keyboard, announced as
    // a control (DesignSystem §3).
    await userEvent.click(screen.getByRole("button", { name: "Show source 1" }));

    expect(screen.queryByRole("button", { name: "Expand context inspector" })).toBeNull();
    expect(screen.getAllByText(CITATION.quoted_text)).toHaveLength(2);
    expect(screen.getByText("Page 3")).toBeInTheDocument();
    // The char span is what makes this provenance rather than a document name.
    expect(screen.getAllByText(/Characters 0–71/)).toHaveLength(2);
  });

  it("test_leaving_the_conversation_clears_its_selection", async () => {
    // Evidence belongs to the conversation it was opened in. Carrying it onto
    // another page would show a passage beside content it says nothing about.
    setMediaQueries({ [INSPECTOR_INLINE]: true, [SIDEBAR_INLINE]: true });
    stubRouter(() => jsonResponse(200, { status: "ready", checks: { postgres: "ok" } }));
    navigation.pathname = "/chat/session-1";

    renderWithProviders(<ChatWithInspector />);
    await userEvent.click(screen.getByRole("button", { name: "Show source 1" }));
    expect(screen.getAllByText(CITATION.quoted_text)).toHaveLength(2);

    navigation.pathname = "/knowledge";
    act(() => rerenderTree());

    expect(screen.getAllByText(CITATION.quoted_text)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Expand context inspector" })).toBeInTheDocument();
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
