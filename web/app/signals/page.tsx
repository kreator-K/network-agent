import { AppShell } from "@/components/app-shell";
import { getSignalSourceCatalog, getSignalSources, getSignals } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { createSignalSource, runSignalScan, signalFeedback, sourceDecision } from "./actions";

export default async function SignalsPage() {
  await requireSession();
  const [signals, sources, catalog] = await Promise.all([getSignals(), getSignalSources(), getSignalSourceCatalog()]);
  const existingUrls = new Set(sources.map((source) => source.url));
  const suggestions = catalog.filter((source) => !existingUrls.has(source.url));
  return <AppShell><div className="page">
    <div className="pageHeader"><div><p className="eyebrow">Evidence desk</p><h1>Signals</h1></div><form action={runSignalScan}><button className="primaryAction" type="submit">Scan approved sources</button></form></div>
    <section className="panel sourcePanel">
      <div className="panelTitle"><h2>Source review</h2><span>Add → approve → enable</span></div>
      <form action={createSignalSource} className="sourceForm"><input name="name" placeholder="Feed name" required/><input name="url" type="url" placeholder="Public RSS or Atom URL" required/><select name="source_type" defaultValue="auto_feed"><option value="auto_feed">Auto-detect</option><option value="rss">RSS</option><option value="atom">Atom</option></select><button className="secondaryAction" type="submit">Add pending source</button></form>
      <div className="sourceList">{sources.map((source) => <article key={source.id}><div><span>#{source.id} · {source.approval_status}</span><strong>{source.name}</strong><small>{source.url}</small></div><form action={sourceDecision}><input type="hidden" name="source_id" value={source.id}/>{source.approval_status === "pending" ? <><button name="source_action" value="approve">Approve</button><button name="source_action" value="reject">Reject</button></> : source.approval_status === "approved" ? <button name="source_action" value={source.enabled ? "disable" : "enable"}>{source.enabled ? "Disable" : "Enable"}</button> : null}</form></article>)}</div>
      {suggestions.length ? <div className="catalogSuggestions"><span>Pending catalog suggestions</span>{suggestions.map((source) => <form action={createSignalSource} key={source.url}><input type="hidden" name="name" value={source.name}/><input type="hidden" name="url" value={source.url}/><input type="hidden" name="source_type" value={source.source_type}/><div><strong>{source.name}</strong><small>{source.topics?.join(" · ")}</small></div><button className="secondaryAction" type="submit">Add for review</button></form>)}</div> : null}
    </section>
    <section className="panel"><div className="signalList">{signals.length ? signals.map((signal) => <article key={signal.id}><span>#{signal.id}</span><div><strong>{signal.title || "Untitled signal"}</strong><p>{signal.source_name || "Approved source"}</p></div><div className="feedbackActions"><b>{signal.status || "stored"}</b><form action={signalFeedback}><input type="hidden" name="signal_id" value={signal.id}/><button type="submit" name="feedback_type" value="more_like_this">More like this</button><button type="submit" name="feedback_type" value="less_like_this">Less like this</button></form></div></article>) : <div className="empty"><strong>No stored signals.</strong><p>Run a scan after approving and enabling at least one RSS or Atom source.</p></div>}</div></section>
  </div></AppShell>;
}
