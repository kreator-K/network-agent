import { getSignals } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { requireSession } from "@/lib/session";

export default async function Dashboard() {
  await requireSession();
  const signals = await getSignals();
  return <AppShell><div className="page">
      <header className="pageHeader">
        <div><p className="eyebrow">Workspace</p><h1>Build the right relationships.<br />Publish ideas with evidence.</h1></div>
        <span className="status"><i /> Approval-first</span>
      </header>
      <section className="metrics" aria-label="Workflow summary">
        <article><span>01</span><strong>Review signals</strong><p>Approved public sources only.</p></article>
        <article><span>02</span><strong>Shape the angle</strong><p>Research, hooks, carousel and caption.</p></article>
        <article><span>03</span><strong>You decide</strong><p>Nothing publishes without confirmation.</p></article>
      </section>
      <section className="panel">
        <div className="panelTitle"><div><p className="eyebrow">Latest evidence</p><h2>Signals ready for review</h2></div><span>{signals.length} visible</span></div>
        {signals.length ? (
          <div className="signalList">{signals.map((signal) => <article key={signal.id}><span>#{signal.id}</span><div><strong>{signal.title || "Untitled signal"}</strong><p>{signal.source_name || "Approved source"}</p></div><b>Review →</b></article>)}</div>
        ) : <div className="empty"><strong>No signals loaded yet.</strong><p>Connect the protected backend and approve an RSS or Atom source.</p></div>}
      </section>
    </div></AppShell>;
}
