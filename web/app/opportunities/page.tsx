import { AppShell } from "@/components/app-shell";
import { requireSession } from "@/lib/session";
export default async function OpportunitiesPage() { await requireSession(); return <AppShell><div className="page"><p className="eyebrow">Editorial queue</p><h1>Opportunities</h1><section className="panel placeholder"><h2>Compare source-backed angles</h2><p>Rank, save, dismiss, or move an opportunity into Content Studio.</p></section></div></AppShell>; }
