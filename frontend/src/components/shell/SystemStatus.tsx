"use client";

import { AlertTriangle, CheckCircle2, CircleSlash } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { List, ListItem } from "@/components/ui/List";
import { Skeleton } from "@/components/ui/Skeleton";

import { useReadiness } from "./useReadiness";

/**
 * The dependencies the API reports on `/readyz`, one row each.
 *
 * The same query as the sidebar indicator, so the two cannot disagree and only
 * one request is in flight.
 */
export function SystemStatus() {
  const { data, isPending, isError, error } = useReadiness();

  if (isPending) {
    // Skeleton rows shaped like the rows that are coming, not a spinner over a
    // blank region (DesignSystem §4).
    return (
      <div role="group" aria-label="System status">
        <List label="Dependencies">
          {["one", "two"].map((key) => (
            <ListItem key={key} leading={<Skeleton className="size-4 rounded-full" />}>
              <Skeleton
                label={key === "one" ? "Loading dependency status" : undefined}
                className="h-3.5 w-28"
              />
            </ListItem>
          ))}
        </List>
      </div>
    );
  }

  if (isError) {
    return (
      <EmptyState
        icon={CircleSlash}
        title="The API is unreachable"
        description={`Nothing answered at ${error.message.includes("fetch") ? "the API address" : "readiness"}. The stack may still be starting: \`docker compose ps\` shows which service is not healthy yet.`}
        headingLevel={3}
      />
    );
  }

  return (
    <List label="Dependencies">
      {data.checks.map((check) => (
        <ListItem
          key={check.name}
          leading={
            check.ok ? (
              <CheckCircle2
                className="size-[18px] text-success"
                strokeWidth={1.5}
                aria-hidden="true"
              />
            ) : (
              <AlertTriangle
                className="size-[18px] text-danger"
                strokeWidth={1.5}
                aria-hidden="true"
              />
            )
          }
          // The API's own word, verbatim. A dependency that failed says how.
          trailing={check.detail}
        >
          {check.name}
        </ListItem>
      ))}
    </List>
  );
}
