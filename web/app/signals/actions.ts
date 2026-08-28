"use server";

import { revalidatePath } from "next/cache";
import { addSignalSource, approveSignalSource, recordSignalFeedback, rejectSignalSource, scanSignals, setSignalSourceEnabled } from "@/lib/api";
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

export async function createSignalSource(formData: FormData) {
  await requireSession();
  const name = String(formData.get("name") || "").trim();
  const url = String(formData.get("url") || "").trim();
  const sourceType = String(formData.get("source_type") || "auto_feed");
  if (!name || !url) return;
  await addSignalSource({ name, url, source_type: sourceType });
  revalidatePath("/signals");
}

export async function sourceDecision(formData: FormData) {
  await requireSession();
  const sourceId = Number(formData.get("source_id"));
  const action = String(formData.get("source_action") || "");
  if (!Number.isSafeInteger(sourceId) || sourceId < 1) return;
  if (action === "approve") await approveSignalSource(sourceId);
  else if (action === "reject") await rejectSignalSource(sourceId);
  else if (action === "enable") await setSignalSourceEnabled(sourceId, true);
  else if (action === "disable") await setSignalSourceEnabled(sourceId, false);
  revalidatePath("/signals");
}
