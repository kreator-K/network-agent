import { AppShell } from "@/components/app-shell";
import { requireSession } from "@/lib/session";
export default async function StudioPage() { await requireSession(); return <AppShell><div className="page"><p className="eyebrow">Creation graph</p><h1>Content Studio</h1><section className="panel placeholder"><h2>Research → Hook → Carousel → Caption</h2><p>Each artifact will remain inspectable, retryable, and tied to its evidence.</p></section></div></AppShell>; }
