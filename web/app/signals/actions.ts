"use server";
import { revalidatePath } from "next/cache";
import { addResearchResource } from "@/lib/api";
import { requireSession } from "@/lib/session";
export async function addResource(formData: FormData) { await requireSession(); const title = String(formData.get("title") || "").trim(); if (!title) return; await addResearchResource({ title, url: String(formData.get("url") || "").trim(), notes: String(formData.get("notes") || "").trim() }); revalidatePath("/signals"); }
