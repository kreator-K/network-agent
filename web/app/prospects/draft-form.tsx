"use client";

import { useActionState } from "react";
import { createFollowupDraft, createOutreachDraft, type DraftState } from "./actions";

const initialState: DraftState = { draftText: "", error: "" };

export function OutreachDraftForm({ prospectId }: Readonly<{ prospectId: number }>) {
  const [state, action, pending] = useActionState(createOutreachDraft, initialState);
  return <div className="draftTool">
    <form action={action}>
      <input type="hidden" name="prospect_id" value={prospectId} />
      <label htmlFor={`ask-${prospectId}`}>Connection goal</label>
      <select id={`ask-${prospectId}`} name="ask_type" defaultValue="career_guidance">
        <option value="career_guidance">Career guidance</option>
        <option value="resume_review">Resume review</option>
        <option value="general_chat">General chat</option>
      </select>
      <button className="secondaryAction" type="submit" disabled={pending}>{pending ? "Drafting…" : "Draft connection note"}</button>
    </form>
    <DraftOutput state={state} />
  </div>;
}

export function FollowupDraftForm({ prospectId }: Readonly<{ prospectId: number }>) {
  const [state, action, pending] = useActionState(createFollowupDraft, initialState);
  return <div className="draftTool">
    <form action={action}>
      <input type="hidden" name="prospect_id" value={prospectId} />
      <button className="secondaryAction" type="submit" disabled={pending}>{pending ? "Drafting…" : "Draft follow-up"}</button>
    </form>
    <DraftOutput state={state} />
  </div>;
}

function DraftOutput({ state }: Readonly<{ state: DraftState }>) {
  if (state.error) return <p className="formError" role="alert">{state.error}</p>;
  if (!state.draftText) return null;
  return <div className="draftOutput">
    <span>Draft only · copy and send manually</span>
    <p>{state.draftText}</p>
    <small>Saved as interaction #{state.interactionId}</small>
  </div>;
}
