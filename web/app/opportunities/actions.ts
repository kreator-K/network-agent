"use server";

import { revalidatePath } from "next/cache";
import { generateContentPackage } from "@/lib/api";
import { requireSession } from "@/lib/session";

export async function createDraftPackage(formData: FormData) {
  await requireSession();
  const opportunityId = Number(formData.get("opportunity_id"));
  if (!Number.isSafeInteger(opportunityId) || opportunityId < 1) return;
  await generateContentPackage(opportunityId);
  revalidatePath("/opportunities");
  revalidatePath("/studio");
}
