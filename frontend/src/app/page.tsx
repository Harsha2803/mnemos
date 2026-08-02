export default function OverviewPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-large-title font-semibold tracking-title text-label">Overview</h1>
        <p className="text-callout leading-relaxed text-label-secondary">
          Mnemos is an AI workspace whose context is a compiled artifact. Every answer
          carries an inspectable bundle — what was admitted, what was excluded and why —
          and a memory layer that distinguishes current facts from superseded ones.
        </p>
      </header>
    </div>
  );
}
