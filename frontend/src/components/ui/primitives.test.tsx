import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Inbox } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import compiledCss from "@/app/globals.css?inline";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { resolvedPx } from "@/test/harness";

import { Button } from "./Button";
import { EmptyState } from "./EmptyState";
import { List, ListItem } from "./List";
import { Skeleton } from "./Skeleton";

const INTERACTIVE = 'button, a[href], input, select, textarea, [role="button"]';

describe("Button", () => {
  it("test_button_is_found_by_role_and_accessible_name_in_every_rank", async () => {
    // Querying by role and name is an accessibility assertion as much as a
    // behavioural one: a <div onClick> passes neither.
    const clicked = vi.fn();
    render(
      <>
        <Button rank="filled" onClick={clicked}>
          Connect a source
        </Button>
        <Button rank="tinted">Browse knowledge</Button>
        <Button rank="plain">Cancel</Button>
      </>,
    );

    for (const name of ["Connect a source", "Browse knowledge", "Cancel"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }

    await userEvent.click(screen.getByRole("button", { name: "Connect a source" }));
    expect(clicked).toHaveBeenCalledOnce();
  });

  it("test_button_does_not_submit_a_form_unless_asked", () => {
    // The HTML default is `submit`, which has cost more accidental navigations
    // than it has saved keystrokes.
    render(<Button>Cancel</Button>);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveAttribute("type", "button");
  });

  it("test_the_three_ranks_are_visually_distinct_and_there_is_no_fourth", () => {
    render(
      <>
        <Button rank="filled">Filled</Button>
        <Button rank="tinted">Tinted</Button>
        <Button rank="plain">Plain</Button>
      </>,
    );

    const background = (name: string) =>
      window.getComputedStyle(screen.getByRole("button", { name })).backgroundColor;

    // Three ranks that resolve to the same fill are one rank with three names.
    const fills = new Set([background("Filled"), background("Tinted"), background("Plain")]);
    expect(fills.size).toBe(3);
  });
});

describe("List", () => {
  it("test_list_and_its_rows_are_found_by_role_and_accessible_name", () => {
    render(
      <List label="Dependencies">
        <ListItem trailing="ok">postgres</ListItem>
        <ListItem trailing="ok">redis</ListItem>
      </List>,
    );

    expect(screen.getByRole("list", { name: "Dependencies" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("postgres")).toBeInTheDocument();
  });

  it("test_separators_are_inset_to_the_text_origin_and_never_full_bleed", () => {
    // The detail that most separates a considered list from a default one. A
    // separator at inset 0 runs edge to edge and cuts the group in half instead
    // of dividing it, so `left: 0` here is a regression, not a style choice.
    expect(compiledCss).toMatch(
      /\.list-row \+ \.list-row::before\s*\{[^}]*left:\s*var\(--list-inset\)/,
    );
    expect(compiledCss).toMatch(/\.list-row\s*\{[^}]*--list-inset:\s*var\(--space-4\)/);
    // A leading icon moves the text origin, so it has to move the separator.
    expect(compiledCss).toMatch(
      /\.list-row-leading\s*\{[^}]*--list-inset:\s*calc\(var\(--space-4\) \+ 1\.25rem \+ var\(--space-3\)\)/,
    );
  });

  it("test_a_row_with_a_leading_slot_shifts_its_own_separator", () => {
    render(
      <List label="Sections">
        <ListItem leading={<Inbox aria-hidden="true" />}>Overview</ListItem>
        <ListItem>Plain row</ListItem>
      </List>,
    );

    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveClass("list-row-leading");
    expect(rows[1]).not.toHaveClass("list-row-leading");
  });
});

describe("EmptyState", () => {
  it("test_empty_state_is_found_by_its_heading_role_and_name", () => {
    render(
      <EmptyState
        icon={Inbox}
        title="No message selected"
        description="Select a message to see the context bundle that produced it."
        headingLevel={2}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "No message selected" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Select a message to see the context bundle that produced it."),
    ).toBeInTheDocument();
  });

  it("test_empty_state_renders_the_action_it_is_given", () => {
    render(<EmptyState icon={Inbox} title="Nothing here" action={<Button rank="filled">Add one</Button>} />);
    expect(screen.getByRole("button", { name: "Add one" })).toBeInTheDocument();
  });
});

describe("Skeleton", () => {
  it("test_a_labelled_skeleton_announces_itself_and_an_unlabelled_one_does_not", () => {
    // Six live regions all saying "loading" is worse than none, so only the
    // shape that stands for the region is announced.
    render(
      <div>
        <Skeleton label="Loading readiness" className="h-4 w-32" />
        <Skeleton className="h-4 w-16" />
      </div>,
    );

    expect(screen.getByRole("status", { name: "Loading readiness" })).toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });
});

describe("accessibility floors", () => {
  it("test_every_interactive_target_is_at_least_44px", () => {
    // DesignSystem §3. Resolved from the compiled stylesheet through the
    // `--hit-target` token, so this measures what ships rather than restating
    // the class list each component was written with.
    render(
      <div>
        <Button rank="filled">Connect a source</Button>
        <Button rank="tinted">Browse knowledge</Button>
        <Button rank="plain">Cancel</Button>
        <ThemeToggle />
      </div>,
    );

    const targets = Array.from(document.body.querySelectorAll(INTERACTIVE));
    expect(targets.length).toBeGreaterThanOrEqual(6);

    for (const target of targets) {
      const minHeight = resolvedPx(target, "min-height");
      const minWidth = resolvedPx(target, "min-width");
      const label = target.textContent || target.getAttribute("aria-label") || "(unnamed)";

      expect(minHeight, `${label}: no resolvable min-height`).not.toBeNull();
      expect(minWidth, `${label}: no resolvable min-width`).not.toBeNull();
      expect(minHeight as number, `${label}: min-height`).toBeGreaterThanOrEqual(44);
      expect(minWidth as number, `${label}: min-width`).toBeGreaterThanOrEqual(44);
    }
  });
});
