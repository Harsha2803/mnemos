import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import KnowledgePage from "./page";

const DOCUMENTS_PATH = "/api/v1/knowledge/documents";

function aDocument(overrides: Record<string, unknown> = {}) {
  return {
    id: "019fe000-0000-7000-8000-00000000000a",
    title: "Q3 Revenue Policy",
    media_type: "text/plain",
    byte_size: 2048,
    status: "ready",
    superseded_by: null,
    chunk_count: 4,
    created_at: "2026-08-08T12:00:00Z",
    ...overrides,
  };
}

describe("the knowledge library", () => {
  it("test_deleting_a_document_names_it_in_the_confirmation", async () => {
    /**
     * DesignSystem §4: "Delete document?" is not good enough; the
     * confirmation names the specific thing being destroyed. Asserted on the
     * rendered dialog rather than on the string constant, because the way
     * this breaks is somebody rendering a generic message beside a specific
     * one.
     */
    const router = stubRouter((call) => {
      if (call.method === "GET" && call.path === DOCUMENTS_PATH) {
        return jsonResponse(200, [aDocument()]);
      }
      if (call.method === "DELETE") return new Response(null, { status: 204 });
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<KnowledgePage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete Q3 Revenue Policy" }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Delete Q3 Revenue Policy?");

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(router.countOf(`${DOCUMENTS_PATH}/${aDocument().id}`)).toBe(1));
  });

  it("test_upload_shows_a_layout_matching_skeleton_never_a_spinner", async () => {
    /**
     * DesignSystem §4: skeletons that match the final layout, never a centred
     * spinner over a blank region. The upload is held open deliberately so
     * the in-flight state is observable rather than raced past.
     */
    let releaseUpload!: () => void;
    const held = new Promise<void>((resolve) => {
      releaseUpload = resolve;
    });

    stubRouter(async (call) => {
      if (call.method === "GET" && call.path === DOCUMENTS_PATH) return jsonResponse(200, []);
      if (call.method === "POST" && call.path === DOCUMENTS_PATH) {
        await held;
        return jsonResponse(201, aDocument());
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    renderWithProviders(<KnowledgePage />);

    const input = await screen.findByLabelText("Upload a document");
    await userEvent.upload(
      input,
      new File(["some document text"], "policy.txt", { type: "text/plain" }),
    );

    // The labelled skeleton stands for the region; a spinner would have
    // thrown away the shape of what is coming.
    expect(await screen.findByRole("status", { name: "Processing the document" }))
      .toBeInTheDocument();

    releaseUpload();
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Processing the document" })).toBeNull(),
    );
  });

  it("an upload the API refuses shows the reason it gave", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === DOCUMENTS_PATH) return jsonResponse(200, []);
      return jsonResponse(422, {
        error: {
          code: "validation_error",
          message: "unsupported media type 'application/zip'",
          field: "media_type",
        },
      });
    });

    renderWithProviders(<KnowledgePage />);

    // `applyAccept: false` because the input's `accept` list would filter this
    // file out — which is `userEvent` faithfully simulating a real file
    // picker. `accept` is a hint the browser applies to the picker only; a
    // drag-and-drop, or any non-browser caller, reaches the server regardless,
    // so the server's refusal is the control being tested here and the client
    // hint is not a substitute for it.
    await userEvent.upload(
      await screen.findByLabelText("Upload a document"),
      new File(["PK"], "archive.zip", { type: "application/zip" }),
      { applyAccept: false },
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unsupported media type 'application/zip'",
    );
  });

  it("test_the_knowledge_library_has_no_axe_violations", async () => {
    stubRouter((call) => {
      if (call.method === "GET" && call.path === DOCUMENTS_PATH) {
        return jsonResponse(200, [aDocument()]);
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });

    const { container } = renderWithProviders(<KnowledgePage />);
    await screen.findByText("Q3 Revenue Policy");

    expect((await axe(container)).violations).toEqual([]);
  });
});
