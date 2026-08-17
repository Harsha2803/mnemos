import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import { UploadControl } from "./UploadControl";

const DOCUMENTS_PATH = "/api/v1/knowledge/documents";

function aFile(name: string, sizeBytes: number, type = "text/plain"): File {
  return new File([new Uint8Array(sizeBytes)], name, { type });
}

describe("the upload control", () => {
  it("test_a_file_over_the_limit_is_refused_without_a_network_call", async () => {
    const router = stubRouter((call) => {
      if (call.method === "POST" && call.path === DOCUMENTS_PATH) {
        return jsonResponse(201, { id: "should-not-be-reached" });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });
    const onUploaded = vi.fn();

    renderWithProviders(<UploadControl onUploaded={onUploaded} />);

    const oversized = aFile("huge.txt", 26 * 1024 * 1024);
    await userEvent.upload(await screen.findByLabelText("Upload documents"), oversized);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "huge.txt: larger than the 25 MB limit",
    );
    expect(router.countOf(DOCUMENTS_PATH)).toBe(0);
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("test_selecting_several_files_sends_one_request_per_file", async () => {
    const router = stubRouter((call) => {
      if (call.method === "POST" && call.path === DOCUMENTS_PATH) {
        return jsonResponse(201, { id: "019fe000-0000-7000-8000-00000000000a" });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });
    const onUploaded = vi.fn();

    renderWithProviders(<UploadControl onUploaded={onUploaded} />);

    const files = [aFile("one.txt", 10), aFile("two.txt", 10), aFile("three.txt", 10)];
    await userEvent.upload(await screen.findByLabelText("Upload documents"), files);

    await waitFor(() => expect(router.countOf(DOCUMENTS_PATH)).toBe(3));
    // One call for the whole settled batch, not one per file — the callback
    // just invalidates the document list, and that is idempotent regardless.
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("test_a_batch_with_one_bad_file_still_uploads_the_others_and_names_the_failure", async () => {
    const router = stubRouter((call) => {
      if (call.method === "POST" && call.path === DOCUMENTS_PATH) {
        return jsonResponse(201, { id: "019fe000-0000-7000-8000-00000000000a" });
      }
      return jsonResponse(404, { error: { code: "not_found", message: "not found" } });
    });
    const onUploaded = vi.fn();

    renderWithProviders(<UploadControl onUploaded={onUploaded} />);

    const files = [aFile("good.txt", 10), aFile("huge.txt", 26 * 1024 * 1024)];
    await userEvent.upload(await screen.findByLabelText("Upload documents"), files);

    // The oversized file never reaches the network — only the good one does.
    await waitFor(() => expect(router.countOf(DOCUMENTS_PATH)).toBe(1));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "huge.txt: larger than the 25 MB limit",
    );
    expect(onUploaded).toHaveBeenCalledTimes(1);
  });
});
