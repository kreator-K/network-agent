"use client";

import Link from "next/link";
import { useActionState } from "react";
import { freezePublishRequest, type FreezeState } from "./actions";

const initialState: FreezeState = { error: "" };

export function FreezeRequestForm({ postId }: Readonly<{ postId: number }>) {
  const [state, action, pending] = useActionState(freezePublishRequest, initialState);
  return <div className="freezeTool">
    <form action={action}>
      <input type="hidden" name="post_id" value={postId} />
      <button className="secondaryAction" type="submit" disabled={pending}>{pending ? "Freezing…" : "Create frozen preview"}</button>
      <small>This does not contact LinkedIn.</small>
    </form>
    {state.error ? <p className="formError" role="alert">{state.error}</p> : null}
    {state.requestId ? <div className="frozenNotice">
      <strong>Frozen request #{state.requestId}</strong>
      <span>Payload fingerprint {state.fingerprint}</span>
      <p>{state.commentary}</p>
      <Link href="/publishing">Review and explicitly confirm →</Link>
    </div> : null}
  </div>;
}
