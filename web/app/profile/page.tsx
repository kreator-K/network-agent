import { AppShell } from "@/components/app-shell";
import { getBrandProfile, getBrandProfileVersions } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { activateProfileVersion, editProfileField } from "./actions";

const fields = [
  ["professional_identity", "Professional identity"],
  ["content_pillars", "Content pillars (comma-separated)"],
  ["target_audiences", "Target audiences (comma-separated)"],
  ["preferred_tone", "Preferred tone (comma-separated)"],
  ["career_focus", "Career focus (comma-separated)"],
  ["verified_experiences", "Verified experiences (comma-separated)"],
  ["allowed_personal_claims", "Allowed personal claims (comma-separated)"],
  ["claims_requiring_confirmation", "Claims requiring confirmation (comma-separated)"],
  ["topics_to_avoid", "Topics to avoid (comma-separated)"],
] as const;

export default async function ProfilePage() {
  await requireSession();
  const [profile, versions] = await Promise.all([getBrandProfile(), getBrandProfileVersions()]);
  return <AppShell><div className="page">
    <p className="eyebrow">Human-controlled voice DNA</p>
    <h1>Personal-brand profile.</h1>
    <div className="profileGrid">
      <section className="panel">
        <div className="panelTitle"><h2>Active version</h2><span>{profile ? `v${profile.version}` : "not configured"}</span></div>
        {profile ? <div className="profileSummary">
          <strong>{profile.professional_identity}</strong>
          <p>{profile.current_program || "No current program recorded."}</p>
          <dl><dt>Content pillars</dt><dd>{profile.content_pillars?.join(", ") || "—"}</dd><dt>Audiences</dt><dd>{profile.target_audiences?.join(", ") || "—"}</dd><dt>Tone</dt><dd>{profile.preferred_tone?.join(", ") || "—"}</dd></dl>
        </div> : <div className="empty"><strong>No active profile.</strong><p>Initialize the versioned seed before editing fields.</p></div>}
      </section>
      <section className="panel">
        <div className="panelTitle"><h2>Create a field version</h2><span>Append-only</span></div>
        <form action={editProfileField} className="profileForm">
          <label>Field<select name="field_name">{fields.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>New value<textarea name="value" required maxLength={5000} rows={5} /></label>
          <button className="primaryAction" type="submit" disabled={!profile}>Save as new active version</button>
          <small>Edits never mutate old versions or core intent.</small>
        </form>
      </section>
    </div>
    <section className="panel">
      <div className="panelTitle"><h2>Version history</h2><span>Rollback by activation</span></div>
      <div className="profileVersions">{versions.map((version) => <article key={version.version}><div><span>Version {version.version}</span><strong>{version.professional_identity || "Profile version"}</strong><small>{new Date(version.created_at).toLocaleString()}</small></div>{version.is_active ? <em>Active</em> : <form action={activateProfileVersion}><input type="hidden" name="version" value={version.version} /><button className="secondaryAction" type="submit">Activate</button></form>}</article>)}</div>
    </section>
  </div></AppShell>;
}
