import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { describe, expect, it } from "vitest";

import MemoryPage from "@/app/(app)/memory/page";
import { RevisionMark } from "@/components/ui/RevisionMark";
import { useInspectorSelection, type InspectorSelection } from "@/lib/inspector/SelectionProvider";
import type { Citation } from "@/lib/knowledge/api";
import { jsonResponse, stubRouter } from "@/test/http";
import { renderWithProviders } from "@/test/render";

import { InspectorContent } from "./InspectorContent";

const CITATIONS: Citation[] = [
  { id: "c1", message_id: "m1", marker: 1, document_id: "d1", chunk_id: "k1", quoted_text: "Three days carry over.", start_char: 10, end_char: 32, page_number: 4, score: 0.9 },
  { id: "c2", message_id: "m1", marker: 2, document_id: "d1", chunk_id: "k2", quoted_text: "Unused days lapse in March.", start_char: 33, end_char: 60, page_number: 5, score: 0.8 },
];
const MESSAGE = { id: "m1", content: "Three days [1], lapsing in March [2].", citations: CITATIONS };

const BUNDLE = {
  id: "b1", digest: "9f2c4e1ab07d5c3e88a1", flow: "rag", token_budget: 800, tokens_consumed: 412,
  compiled_prompt: "[QUESTION]\nhow many", budget_report: {},
  explain: { refine: { conflicts_demoted: 1, conflicts: [{ candidate: "Handbook 2025 §4", preferred_source: "Handbook 2026 §4" }] } },
  admitted: [{ id: "i1", position: 0, section: "evidence", operator: "hybrid", text: "Three days carry over.", tokens: 31, raw_score: 0.9, rrf_score: 0.03, utility: 0.9, density: 0.03, trust_tier: 40, source_kind: "document", source_ref: "d1#k1", document_title: "Employee Handbook 2026.pdf", acl_rule: "tag:hr", memory_id: null }],
  rejections: [{ key: "d0#k1", section: "evidence", source_kind: "document", source_ref: "Employee Handbook 2025.pdf §4", reason: "superseded_revision", tokens: 30, utility: 0.9, detail: "Superseded by the 2026 handbook." }],
  lineage: [{ source_id: "d1", target_id: "d0", kind: "supersedes", rationale: "2026 revision" }],
  created_at: "2026-10-22T08:00:00Z",
};

function stubLibrary() {
  stubRouter((call) => {
    if (call.path.endsWith("/knowledge/documents")) {
      return jsonResponse(200, [
        { id: "d1", title: "Employee Handbook 2026.pdf", media_type: "application/pdf", byte_size: 1, status: "ready", chunk_count: 2, superseded_by: null, created_at: "2026-10-01T00:00:00Z" },
        { id: "d0", title: "Employee Handbook 2025.pdf", media_type: "application/pdf", byte_size: 1, status: "ready", chunk_count: 2, superseded_by: "d1", created_at: "2025-10-01T00:00:00Z" },
      ]);
    }
    if (call.path.endsWith("/context/messages/m1/bundle")) return jsonResponse(200, BUNDLE);
    if (call.path.endsWith("/memories")) {
      return jsonResponse(200, {
        claims: [
          { id: "new", subject: { id: "s", kind: "person", external_ref: "employee:priya", display_name: "Priya Raman" }, predicate: "reports_to", object_text: "Jonas Weber", kind: "fact", status: "active", scope: {}, valid_from: "2026-07-01T00:00:00Z", valid_to: "9999-12-31T23:59:59Z", recorded_at: "2026-09-22T00:00:00Z", retracted_at: null, confidence: 1, trust_tier: 40, source_kind: "user", source_ref: null },
          { id: "old", subject: { id: "s", kind: "person", external_ref: "employee:priya", display_name: "Priya Raman" }, predicate: "reports_to", object_text: "Elena Petrova", kind: "fact", status: "superseded", scope: {}, valid_from: "2025-03-01T00:00:00Z", valid_to: "2026-07-01T00:00:00Z", recorded_at: "2026-04-05T00:00:00Z", retracted_at: null, confidence: 1, trust_tier: 40, source_kind: "user", source_ref: null },
        ],
        edges: [{ id: "e", source_id: "new", target_id: "old", kind: "supersedes", rationale: null, created_at: "2026-09-22T00:00:00Z" }],
      });
    }
    return jsonResponse(404, {});
  });
}

