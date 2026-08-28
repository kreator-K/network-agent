import { AppShell } from "@/components/app-shell";
import { getFollowupsDue, getProspects } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { createProspect } from "./actions";
import { FollowupDraftForm, OutreachDraftForm } from "./draft-form";

export default async function ProspectsPage() {
  await requireSession();
  const [prospects, followups] = await Promise.all([getProspects(), getFollowupsDue()]);
  const dueIds = new Set(followups.map((item) => item.prospect_id));

  return <AppShell><div className="page">
    <p className="eyebrow">Manual networking CRM</p>
    <h1>Prospects and draft review.</h1>
    <div className="crmGrid">
      <section className="panel intakePanel">
        <div className="panelTitle"><h2>Add a prospect</h2><span>Manual intake only</span></div>
        <form action={createProspect} className="prospectForm">
          <label>Name<input name="name" required maxLength={200} /></label>
          <label>LinkedIn profile URL<input name="profile_url" type="url" maxLength={1000} /></label>
          <label>Role<input name="role_title" maxLength={300} /></label>
          <label>Company<input name="company" maxLength={300} /></label>
          <label>Location<input name="location" maxLength={200} /></label>
          <label>Notes<textarea name="notes" maxLength={2000} rows={4} /></label>
          <button className="primaryAction" type="submit">Add to CRM</button>
        </form>
      </section>
      <section className="panel safetyPanel">
        <p className="eyebrow">Safety boundary</p>
        <h2>No automatic outreach</h2>
        <p>This workspace creates and saves drafts. You copy the text and send it yourself in LinkedIn. There is no connection-request or direct-message sending endpoint.</p>
        <strong>{followups.length} follow-up{followups.length === 1 ? "" : "s"} currently due</strong>
      </section>
    </div>
    <section className="panel prospectPanel">
      <div className="panelTitle"><h2>Prospect workspace</h2><span>{prospects.length} records</span></div>
      <div className="prospectList">{prospects.length ? prospects.map((prospect) => <article key={prospect.id}>
        <div className="prospectSummary">
          <span>{prospect.status.replaceAll("_", " ")}{dueIds.has(prospect.id) ? " · follow-up due" : ""}</span>
          <h2>{prospect.name}</h2>
          <p>{[prospect.role_title, prospect.company, prospect.location].filter(Boolean).join(" · ") || "Context not added yet"}</p>
          {prospect.notes ? <small>{prospect.notes}</small> : null}
        </div>
        <div className="prospectActions">
          <OutreachDraftForm prospectId={prospect.id} />
          {dueIds.has(prospect.id) ? <FollowupDraftForm prospectId={prospect.id} /> : null}
        </div>
      </article>) : <div className="empty"><strong>No prospects yet.</strong><p>Add the first prospect using manually supplied details.</p></div>}</div>
    </section>
  </div></AppShell>;
}
