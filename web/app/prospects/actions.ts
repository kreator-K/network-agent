"use server";

import { revalidatePath } from "next/cache";
import { addProspect, draftFollowup, draftOutreach } from "@/lib/api";
import { requireSession } from "@/lib/session";

export type DraftState = {
  draftText: string;
  error: string;
  interactionId?: number;
};

const emptyDraftState: DraftState = { draftText: "", error: "" };

export async function createProspect(formData: FormData) {
  await requireSession();
  const name = textValue(formData, "name");
  if (!name) return;
  await addProspect({
    name,
    profile_url: textValue(formData, "profile_url"),
    role_title: textValue(formData, "role_title"),
    company: textValue(formData, "company"),
    location: textValue(formData, "location"),
    notes: textValue(formData, "notes"),
  });
  revalidatePath("/prospects");
}

export async function createOutreachDraft(
  _previous: DraftState = emptyDraftState,
  formData: FormData,
): Promise<DraftState> {
  await requireSession();
  const prospectId = positiveInteger(formData, "prospect_id");
  const askType = textValue(formData, "ask_type");
  if (!prospectId || !["resume_review", "career_guidance", "general_chat"].includes(askType)) {
    return { draftText: "", error: "Choose a valid outreach goal." };
  }
  const result = await draftOutreach(prospectId, askType);
  if (!result) return { draftText: "", error: "The draft could not be created." };
  return {
    draftText: result.draft.draft_text,
    error: "",
    interactionId: result.draft_interaction_id,
  };
}

export async function createFollowupDraft(
  _previous: DraftState = emptyDraftState,
  formData: FormData,
): Promise<DraftState> {
  await requireSession();
  const prospectId = positiveInteger(formData, "prospect_id");
  if (!prospectId) return { draftText: "", error: "Invalid prospect." };
  const result = await draftFollowup(prospectId);
  if (!result) return { draftText: "", error: "The follow-up draft could not be created." };
  return {
    draftText: result.draft.draft_text,
    error: "",
    interactionId: result.draft_interaction_id,
  };
}

function textValue(formData: FormData, key: string): string {
  return String(formData.get(key) || "").trim();
}

function positiveInteger(formData: FormData, key: string): number | null {
  const value = Number(formData.get(key));
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}
