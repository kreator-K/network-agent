import { AppShell } from "@/components/app-shell";
import { getWorkflowRuns } from "@/lib/api";
import { requireSession } from "@/lib/session";

export default async function WorkflowsPage() {
  await requireSession();
  const runs = await getWorkflowRuns();
  return <AppShell><div className="page"><p className="eyebrow">Audit trail</p><h1>Workflow runs</h1><section className="panel"><div className="workflowList">{runs.length ? runs.map((run) => <article key={run.run_id}><div><span>{run.workflow_name} · v{run.workflow_version}</span><strong>{run.status}</strong><p>{new Date(run.started_at).toLocaleString()} · {run.node_count} nodes</p></div><code>{run.run_id.slice(0, 12)}</code></article>) : <div className="empty"><strong>No graph receipts yet.</strong><p>Receipts appear after an enabled graph workflow completes.</p></div>}</div></section></div></AppShell>;
}
