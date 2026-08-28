"use server";

import { revalidatePath } from "next/cache";
import { activateBrandProfile, updateBrandProfileField } from "@/lib/api";
import { requireSession } from "@/lib/session";

export async function editProfileField(formData: FormData) {
  await requireSession();
  const fieldName = String(formData.get("field_name") || "");
  const value = String(formData.get("value") || "").trim();
  if (!fieldName || value.length > 5000) return;
  await updateBrandProfileField(fieldName, value);
  revalidatePath("/profile");
}

export async function activateProfileVersion(formData: FormData) {
  await requireSession();
  const version = Number(formData.get("version"));
  if (!Number.isSafeInteger(version) || version < 1) return;
  await activateBrandProfile(version);
  revalidatePath("/profile");
}
