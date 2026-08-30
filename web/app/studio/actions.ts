"use server";

import { revalidatePath } from "next/cache";
import { approveContentPackage, createContentPackage, preparePublishRequest, reviseContentPackage, selectContentVariant } from "@/lib/api";
import { requireSession } from "@/lib/session";

export type FreezeState = {
  requestId?: number;
  fingerprint?: string;
  commentary?: string;
  error: string;
};

export type CreatePostState = { error: string; created: boolean };

const allowedImageTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const maxImageBytes = 10 * 1024 * 1024;

export async function createPost(
  _previous: CreatePostState,
  formData: FormData,
): Promise<CreatePostState> {
  await requireSession();
  const topic = String(formData.get("topic") || "").trim();
  if (!topic) return { error: "Add a topic for the post.", created: false };
  const resourceId = positiveInteger(formData.get("research_resource_id"));
  const image = formData.get("image");
  let imageBase64: string | undefined;
  let imageType: "image/jpeg" | "image/png" | "image/webp" | undefined;
  if (image instanceof File && image.size > 0) {
    if (!allowedImageTypes.has(image.type)) {
      return { error: "Upload a JPEG, PNG, or WebP image.", created: false };
    }
    if (image.size > maxImageBytes) {
      return { error: "The image must be 10 MB or smaller.", created: false };
    }
    imageBase64 = Buffer.from(await image.arrayBuffer()).toString("base64");
    imageType = image.type as "image/jpeg" | "image/png" | "image/webp";
  }
  const created = await createContentPackage({
    topic,
    inspiration_notes: String(formData.get("inspiration_notes") || "").trim() || undefined,
    research_resource_id: resourceId || undefined,
    image_base64: imageBase64,
    image_content_type: imageType,
    overlay_text: String(formData.get("overlay_text") || "").trim() || undefined,
    image_alt_text: String(formData.get("image_alt_text") || "").trim() || undefined,
    generate_image: formData.get("generate_image") === "on",
  });
  if (!created) {
    return { error: "The content package could not be created. Make sure the selected research brief is ready.", created: false };
  }
  revalidatePath("/studio");
  return { error: "", created: true };
}

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
