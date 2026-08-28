import { AppShell } from "@/components/app-shell";
import { requireSession } from "@/lib/session";
export default async function SignalsPage() { await requireSession(); return <AppShell><Placeholder eyebrow="Evidence desk" title="Signals" copy="Scan approved sources, inspect provenance, and decide what deserves deeper analysis." /></AppShell>; }
function Placeholder({ eyebrow, title, copy }: { eyebrow: string; title: string; copy: string }) { return <div className="page"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><section className="panel placeholder"><h2>Workflow surface in progress</h2><p>{copy}</p></section></div>; }
