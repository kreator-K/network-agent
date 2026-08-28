import { NextRequest, NextResponse } from "next/server";
import { completeLinkedInAuthorization } from "@/lib/api";

export async function GET(request: NextRequest) {
  const allowed = ["code", "state", "error", "error_description"];
  const params = Object.fromEntries(
    allowed.flatMap((key) => {
      const value = request.nextUrl.searchParams.get(key);
      return value === null ? [] : [[key, value]];
    }),
  );
  const completed = await completeLinkedInAuthorization(params);
  const target = new URL(completed ? "/publishing?linkedin=connected" : "/publishing?linkedin=error", request.url);
  return NextResponse.redirect(target);
}
