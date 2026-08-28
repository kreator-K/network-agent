"use server";

import { revalidatePath } from "next/cache";
import { cancelPublishRequest, confirmPublishRequest, disconnectLinkedIn, startLinkedInAuthorization } from "@/lib/api";
import { requireSession } from "@/lib/session";

export type PublishState = { message: string; error: string };
export type AuthorizationState = { authorizationUrl?: string; message: string; error: string };

export async function beginLinkedInAuthorization(
  _previous: AuthorizationState,
): Promise<AuthorizationState> {
  await requireSession();
  const result = await startLinkedInAuthorization();
  if (!result) return { message: "", error: "LinkedIn authorization could not be started. Check server configuration." };
  return { authorizationUrl: result.authorization_url, message: result.message, error: "" };
}

export async function disconnectLinkedInAccount(formData: FormData) {
  await requireSession();
  if (String(formData.get("confirmation") || "") !== "DISCONNECT_LINKEDIN") return;
  await disconnectLinkedIn();
  revalidatePath("/publishing");
}

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
