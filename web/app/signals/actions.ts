"use server";

import { revalidatePath } from "next/cache";
import { recordSignalFeedback, scanSignals } from "@/lib/api";
import { requireSession } from "@/lib/session";

export async function runSignalScan() {
  await requireSession();
  await scanSignals();
  revalidatePath("/signals");
  revalidatePath("/");
}

export async function signalFeedback(formData: FormData) {
  await requireSession();
  const signalId = Number(formData.get("signal_id"));
  const feedbackType = String(formData.get("feedback_type") || "");
  if (!Number.isSafeInteger(signalId) || signalId < 1 || !["more_like_this", "less_like_this"].includes(feedbackType)) return;
  await recordSignalFeedback(signalId, feedbackType);
  revalidatePath("/signals");
}
