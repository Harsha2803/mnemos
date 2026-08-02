import { SystemStatus } from "@/components/shell/SystemStatus";
import { API_BASE_URL } from "@/lib/api/client";

export default function OverviewPage() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-large-title font-semibold tracking-title text-label">Overview</h1>
        <p className="text-callout leading-relaxed text-label-secondary">
          Mnemos is an AI workspace whose context is a compiled artifact. Every answer
          carries an inspectable bundle — what was admitted, what was excluded and why —
          and a memory layer that distinguishes current facts from superseded ones.
        </p>
      </header>

      <section className="flex flex-col gap-3" aria-labelledby="system-status-heading">
        <div className="flex flex-col gap-1">
          <h2 id="system-status-heading" className="text-title-3 font-semibold tracking-title">
            System
          </h2>
          <p className="text-footnote text-label-secondary">
            Live from <code className="font-mono">{API_BASE_URL}/readyz</code>, through the
            client generated from the API&rsquo;s own OpenAPI document.
          </p>
        </div>
        <SystemStatus />
      </section>
    </div>
  );
}
