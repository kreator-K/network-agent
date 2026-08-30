import { NextResponse } from "next/server";
import { hasValidSession } from "@/lib/session";

export async function GET(
  _request: Request,
  context: { params: Promise<{ postId: string }> },
) {
  if (!(await hasValidSession())) return new NextResponse("Unauthorized", { status: 401 });
  const { postId } = await context.params;
  if (!/^\d+$/.test(postId)) return new NextResponse("Not found", { status: 404 });
  const baseUrl = process.env.NETWORK_API_BASE_URL;
  const token = process.env.WEB_API_TOKEN;
  if (!baseUrl || !token) return new NextResponse("Unavailable", { status: 503 });
  const response = await fetch(`${baseUrl}/api/v1/content/${postId}/image`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) return new NextResponse("Not found", { status: 404 });
  return new NextResponse(await response.arrayBuffer(), {
    headers: {
      "Content-Type": response.headers.get("content-type") || "image/png",
      "Cache-Control": "private, max-age=300",
    },
  });
}
