"use server";

import { revalidatePath } from "next/cache";
import { generateContentPackage, recordOpportunityFeedback } from "@/lib/api";
import { requireSession } from "@/lib/session";

export async function createDraftPackage(formData: FormData) {
  await requireSession();
  const opportunityId = Number(formData.get("opportunity_id"));
  if (!Number.isSafeInteger(opportunityId) || opportunityId < 1) return;
  await generateContentPackage(opportunityId);
  revalidatePath("/opportunities");
  revalidatePath("/studio");
}

export async function opportunityFeedback(formData: FormData) {
  await requireSession();
  const opportunityId = Number(formData.get("opportunity_id"));
  const feedbackType = String(formData.get("feedback_type") || "");
  if (!Number.isSafeInteger(opportunityId) || opportunityId < 1 || !["good_angle", "too_generic", "not_relevant"].includes(feedbackType)) return;
  await recordOpportunityFeedback(opportunityId, feedbackType);
  revalidatePath("/opportunities");
}
