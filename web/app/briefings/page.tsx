import { AppShell } from "@/components/app-shell";
import { getBriefingRuns, getBriefingStatus } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { runBriefingDry } from "./actions";

export default async function BriefingsPage() {
  await requireSession();
  const [status, runs] = await Promise.all([getBriefingStatus(), getBriefingRuns()]);
  return <AppShell><div className="page">
    <div className="pageHeader"><div><p className="eyebrow">Operational preparation</p><h1>Briefings</h1></div><form action={runBriefingDry}><button className="primaryAction" type="submit">Run manual dry briefing</button></form></div>
    <div className="metrics"><article><span>Scheduler</span><strong>{status?.enabled ? "enabled" : "off"}</strong><p>Manual control remains available.</p></article><article><span>Configured time</span><strong>{status?.briefing_time || "—"}</strong><p>{status?.timezone || "No timezone"}</p></article><article><span>Safety mode</span><strong>Dry preparation</strong><p>No approval, outreach, calendar, or publish action.</p></article></div>
    <section className="panel"><div className="panelTitle"><h2>Run history</h2><span>{runs.length} receipts</span></div><div className="briefingList">{runs.length ? runs.map((run) => <article key={run.id}><div><span>Run #{run.id} · {run.run_type}</span><strong>{run.status.replaceAll("_", " ")}</strong><small>{run.completed_at ? new Date(run.completed_at).toLocaleString() : "Not completed"}</small></div><p>{run.new_signals_count || 0} signals · {run.opportunities_created_count || 0} opportunities · {run.packages_prepared_count || 0} packages · {run.followups_due_count || 0} follow-ups</p></article>) : <div className="empty"><strong>No briefing runs.</strong><p>Run a manual dry briefing when approved sources are ready.</p></div>}</div></section>
  </div></AppShell>;
}