/** The inspector with a selection already made, as a page would make it. */
function InspectorWith({ selection }: { selection: InspectorSelection }) {
  const { select } = useInspectorSelection();
  useEffect(() => select(selection), [select, selection]);
  return <InspectorContent />;
}

describe("revision marks", () => {
  it("test_a_revision_mark_strikes_the_old_value_and_says_what_replaced_it", () => {
    render(<RevisionMark previous="Elena Petrova" current="Jonas Weber" effective="1 Jul 2026" />);

    const struck = document.querySelector("del");
    const added = document.querySelector("ins");
    expect(struck).toHaveTextContent("Superseded: Elena Petrova");
    expect(added).toHaveTextContent("Replaced by: Jonas Weber");
    expect(screen.getByText("effective 1 Jul 2026")).toBeInTheDocument();
  });

  it("test_memory_shows_supersession_as_a_revision_not_as_raw_ids", async () => {
    stubLibrary();
    renderWithProviders(<MemoryPage />);

    const revisions = await screen.findByRole("complementary", { name: "Revisions" });
    expect(await within(revisions).findByText("Superseded:", { exact: false })).toBeInTheDocument();
    expect(revisions.querySelector("del")).toHaveTextContent("Elena Petrova");
    expect(revisions.querySelector("ins")).toHaveTextContent("Jonas Weber");
    expect(revisions).not.toHaveTextContent("new supersedes old");
  });
});

describe("the inspector's views", () => {
  it("test_evidence_names_each_document_and_page", async () => {
    stubLibrary();
    renderWithProviders(<InspectorWith selection={{ kind: "message", message: MESSAGE }} />);

    expect(await screen.findAllByText("Employee Handbook 2026.pdf")).toHaveLength(2);
    expect(screen.getByText("2 passages from 1 document.")).toBeInTheDocument();
    expect(screen.getByText("p.5")).toBeInTheDocument();
  });

  it("test_a_citation_reads_as_a_titled_passage_with_its_location", async () => {
    stubLibrary();
    renderWithProviders(
      <InspectorWith selection={{ kind: "citation", message: MESSAGE, citation: CITATIONS[0] as Citation }} />,
    );

    expect(await screen.findByRole("heading", { level: 3, name: "Employee Handbook 2026.pdf" })).toBeInTheDocument();
    expect(screen.getByText("Source 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Page 4")).toBeInTheDocument();
    expect(screen.getByText(/Characters 10–32/)).toBeInTheDocument();
    expect(document.querySelector("blockquote")).toHaveTextContent("Three days carry over.");

    await userEvent.click(screen.getByRole("button", { name: "Next citation" }));
    expect(screen.getByText("Source 2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next citation" })).toBeDisabled();
  });

  it("test_the_bundle_shows_exclusions_struck_and_lineage_as_revision_marks", async () => {
    stubLibrary();
    renderWithProviders(<InspectorWith selection={{ kind: "bundle", message: MESSAGE }} />);

    expect(await screen.findByRole("heading", { name: "Hard token budget" })).toBeInTheDocument();
    expect(screen.getByText("Admitted · 1")).toBeInTheDocument();
    expect(screen.getByText("Excluded · 1")).toBeInTheDocument();
    expect(screen.getByText("superseded revision")).toBeInTheDocument();

    // The document lineage names both revisions, once the library resolves.
    const inserted = () => [...document.querySelectorAll("ins")].map((mark) => mark.textContent);
    await waitFor(() => expect(inserted()).toContain("Replaced by: Employee Handbook 2026.pdf"));
    expect(inserted()).toContain("Replaced by: Handbook 2026 §4");
    expect([...document.querySelectorAll("del")].map((mark) => mark.textContent)).toContain(
      "Superseded: Employee Handbook 2025.pdf",
    );
  });
});
