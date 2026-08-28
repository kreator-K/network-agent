import "server-only";

export type Signal = {
  id: number;
  title: string | null;
  source_name?: string;
  status?: string;
};
export type Opportunity = { id: number; headline: string; suggested_angle?: string; status: string; total_score?: number };
export type WorkflowRun = { run_id: string; workflow_name: string; workflow_version: number; status: string; started_at: string; finished_at: string; node_count: number; failed_nodes: number };

type ApiEnvelope<T> = { data: T };

const baseUrl = process.env.NETWORK_API_BASE_URL;
const token = process.env.WEB_API_TOKEN;

export async function getSignals(): Promise<Signal[]> {
  if (!baseUrl || !token) return [];
  const response = await fetch(`${baseUrl}/api/v1/signals?limit=5`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) return [];
  const payload = (await response.json()) as ApiEnvelope<Signal[]>;
  return payload.data;
}

export async function getOpportunities(): Promise<Opportunity[]> {
  return apiRequest<Opportunity[]>("/api/v1/opportunities?limit=20", { method: "GET" }, []);
}
export async function getWorkflowRuns(): Promise<WorkflowRun[]> {
  return apiRequest<WorkflowRun[]>("/api/v1/workflows?limit=30", { method: "GET" }, []);
}

export async function scanSignals(): Promise<boolean> {
  const result = await apiRequest<unknown>("/api/v1/signals/scan", {
    method: "POST",
    body: JSON.stringify({ graph_mode: "shadow" }),
  }, null);
  return result !== null;
}

export async function generateContentPackage(opportunityId: number): Promise<boolean> {
  const result = await apiRequest<unknown>(`/api/v1/opportunities/${opportunityId}/content-package`, {
    method: "POST",
    body: JSON.stringify({ image_mode: "disabled", graph_mode: "shadow" }),
  }, null);
  return result !== null;
}

async function apiRequest<T>(path: string, init: RequestInit, fallback: T): Promise<T> {
  if (!baseUrl || !token) return fallback;
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init.headers },
      cache: "no-store",
    });
    if (!response.ok) return fallback;
    const payload = (await response.json()) as ApiEnvelope<T>;
    return payload.data;
  } catch {
    return fallback;
  }
}
