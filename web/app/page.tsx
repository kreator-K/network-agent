import { AppShell } from "@/components/app-shell";
import { requireSession } from "@/lib/session";

export default async function Dashboard() {
  await requireSession();
  return <AppShell><div className="page">
      <header className="pageHeader">
        <div><p className="eyebrow">Workspace</p><h1>Build the right relationships.<br />Publish ideas with evidence.</h1></div>
        <span className="status"><i /> Approval-first</span>
      </header>
      <section className="metrics" aria-label="Workflow summary">
        <article><span>01</span><strong>Know your audience</strong><p>Use your own notes and experience.</p></article>
        <article><span>02</span><strong>Shape the angle</strong><p>Research, hooks, carousel and caption.</p></article>
        <article><span>03</span><strong>You decide</strong><p>Nothing publishes without confirmation.</p></article>
      </section>
    </div></AppShell>;
}
