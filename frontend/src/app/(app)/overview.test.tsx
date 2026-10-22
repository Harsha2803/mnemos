import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import OverviewPage from "./page";

const NOW = new Date("2026-10-22T10:00:00Z");
const ago = (minutes: number) => new Date(NOW.getTime() - minutes * 60_000).toISOString();

function stubWorkspace() {
  stubRouter((call) => {
    if (call.path === "/readyz") return jsonResponse(200, { status: "ready", checks: { postgres: "ok", redis: "ok" } });
    if (call.path.endsWith("/knowledge/documents")) {
      return jsonResponse(200, [
        { id: "d1", title: "Handbook 2026.pdf", media_type: "application/pdf", byte_size: 1, status: "ready", chunk_count: 3, superseded_by: null, created_at: ago(60 * 26) },
        { id: "d0", title: "Handbook 2025.pdf", media_type: "application/pdf", byte_size: 1, status: "ready", chunk_count: 3, superseded_by: "d1", created_at: ago(60 * 24 * 300) },
      ]);
    }
    if (call.path.endsWith("/connectors/jobs")) {
      return jsonResponse(200, [
        { id: "j1", kind: "connector.ingest", status: "failed", payload: { item_name: "FAQ.html", source_slug: "hr" }, document_id: null, attempts: 3, max_attempts: 3, done_units: 1, total_units: 4, owner_id: null, heartbeat_at: null, lease_expires_at: null, started_at: null, finished_at: null, error_code: "extract_failed", error_detail: "no readable text", created_at: ago(90), updated_at: ago(30), events: [] },
      ]);
    }
    if (call.path.endsWith("/connectors")) return jsonResponse(200, [{ id: "s", slug: "hr", name: "HR", kind: "local_fs", is_enabled: true, created_at: ago(1000) }]);
    if (call.path.endsWith("/chat/sessions")) {
      return jsonResponse(200, { sessions: [{ id: "c1", title: "Carry-over leave", folder_id: null, is_archived: false, created_at: ago(130), updated_at: ago(120), last_message_at: ago(120) }], next_cursor: null });
    }
    if (call.path.endsWith("/memories")) return jsonResponse(200, { claims: [], edges: [] });
    return jsonResponse(404, {});
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the overview", () => {
  it("test_the_workspace_state_is_one_sentence_with_its_numbers_linked", async () => {
    stubWorkspace();
    renderWithProviders(<OverviewPage />);

    const current = await screen.findByRole("link", { name: "1 current document" });
    expect(current).toHaveAttribute("href", "/knowledge");
    const sentence = current.closest("p");
    expect(sentence).toHaveTextContent("1 superseded revision kept on record.");
    expect(sentence).toHaveTextContent("1 source connected, with 1 failed.");
    expect(sentence).toHaveTextContent("1 conversation, the latest 2 hours ago.");
  });

  it("test_readiness_is_one_line_with_the_services_on_demand", async () => {
    stubWorkspace();
    renderWithProviders(<OverviewPage />);

    const summary = await screen.findByText("All 2 services ready");
    const details = summary.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(within(details as HTMLElement).getByText("postgres")).toBeInTheDocument();
  });

  it("test_activity_is_a_dated_ledger_with_revisions_and_failures", async () => {
    stubWorkspace();
    renderWithProviders(<OverviewPage />);

    const today = await screen.findByRole("region", { name: "Today" });
    expect(within(today).getByText("Failed")).toBeInTheDocument();
    expect(within(today).getByText("FAQ.html")).toBeInTheDocument();
    expect(within(today).getByRole("link", { name: /Carry-over leave/ })).toHaveAttribute("href", "/chat/c1");

    const yesterday = screen.getByRole("region", { name: "Yesterday" });
    expect(within(yesterday).getByText("Revised")).toBeInTheDocument();
    expect(yesterday.querySelector("del")).toHaveTextContent("Handbook 2025.pdf");
    expect(yesterday.querySelector("ins")).toHaveTextContent("Handbook 2026.pdf");
  });
});
