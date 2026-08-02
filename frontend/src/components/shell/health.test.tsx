import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders, stubJsonResponse, stubNetworkFailure } from "@/test/render";

import { HealthIndicator } from "./HealthIndicator";
import { SystemStatus } from "./SystemStatus";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the readiness indicator", () => {
  it("test_the_shell_reports_the_api_as_ready_from_a_real_readyz_response", async () => {
    stubJsonResponse(200, { status: "ready", checks: { postgres: "ok", redis: "ok" } });

    renderWithProviders(<HealthIndicator />);

    // A skeleton first, never a spinner over a blank region, and it announces
    // itself once rather than once per shape.
    expect(screen.getByRole("status", { name: "Checking API readiness" })).toBeInTheDocument();

    expect(await screen.findByText("API ready")).toBeInTheDocument();
  });

  it("test_a_degraded_api_is_named_in_words_and_not_only_in_colour", async () => {
    stubJsonResponse(503, {
      status: "not_ready",
      checks: { postgres: "ok", redis: "error: ConnectionError" },
    });

    renderWithProviders(<HealthIndicator />);

    // DesignSystem §3: colour is never the only signal. Around 8% of men have a
    // colour-vision deficiency, and the green/amber pair is the one they are
    // most likely to confuse — so the state has to be readable as text.
    const status = await screen.findByText("API degraded");
    expect(status.closest("[aria-live]")).toHaveAttribute("aria-live", "polite");
  });

  it("test_an_unreachable_api_is_distinguished_from_a_degraded_one", async () => {
    stubNetworkFailure();

    renderWithProviders(<HealthIndicator />);

    // "unreachable" and "degraded" send whoever reads them to different places,
    // so collapsing the two into one amber dot costs real debugging time.
    expect(await screen.findByText("API unreachable", undefined, { timeout: 3000 })).toBeInTheDocument();
  });
});

describe("the system status list", () => {
  it("test_every_dependency_the_api_reports_gets_a_row", async () => {
    stubJsonResponse(200, {
      status: "ready",
      checks: { postgres: "ok", redis: "ok" },
    });

    renderWithProviders(<SystemStatus />);

    // Waiting on the *content*, not on the list: the skeleton state renders the
    // same named list, which is right for a screen reader — one region, one
    // name, whatever its state — and would make a wait on the role vacuous.
    expect(await screen.findByText("postgres")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Dependencies" })).toBeInTheDocument();
    expect(screen.getByText("redis")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("test_a_failing_dependency_shows_the_apis_own_words", async () => {
    stubJsonResponse(503, {
      status: "not_ready",
      checks: { postgres: "ok", redis: "error: ConnectionError" },
    });

    renderWithProviders(<SystemStatus />);

    // Verbatim, not "unhealthy". The API already knows which exception it saw;
    // rewording it here loses the only clue the screen has.
    expect(await screen.findByText("error: ConnectionError")).toBeInTheDocument();
  });

  it("test_an_unreachable_api_renders_an_empty_state_and_not_an_empty_list", async () => {
    stubNetworkFailure();

    renderWithProviders(<SystemStatus />);

    // An empty pane with no explanation reads as a bug, and here it would be
    // the wrong bug: an empty dependency list looks like "no dependencies".
    expect(
      await screen.findByRole("heading", { name: "The API is unreachable" }, { timeout: 3000 }),
    ).toBeInTheDocument();
  });
});
