"use client";

import { useActionState } from "react";
import { meetingAction, type MeetingState } from "./actions";

const initialState: MeetingState = { message: "", error: "" };

export function MeetingForm({ prospectId }: Readonly<{ prospectId: number }>) {
  const [state, action, pending] = useActionState(meetingAction, initialState);
  return <div className="meetingTool">
    {!state.preview ? <form action={action} className="meetingForm">
      <input type="hidden" name="prospect_id" value={prospectId} />
      <label>Date<input name="meeting_date" type="date" required /></label>
      <label>Start<input name="start_time" type="time" required /></label>
      <label>End<input name="end_time" type="time" /></label>
      <label>Timezone<input name="timezone" defaultValue="America/New_York" required /></label>
      <label>Notes<input name="notes" maxLength={2000} /></label>
      <button className="secondaryAction" type="submit" name="operation" value="preview" disabled={pending}>{pending ? "Checking…" : "Preview meeting"}</button>
    </form> : <div className="meetingPreview">
      <strong>{state.preview.meetingDate} at {state.preview.startTime}{state.preview.endTime ? `–${state.preview.endTime}` : ""}</strong>
      <span>{state.preview.timezone}</span>
      {state.preview.notes ? <p>{state.preview.notes}</p> : null}
      <small>{state.message}</small>
      <form action={action}>
        <input type="hidden" name="prospect_id" value={prospectId} />
        <input type="hidden" name="meeting_date" value={state.preview.meetingDate} />
        <input type="hidden" name="start_time" value={state.preview.startTime} />
        <input type="hidden" name="end_time" value={state.preview.endTime} />
        <input type="hidden" name="timezone" value={state.preview.timezone} />
        <input type="hidden" name="notes" value={state.preview.notes} />
        <input type="hidden" name="confirmation" value="MEETING_CONFIRMED" />
        <button className="primaryAction" type="submit" name="operation" value="confirm" disabled={pending}>Explicitly confirm meeting</button>
      </form>
    </div>}
    {state.error ? <p className="formError" role="alert">{state.error}</p> : null}
    {!state.preview && state.message ? <p className="formSuccess" role="status">{state.message}</p> : null}
  </div>;
}
