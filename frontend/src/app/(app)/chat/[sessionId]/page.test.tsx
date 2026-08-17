import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { renderWithProviders } from "@/test/render";
import { jsonResponse, stubRouter } from "@/test/http";
import { visit } from "@/test/navigation";

import ChatSessionPage from "./page";

const SESSION_ID = "019fe000-0000-7000-8000-000000000001";

function sessionDetail(messages: unknown[] = []) {
  return {
    session: {
      id: SESSION_ID,
      title: "New chat",
      is_archived: false,
      last_message_at: null,
      created_at: "2026-08-04T12:00:00Z",
      updated_at: "2026-08-04T12:00:00Z",
    },
    messages,
  };
}

/**
 * A `ReadableStream` the test controls one `enqueue` at a time — the SSE body
 * `POST .../messages` answers with, in `stream.ts`'s frame shape.
 */
function controllableSseStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  const encoder = new TextEncoder();
  return {
    stream,
    push(event: string, data: unknown) {
      controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
    },
    close() {
      controller.close();
    },
  };
}

function renderChatSession(handleMessages: (call: { method: string }) => Response) {
  visit(`/chat/${SESSION_ID}`, "", { sessionId: SESSION_ID });
  return stubRouter((call) => {
    if (call.method === "GET" && call.path === `/api/v1/chat/sessions/${SESSION_ID}`) {
      return jsonResponse(200, sessionDetail());
    }
    if (call.method === "POST" && call.path === `/api/v1/chat/sessions/${SESSION_ID}/messages`) {
      return handleMessages(call);
    }
    return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
  });
}

describe("the chat session surface", () => {
  it("test_tokens_render_as_they_arrive_and_never_behind_a_spinner", async () => {
    const sse = controllableSseStream();
    renderChatSession(
      () =>
        new Response(sse.stream, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
    );

    renderWithProviders(<ChatSessionPage />);

    const textarea = await screen.findByRole("textbox", { name: "Message" });
    await userEvent.type(textarea, "hello there{Enter}");

    sse.push("route", {
      flow: "chat",
      reason: "No document or database context is needed.",
    });
    await waitFor(() =>
      expect(
        screen.getByLabelText(
          "Routed to Chat: No document or database context is needed.",
        ),
      ).toBeInTheDocument(),
    );

    // Nothing from the model yet: the assistant bubble exists (never a
    // spinner over a blank region) but carries no text.
    expect(screen.queryByText("Hel")).toBeNull();

    sse.push("token", { text: "Hel" });
    await waitFor(() => expect(screen.getByText("Hel")).toBeInTheDocument());

    // The second chunk has deliberately not arrived yet — this is the
    // assertion that fails if the client awaited the whole response instead
    // of rendering as tokens arrive.
    expect(screen.queryByText("Hello")).toBeNull();

    sse.push("token", { text: "lo" });
    await waitFor(() => expect(screen.getByText("Hello")).toBeInTheDocument());

    sse.push("done", {
      message: {
        id: "msg-1",
        ordinal: 1,
        role: "assistant",
        content: "Hello",
        flow: "chat",
        router_rationale: "No document or database context is needed.",
        prompt_tokens: 3,
        completion_tokens: 2,
        latency_ms: 12,
        model: "qwen2.5:3b-instruct",
        finish_reason: "stop",
        created_at: "2026-08-04T12:00:01Z",
      },
    });
    sse.close();

    // Streaming ends, the composer re-enables.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send message" })).toBeInTheDocument(),
    );
  });

  it("test_the_chat_surface_has_no_axe_violations", async () => {
    renderChatSession(() => jsonResponse(200, { error: "unused in this test" }));
    const { container } = renderWithProviders(<ChatSessionPage />);

    await screen.findByRole("textbox", { name: "Message" });

    expect((await axe(container)).violations).toEqual([]);
  });
});
