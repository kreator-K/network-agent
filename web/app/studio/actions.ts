"use server";

import { revalidatePath } from "next/cache";
import { approveContentPackage, preparePublishRequest, reviseContentPackage, selectContentVariant } from "@/lib/api";
import { requireSession } from "@/lib/session";

export type FreezeState = {
  requestId?: number;
  fingerprint?: string;
  commentary?: string;
  error: string;
};

export async function approvePackage(formData: FormData) {
  await requireSession();
  const postId = positiveInteger(formData.get("post_id"));
  if (!postId) return;
  await approveContentPackage(postId);
  revalidatePath("/studio");
}

export async function revisePackage(formData: FormData) {
  await requireSession();
  const postId = positiveInteger(formData.get("post_id"));
  const revisionType = String(formData.get("revision_type") || "");
  const revisionNotes = String(formData.get("revision_notes") || "").trim();
  if (!postId || !revisionType) return;
  await reviseContentPackage(postId, revisionType, revisionNotes);
  revalidatePath("/studio");
}

export async function chooseVariant(formData: FormData) {
  await requireSession();
  const postId = positiveInteger(formData.get("post_id"));
  const variantNumber = positiveInteger(formData.get("variant_number"));
  if (!postId || !variantNumber || variantNumber > 3) return;
  await selectContentVariant(postId, variantNumber);
  revalidatePath("/studio");
}

export async function freezePublishRequest(
  _previous: FreezeState,
  formData: FormData,
): Promise<FreezeState> {
  await requireSession();
  const postId = positiveInteger(formData.get("post_id"));
  if (!postId) return { error: "Invalid content package." };
  const request = await preparePublishRequest(postId);
  if (!request) return { error: "The frozen publish preview could not be created." };
  revalidatePath("/publishing");
  return {
    requestId: request.request_id,
    fingerprint: request.payload_fingerprint,
    commentary: request.commentary,
    error: "",
  };
}

function positiveInteger(value: FormDataEntryValue | null): number | null {
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : null;
}
