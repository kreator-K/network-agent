"use client";

import { useActionState } from "react";
import { actOnPublishRequest, type PublishState } from "./actions";

const initialState: PublishState = { message: "", error: "" };

export function PublishRequestControls({ requestId }: Readonly<{ requestId: number }>) {
  const [state, action, pending] = useActionState(actOnPublishRequest, initialState);
  return <div className="publishControls">
    <form action={action}>
      <input type="hidden" name="request_id" value={requestId} />
      <input type="hidden" name="confirmation" value="CONFIRM_PUBLISH" />
      <button className="dangerAction" type="submit" name="operation" value="confirm" disabled={pending}>Confirm exact frozen payload</button>
    </form>
    <form action={action}>
      <input type="hidden" name="request_id" value={requestId} />
      <input type="hidden" name="confirmation" value="CANCEL_PUBLISH" />
      <button className="secondaryAction" type="submit" name="operation" value="cancel" disabled={pending}>Cancel request</button>
    </form>
    {state.error ? <p className="formError" role="alert">{state.error}</p> : null}
    {state.message ? <p className="formSuccess" role="status">{state.message}</p> : null}
  </div>;
}
