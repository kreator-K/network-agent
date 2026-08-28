"use client";

import { useActionState } from "react";
import { beginLinkedInAuthorization, type AuthorizationState } from "./actions";

const initialState: AuthorizationState = { message: "", error: "" };

export function LinkedInConnection() {
  const [state, action, pending] = useActionState(beginLinkedInAuthorization, initialState);
  return <div className="connectionTool">
    <form action={action}>
      <button className="primaryAction" type="submit" disabled={pending}>{pending ? "Preparing…" : "Connect LinkedIn"}</button>
    </form>
    {state.error ? <p className="formError" role="alert">{state.error}</p> : null}
    {state.authorizationUrl ? <div className="authorizationNotice">
      <p>{state.message}</p>
      <a href={state.authorizationUrl}>Continue to LinkedIn authorization →</a>
      <small>Requested scopes: OpenID identity, profile, and member posting. Authorization alone never publishes.</small>
    </div> : null}
  </div>;
}
