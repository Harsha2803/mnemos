"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash2, Clock3, Wrench } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  decideToolInvocation,
  discoverTools,
  fetchToolInvocations,
  fetchTools,
  fetchToolServers,
  grantToolToSelf,
  proposeToolInvocation,
  registerToolServer,
  saveToolCredential,
  TOOL_INVOCATIONS_QUERY_KEY,
  TOOL_SERVERS_QUERY_KEY,
  TOOLS_QUERY_KEY,
  type McpTool,
  type ToolInvocation,
} from "@/lib/tools/api";

const INPUT = "hit-target w-full rounded-md border border-separator bg-bg px-3 text-callout text-label outline-none focus-visible:ring-2 focus-visible:ring-accent";

export default function ToolsPage() {
  const queryClient = useQueryClient();
  const servers = useQuery({ queryKey: TOOL_SERVERS_QUERY_KEY, queryFn: ({ signal }) => fetchToolServers(signal) });
  const tools = useQuery({ queryKey: TOOLS_QUERY_KEY, queryFn: ({ signal }) => fetchTools(signal) });
  const invocations = useQuery({ queryKey: TOOL_INVOCATIONS_QUERY_KEY, queryFn: ({ signal }) => fetchToolInvocations(signal) });
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: TOOL_SERVERS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: TOOLS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: TOOL_INVOCATIONS_QUERY_KEY }),
    ]);
  };

  const pending = useMemo(
    () => (invocations.data ?? []).filter((item) => item.status === "pending_approval"),
    [invocations.data],
  );

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-large-title font-semibold tracking-title text-label">Tools</h1>
        <p className="text-callout leading-relaxed text-label-secondary">
          Register one MCP server, cache its catalog, grant it to yourself, and inspect every
          proposal, approval, denial, result, and failure. Credentials are stored per user.
        </p>
      </header>

      {notice !== null && <p role="status" className="rounded-md bg-fill-secondary px-4 py-3 text-callout">{notice}</p>}

      <RegisterServer onComplete={(message) => { setNotice(message); void refresh(); }} />

      <section className="flex flex-col gap-3" aria-labelledby="servers-heading">
        <h2 id="servers-heading" className="text-title-3 font-semibold tracking-title">Registered servers</h2>
        {servers.isPending ? <LoadingRows /> : (servers.data?.length ?? 0) === 0 ? (
          <EmptyState icon={Wrench} title="No MCP server registered" description="Use the form above to register the local demo server." headingLevel={3} />
        ) : (
          <div className="list-group">
            {servers.data?.map((server) => (
              <ServerRow key={server.id} server={server} onComplete={(message) => { setNotice(message); void refresh(); }} />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3" aria-labelledby="catalog-heading">
        <h2 id="catalog-heading" className="text-title-3 font-semibold tracking-title">Discovered catalog</h2>
        {(tools.data?.length ?? 0) === 0 ? (
          <p className="text-callout text-label-secondary">Discover a registered server to cache its tools here.</p>
        ) : (
          <div className="grid gap-3">
            {tools.data?.map((tool) => <ToolCard key={tool.id} tool={tool} onComplete={(message) => { setNotice(message); void refresh(); }} />)}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3" aria-labelledby="approvals-heading">
        <h2 id="approvals-heading" className="text-title-3 font-semibold tracking-title">Awaiting approval</h2>
        {pending.length === 0 ? (
          <p className="text-callout text-label-secondary">No tool call is waiting for your decision.</p>
        ) : pending.map((invocation) => (
          <ApprovalRow key={invocation.id} invocation={invocation} onComplete={(message) => { setNotice(message); void refresh(); }} />
        ))}
      </section>

      <section className="flex flex-col gap-3" aria-labelledby="history-heading">
        <h2 id="history-heading" className="text-title-3 font-semibold tracking-title">Invocation history</h2>
        {invocations.isPending ? <LoadingRows /> : (invocations.data?.length ?? 0) === 0 ? (
          <p className="text-callout text-label-secondary">Proposals and results will appear here.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {invocations.data?.map((invocation) => <HistoryRow key={invocation.id} invocation={invocation} />)}
          </div>
        )}
      </section>
    </div>
  );
}

function RegisterServer({ onComplete }: { onComplete: (message: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: registerToolServer,
    onSuccess: () => { setError(null); onComplete("Server registered. Discover it below."); },
    onError: (caught: Error) => setError(caught.message),
  });

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    mutation.mutate({
      slug: String(data.get("slug")),
      name: String(data.get("name")),
      endpoint: String(data.get("endpoint")),
      description: "Deterministic local MCP fixture",
      min_trust_tier: 20,
      requires_approval: true,
    });
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby="register-tool-heading">
      <h2 id="register-tool-heading" className="text-title-3 font-semibold tracking-title">Register a server</h2>
      <form onSubmit={submit} className="grid gap-3 rounded-lg bg-bg-secondary p-4 md:grid-cols-3">
        <label className="flex flex-col gap-1 text-footnote font-semibold">Slug<input className={INPUT} name="slug" defaultValue="demo" required /></label>
        <label className="flex flex-col gap-1 text-footnote font-semibold">Name<input className={INPUT} name="name" defaultValue="Mnemos demo" required /></label>
        <label className="flex flex-col gap-1 text-footnote font-semibold">Streamable HTTP endpoint<input className={INPUT} name="endpoint" defaultValue="http://demo-mcp:8100/mcp" required /></label>
        <div className="md:col-span-3"><Button type="submit" rank="filled" disabled={mutation.isPending}>Register server</Button></div>
      </form>
      {error !== null && <p role="alert" className="text-callout text-danger">{error}</p>}
    </section>
  );
}

function ServerRow({ server, onComplete }: { server: Awaited<ReturnType<typeof fetchToolServers>>[number]; onComplete: (message: string) => void }) {
  const [scheme, setScheme] = useState<"none" | "bearer" | "api_key">("none");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const discover = useMutation({ mutationFn: () => discoverTools(server.id), onSuccess: (items) => { setError(null); onComplete(`Discovered ${items.length} tool${items.length === 1 ? "" : "s"}.`); }, onError: (caught: Error) => setError(caught.message) });
  const credential = useMutation({ mutationFn: () => saveToolCredential(server.id, scheme, secret), onSuccess: () => { setError(null); setSecret(""); onComplete("Your credential was encrypted and saved."); }, onError: (caught: Error) => setError(caught.message) });

  return (
    <div className="list-row flex flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1"><p className="font-semibold">{server.name}</p><p className="truncate text-footnote text-label-secondary">{server.endpoint}</p></div>
        <span className="text-footnote text-label-secondary">{server.credential_configured ? "Credential configured" : "No credential"}</span>
        <Button rank="tinted" onClick={() => discover.mutate()} disabled={discover.isPending}>Discover</Button>
      </div>
      <div className="grid gap-2 md:grid-cols-[10rem_minmax(0,1fr)_auto]">
        <label className="flex flex-col gap-1 text-footnote font-semibold">Credential scheme<select className={INPUT} value={scheme} onChange={(event) => setScheme(event.target.value as typeof scheme)}><option value="none">None</option><option value="bearer">Bearer</option><option value="api_key">API key</option></select></label>
        <label className="flex flex-col gap-1 text-footnote font-semibold">Secret<input className={INPUT} type="password" value={secret} onChange={(event) => setSecret(event.target.value)} disabled={scheme === "none"} autoComplete="off" /></label>
        <Button className="self-end" onClick={() => credential.mutate()} disabled={credential.isPending}>Save for me</Button>
      </div>
      {error !== null && <p role="alert" className="text-callout text-danger">{error}</p>}
    </div>
  );
}

function ToolCard({ tool, onComplete }: { tool: McpTool; onComplete: (message: string) => void }) {
  const [value, setValue] = useState("Hello from the Tool console");
  const [error, setError] = useState<string | null>(null);
  const argumentName = firstStringArgument(tool) ?? "message";
  const grant = useMutation({ mutationFn: () => grantToolToSelf(tool.id), onSuccess: () => { setError(null); onComplete(`Granted ${tool.name} to your live identity.`); }, onError: (caught: Error) => setError(caught.message) });
  const invoke = useMutation({ mutationFn: () => proposeToolInvocation(tool.id, argumentName, value), onSuccess: (record) => { setError(null); onComplete(record.status === "pending_approval" ? "Invocation proposed and waiting below." : `Invocation ${record.status}.`); }, onError: (caught: Error) => setError(caught.message) });

  return (
    <article className="flex flex-col gap-3 rounded-lg bg-bg-secondary p-4">
      <div><h3 className="text-headline font-semibold">{tool.name}</h3><p className="text-footnote text-label-secondary">{tool.description ?? "No description"} · {tool.is_mutating ? "Mutating" : "Read-only"}</p></div>
      <label className="flex flex-col gap-1 text-footnote font-semibold">{argumentName}<input className={INPUT} value={value} onChange={(event) => setValue(event.target.value)} /></label>
      <div className="flex flex-wrap gap-2"><Button onClick={() => grant.mutate()} disabled={grant.isPending}>Grant to me</Button><Button rank="filled" onClick={() => invoke.mutate()} disabled={invoke.isPending}>Propose call</Button></div>
      {error !== null && <p role="alert" className="text-callout text-danger">{error}</p>}
    </article>
  );
}

function ApprovalRow({ invocation, onComplete }: { invocation: ToolInvocation; onComplete: (message: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({ mutationFn: (decision: "approve" | "deny") => decideToolInvocation(invocation.id, decision), onSuccess: (record) => { setError(null); onComplete(`Invocation ${record.status}.`); }, onError: (caught: Error) => setError(caught.message) });
  return <article className="flex flex-col gap-3 rounded-lg border border-separator bg-bg-secondary p-4"><div className="flex items-center gap-2"><Clock3 className="size-5 text-warning" aria-hidden="true" /><h3 className="font-semibold">Proposed call</h3></div><pre className="overflow-x-auto text-footnote text-label-secondary">{JSON.stringify(invocation.arguments, null, 2)}</pre><div className="flex gap-2"><Button rank="filled" onClick={() => mutation.mutate("approve")}>Approve and run</Button><Button onClick={() => mutation.mutate("deny")}>Deny</Button></div>{error !== null && <p role="alert" className="text-callout text-danger">{error}</p>}</article>;
}

function HistoryRow({ invocation }: { invocation: ToolInvocation }) {
  const denied = invocation.status === "denied";
  const succeeded = invocation.status === "succeeded";
  const Icon = denied ? CircleSlash2 : succeeded ? CheckCircle2 : Clock3;
  return <article className="flex gap-3 rounded-md bg-bg-secondary p-4"><Icon className={denied ? "size-5 shrink-0 text-danger" : succeeded ? "size-5 shrink-0 text-success" : "size-5 shrink-0 text-warning"} aria-hidden="true" /><div className="min-w-0"><p className="font-semibold capitalize">{invocation.status.replace("_", " ")}</p><p className="text-footnote text-label-secondary">Trust tier {invocation.caller_trust_tier} · {new Date(invocation.created_at).toLocaleString()}</p>{invocation.offending_source !== null && <p className="text-callout text-danger">Denied because retrieved source “{invocation.offending_source}” did not have enough authority.</p>}{invocation.denied_reason !== null && invocation.offending_source === null && <p className="text-callout text-danger">Reason: {invocation.denied_reason}</p>}{succeeded && <pre className="mt-2 overflow-x-auto text-footnote">{JSON.stringify(invocation.result, null, 2)}</pre>}{invocation.error_code !== null && <p className="text-callout text-danger">Failure: {invocation.error_code}</p>}</div></article>;
}

function firstStringArgument(tool: McpTool): string | null {
  const required = tool.input_schema.required;
  const properties = tool.input_schema.properties;
  if (!Array.isArray(required) || required.length !== 1 || typeof required[0] !== "string" || typeof properties !== "object" || properties === null) return null;
  const schema = (properties as Record<string, unknown>)[required[0]];
  return typeof schema === "object" && schema !== null && (schema as Record<string, unknown>).type === "string" ? required[0] : null;
}

function LoadingRows() {
  return <div className="flex flex-col gap-2" aria-hidden="true"><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div>;
}

