import "server-only";

export type Signal = {
  id: number;
  title: string | null;
  source_name?: string;
  status?: string;
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
