import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import type { Nl2SqlResult } from "@/lib/chat/stream";

import { MessageBubble } from "./MessageBubble";
import { SqlPanel } from "./SqlPanel";

const ALLOWED_RESULT: Nl2SqlResult = {
  sql: "SELECT region_name, SUM(net_amount) AS revenue FROM analytics.sales_order GROUP BY region_name",
  verdict: "allowed",
  verdict_detail: null,
  attempt: 1,
  authorized_tables: ["analytics.sales_order"],
  denied_tables: [],
  executed: true,
  row_count: 2,
  truncated: false,
  duration_ms: 42,
  error_code: null,
  error_detail: null,
  columns: ["region_name", "revenue"],
  rows: [
    ["West", 128400.5],
    ["East", 97200],
  ],
};

const REFUSED_RESULT: Nl2SqlResult = {
  sql: "DELETE FROM analytics.sales_order",
  verdict: "rejected_write",
  verdict_detail: "not a read statement (parsed as Delete)",
  attempt: 1,
  authorized_tables: [],
  denied_tables: ["analytics.sales_order"],
  executed: false,
  row_count: null,
  truncated: false,
  duration_ms: null,
  error_code: null,
  error_detail: null,
  columns: [],
  rows: [],
};

describe("the SQL panel", () => {
  it("test_the_sql_panel_shows_the_statement_the_grid_and_the_narration", () => {
    // Rendered through `MessageBubble`, not `SqlPanel` alone — the narration
    // lives in the bubble's own content, and deliverable 5's acceptance
    // criterion is about the two appearing together in the conversation.
    render(
      <MessageBubble
        message={{
          id: "msg-1",
          role: "assistant",
          content: "Revenue was highest in the West region.",
          nl2sql: ALLOWED_RESULT,
        }}
      />,
    );

    expect(screen.getByText("Revenue was highest in the West region.")).toBeInTheDocument();
    expect(screen.getByText(ALLOWED_RESULT.sql)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Query results" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "region_name" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "revenue" })).toBeInTheDocument();
    expect(screen.getByText("West")).toBeInTheDocument();
    expect(screen.getByText("128400.5")).toBeInTheDocument();
  });

  it("test_a_refused_query_shows_the_verdict_and_the_sql_it_refused", () => {
    render(
      <MessageBubble
        message={{
          id: "msg-2",
          role: "assistant",
          content:
            "Mnemos did not run this query: the generated statement was refused by the " +
            "read-only SQL policy and was not executed.",
          nl2sql: REFUSED_RESULT,
        }}
      />,
    );

    expect(
      screen.getByText("Refused — this statement would have written to the database"),
    ).toBeInTheDocument();
    expect(screen.getByText(REFUSED_RESULT.sql)).toBeInTheDocument();
    expect(screen.getByText(/not a read statement/)).toBeInTheDocument();
    // No grid: a rejected verdict was never executed, so there is nothing to show.
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows a truncation note only when the result set was capped", () => {
    const { rerender } = render(<SqlPanel result={ALLOWED_RESULT} />);
    expect(screen.queryByText(/more were available/)).toBeNull();

    rerender(<SqlPanel result={{ ...ALLOWED_RESULT, truncated: true }} />);
    expect(screen.getByText(/Showing the first 2 rows — more were available/)).toBeInTheDocument();
  });

  it("shows an execution-failure state distinct from a guard denial", () => {
    const timedOut: Nl2SqlResult = {
      ...ALLOWED_RESULT,
      executed: false,
      row_count: 0,
      columns: [],
      rows: [],
      error_code: "statement_timeout",
      error_detail: "exceeded the 15000ms statement timeout",
    };
    render(<SqlPanel result={timedOut} />);

    expect(
      screen.getByText("Allowed by the read-only guard, but the database could not run it"),
    ).toBeInTheDocument();
    expect(screen.getByText(/statement_timeout/)).toBeInTheDocument();
    expect(screen.getByText(/exceeded the 15000ms statement timeout/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("test_the_sql_panel_has_no_axe_violations", async () => {
    const { container } = render(<SqlPanel result={ALLOWED_RESULT} />);
    expect((await axe(container)).violations).toEqual([]);
  });

  it("the refused state has no axe violations either", async () => {
    const { container } = render(<SqlPanel result={REFUSED_RESULT} />);
    expect((await axe(container)).violations).toEqual([]);
  });
});
