"use server";

import { revalidatePath } from "next/cache";
import { runDryBriefing } from "@/lib/api";
import { requireSession } from "@/lib/session";

export async function runBriefingDry() {
  await requireSession();
  await runDryBriefing();
  revalidatePath("/briefings");
  revalidatePath("/");
}
