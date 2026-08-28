import "server-only";

export type Signal = {
  id: number;
  title: string | null;
  source_name?: string;
  status?: string;
};
export type Opportunity = { id: number; headline: string; suggested_angle?: string; status: string; total_score?: number };
export type WorkflowRun = { run_id: string; workflow_name: string; workflow_version: number; status: string; started_at: string; finished_at: string; node_count: number; failed_nodes: number };
export type Prospect = {
  id: number;
  name: string;
  profile_url: string | null;
  location: string | null;
  role_title: string | null;
  company: string | null;
  notes: string | null;
  status: string;
  last_touch_date: string | null;
};
export type FollowupDue = {
  prospect_id: number;
  name: string;
  days_since_last_touch?: number;
  due_reason?: string;
};
export type DraftResult = {
  draft: { draft_text: string; character_count?: number; ask_type?: string };
  context_warning?: { message?: string } | null;
  draft_interaction_id: number;
};
export type ContentPackage = {
  id: number;
  topic: string | null;
  draft_text: string;
  status: string;
  package_version: number;
  suggested_first_comment?: string | null;
};
export type LinkedInPublishStatus = {
  publishing_mode: string;
  real_publish_enabled: boolean;
  connection_status: string;
  pending_confirmations: number;
  real_publishing_available: boolean;
};
export type PublishRequest = {
  request_id: number;
  post_id: number;
  package_version: number;
  format: string;
  status: string;
  commentary: string;
  visibility: string;
  payload_fingerprint: string;
  assets: Array<{ path?: string; sha256?: string; role?: string }>;
  expires_at: string;
  reused?: boolean;
  safe_error_summary?: string | null;
};
export type PublishActionResult = {
  status: string;
  published?: boolean;
  message?: string;
  request_id?: number;
};
export type LinkedInAuthorization = {
  authorization_url: string;
  expires_at: string;
  scopes: string[];
  message: string;
};
export type MeetingPreview = {
  prospect_id: number;
  meeting_date: string;
  start_time: string;
  end_time: string | null;
  timezone: string;
  notes: string | null;
  calendar_action: false;
  confirmation_required: true;
};

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

export async function getProspects(): Promise<Prospect[]> {
  return apiRequest<Prospect[]>("/api/v1/prospects?limit=100", { method: "GET" }, []);
}

export async function getFollowupsDue(): Promise<FollowupDue[]> {
  return apiRequest<FollowupDue[]>("/api/v1/prospects/followups-due", { method: "GET" }, []);
}

export async function addProspect(input: {
  name: string;
  profile_url?: string;
  location?: string;
  role_title?: string;
  company?: string;
  notes?: string;
}): Promise<boolean> {
  const result = await apiRequest<unknown>("/api/v1/prospects", {
    method: "POST",
    body: JSON.stringify(input),
  }, null);
  return result !== null;
}

export async function draftOutreach(prospectId: number, askType: string): Promise<DraftResult | null> {
  return apiRequest<DraftResult | null>(`/api/v1/prospects/${prospectId}/outreach-draft`, {
    method: "POST",
    body: JSON.stringify({ ask_type: askType }),
  }, null);
}

export async function draftFollowup(prospectId: number): Promise<DraftResult | null> {
  return apiRequest<DraftResult | null>(`/api/v1/prospects/${prospectId}/followup-draft`, {
    method: "POST",
    body: JSON.stringify({}),
  }, null);
}

export async function getContentPackages(): Promise<ContentPackage[]> {
  return apiRequest<ContentPackage[]>("/api/v1/content", { method: "GET" }, []);
}

export async function approveContentPackage(postId: number): Promise<boolean> {
  const result = await apiRequest<unknown>(`/api/v1/content/${postId}/approve`, {
    method: "POST",
    body: JSON.stringify({}),
  }, null);
  return result !== null;
}

export async function preparePublishRequest(postId: number): Promise<PublishRequest | null> {
  return apiRequest<PublishRequest | null>("/api/v1/linkedin/publish-requests", {
    method: "POST",
    body: JSON.stringify({ post_id: postId }),
  }, null);
}

export async function getLinkedInPublishStatus(): Promise<LinkedInPublishStatus | null> {
  return apiRequest<LinkedInPublishStatus | null>("/api/v1/linkedin/status", { method: "GET" }, null);
}

export async function getPublishRequests(): Promise<PublishRequest[]> {
  return apiRequest<PublishRequest[]>("/api/v1/linkedin/publish-requests?limit=50", { method: "GET" }, []);
}

export async function confirmPublishRequest(requestId: number): Promise<PublishActionResult | null> {
  return apiRequest<PublishActionResult | null>(`/api/v1/linkedin/publish-requests/${requestId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ confirmation: "CONFIRM_PUBLISH" }),
  }, null);
}

export async function cancelPublishRequest(requestId: number): Promise<PublishActionResult | null> {
  return apiRequest<PublishActionResult | null>(`/api/v1/linkedin/publish-requests/${requestId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ confirmation: "CANCEL_PUBLISH" }),
  }, null);
}

export async function startLinkedInAuthorization(): Promise<LinkedInAuthorization | null> {
  return apiRequest<LinkedInAuthorization | null>("/api/v1/linkedin/authorization", {
    method: "POST",
    body: JSON.stringify({}),
  }, null);
}

export async function completeLinkedInAuthorization(params: Record<string, string>): Promise<boolean> {
  const query = new URLSearchParams(params);
  const result = await apiRequest<unknown>(`/api/v1/linkedin/callback?${query.toString()}`, { method: "GET" }, null);
  return result !== null;
}

export async function disconnectLinkedIn(): Promise<boolean> {
  const result = await apiRequest<unknown>("/api/v1/linkedin/disconnect", {
    method: "POST",
    body: JSON.stringify({ confirmation: "DISCONNECT_LINKEDIN" }),
  }, null);
  return result !== null;
}

export async function previewMeeting(prospectId: number, input: {
  meeting_date: string;
  start_time: string;
  end_time?: string;
  timezone?: string;
  notes?: string;
}): Promise<MeetingPreview | null> {
  return apiRequest<MeetingPreview | null>(`/api/v1/prospects/${prospectId}/meeting-preview`, {
    method: "POST",
    body: JSON.stringify(input),
  }, null);
}

export async function confirmMeeting(prospectId: number, input: {
  meeting_date: string;
  start_time: string;
  end_time?: string;
  timezone?: string;
  notes?: string;
}): Promise<boolean> {
  const result = await apiRequest<unknown>(`/api/v1/prospects/${prospectId}/meeting-confirmation`, {
    method: "POST",
    body: JSON.stringify({ ...input, confirmation: "MEETING_CONFIRMED" }),
  }, null);
  return result !== null;
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
