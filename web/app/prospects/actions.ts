"use server";

import { revalidatePath } from "next/cache";
import { addProspect, confirmMeeting, draftFollowup, draftOutreach, previewMeeting } from "@/lib/api";
import { requireSession } from "@/lib/session";

export type DraftState = {
  draftText: string;
  error: string;
  interactionId?: number;
};
export type MeetingState = {
  preview?: {
    meetingDate: string;
    startTime: string;
    endTime: string;
    timezone: string;
    notes: string;
  };
  message: string;
  error: string;
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

export async function meetingAction(
  _previous: MeetingState,
  formData: FormData,
): Promise<MeetingState> {
  await requireSession();
  const prospectId = positiveInteger(formData, "prospect_id");
  if (!prospectId) return { message: "", error: "Invalid prospect." };
  const input = {
    meeting_date: textValue(formData, "meeting_date"),
    start_time: textValue(formData, "start_time"),
    end_time: textValue(formData, "end_time"),
    timezone: textValue(formData, "timezone"),
    notes: textValue(formData, "notes"),
  };
  if (String(formData.get("operation") || "") === "preview") {
    const preview = await previewMeeting(prospectId, input);
    if (!preview) return { message: "", error: "Meeting details are invalid or could not be previewed." };
    return {
      preview: {
        meetingDate: preview.meeting_date,
        startTime: preview.start_time,
        endTime: preview.end_time || "",
        timezone: preview.timezone,
        notes: preview.notes || "",
      },
      message: "Review these exact details. No calendar action has occurred.",
      error: "",
    };
  }
  if (
    String(formData.get("operation") || "") !== "confirm" ||
    String(formData.get("confirmation") || "") !== "MEETING_CONFIRMED"
  ) return { message: "", error: "Explicit meeting confirmation is required." };
  const confirmed = await confirmMeeting(prospectId, input);
  if (!confirmed) return { message: "", error: "Confirmation failed safely. Check calendar state before retrying." };
  revalidatePath("/prospects");
  return { message: "Meeting confirmed and calendar workflow completed.", error: "" };
}

function textValue(formData: FormData, key: string): string {
  return String(formData.get(key) || "").trim();
}

function positiveInteger(formData: FormData, key: string): number | null {
  const value = Number(formData.get(key));
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}
