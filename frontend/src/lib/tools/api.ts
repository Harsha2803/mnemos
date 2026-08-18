import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ToolServer = components["schemas"]["ServerResponse"];
export type McpTool = components["schemas"]["ToolResponse"];
export type ToolInvocation = components["schemas"]["InvocationResponse"];
export type RegisterToolServer = components["schemas"]["RegisterServerRequest"];

export const TOOL_SERVERS_QUERY_KEY = ["tools", "servers"] as const;
export const TOOLS_QUERY_KEY = ["tools", "catalog"] as const;
export const TOOL_INVOCATIONS_QUERY_KEY = ["tools", "invocations"] as const;

export async function fetchToolServers(signal?: AbortSignal): Promise<ToolServer[]> {
  const { data, error } = await api.GET("/api/v1/tools/servers", { signal });
  if (error !== undefined) throw new Error(message(error, "could not load tool servers"));
  return data;
}

export async function registerToolServer(body: RegisterToolServer): Promise<ToolServer> {
  const { data, error } = await api.POST("/api/v1/tools/servers", { body });
  if (error !== undefined) throw new Error(message(error, "could not register this server"));
  return data;
}

export async function saveToolCredential(
  serverId: string,
  scheme: "none" | "bearer" | "api_key",
  secret: string,
): Promise<void> {
  const { error } = await api.PUT("/api/v1/tools/servers/{server_id}/credential", {
    params: { path: { server_id: serverId } },
    body: { scheme, secret },
  });
  if (error !== undefined) throw new Error(message(error, "could not save the credential"));
}

export async function discoverTools(serverId: string): Promise<McpTool[]> {
  const { data, error } = await api.POST("/api/v1/tools/servers/{server_id}/discover", {
    params: { path: { server_id: serverId } },
  });
  if (error !== undefined) throw new Error(message(error, "could not discover tools"));
  return data;
}

export async function fetchTools(signal?: AbortSignal): Promise<McpTool[]> {
  const { data, error } = await api.GET("/api/v1/tools", { signal });
  if (error !== undefined) throw new Error(message(error, "could not load tools"));
  return data;
}

export async function grantToolToSelf(toolId: string): Promise<void> {
  const { error } = await api.POST("/api/v1/tools/{tool_id}/grants/self", {
    params: { path: { tool_id: toolId } },
    body: { auto_approve: false },
  });
  if (error !== undefined) throw new Error(message(error, "could not grant this tool"));
}

export async function proposeToolInvocation(
  toolId: string,
  argumentName: string,
  value: string,
): Promise<ToolInvocation> {
  const { data, error } = await api.POST("/api/v1/tools/invocations", {
    body: { tool_id: toolId, arguments: { [argumentName]: value } },
  });
  if (error !== undefined) throw new Error(message(error, "could not propose this invocation"));
  return data;
}

export async function fetchToolInvocations(signal?: AbortSignal): Promise<ToolInvocation[]> {
  const { data, error } = await api.GET("/api/v1/tools/invocations", { signal });
  if (error !== undefined) throw new Error(message(error, "could not load invocation history"));
  return data;
}

export async function decideToolInvocation(
  invocationId: string,
  decision: "approve" | "deny",
): Promise<ToolInvocation> {
  const call = decision === "approve"
    ? api.POST("/api/v1/tools/invocations/{invocation_id}/approve", {
        params: { path: { invocation_id: invocationId } },
      })
    : api.POST("/api/v1/tools/invocations/{invocation_id}/deny", {
        params: { path: { invocation_id: invocationId } },
      });
  const { data, error } = await call;
  if (error !== undefined) throw new Error(message(error, `could not ${decision} this invocation`));
  return data;
}

function message(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "error" in error) {
    const inner = (error as { error?: { message?: unknown } }).error;
    if (typeof inner?.message === "string") return inner.message;
  }
  return fallback;
}

