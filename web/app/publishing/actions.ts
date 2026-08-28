"use server";

import { revalidatePath } from "next/cache";
import { cancelPublishRequest, confirmPublishRequest } from "@/lib/api";
import { requireSession } from "@/lib/session";

export type PublishState = { message: string; error: string };

export async function actOnPublishRequest(
  _previous: PublishState,
  formData: FormData,
): Promise<PublishState> {
  await requireSession();
  const requestId = Number(formData.get("request_id"));
  const operation = String(formData.get("operation") || "");
  if (!Number.isSafeInteger(requestId) || requestId < 1) return { message: "", error: "Invalid publish request." };

  if (operation === "confirm") {
    const confirmation = String(formData.get("confirmation") || "");
    if (confirmation !== "CONFIRM_PUBLISH") return { message: "", error: "Explicit confirmation is required." };
    const result = await confirmPublishRequest(requestId);
    if (!result) return { message: "", error: "Confirmation failed safely; inspect the audit state before retrying." };
    revalidatePath("/publishing");
    return { message: result.message || `Request status: ${result.status}`, error: "" };
  }

  if (operation === "cancel") {
    const confirmation = String(formData.get("confirmation") || "");
    if (confirmation !== "CANCEL_PUBLISH") return { message: "", error: "Explicit cancellation is required." };
    const result = await cancelPublishRequest(requestId);
    if (!result) return { message: "", error: "Cancellation could not be completed." };
    revalidatePath("/publishing");
    return { message: "Frozen request cancelled. Nothing was published.", error: "" };
  }
  return { message: "", error: "Unknown action." };
}
