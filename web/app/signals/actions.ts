"use server";
import { revalidatePath } from "next/cache";
import { addResearchResource, researchResource } from "@/lib/api";
import { requireSession } from "@/lib/session";
export async function addResource(formData: FormData) { await requireSession(); const title = String(formData.get("title") || "").trim(); if (!title) return; await addResearchResource({ title, url: String(formData.get("url") || "").trim(), notes: String(formData.get("notes") || "").trim(), source_text: String(formData.get("source_text") || "").trim() }); revalidatePath("/signals"); }
export async function runResearch(formData: FormData) { await requireSession(); const id = Number(formData.get("resource_id")); if (Number.isSafeInteger(id) && id > 0) await researchResource(id); revalidatePath("/signals"); }
