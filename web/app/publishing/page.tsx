import { AppShell } from "@/components/app-shell";
import { getLinkedInPublishStatus, getPublishRequests } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { PublishRequestControls } from "./request-controls";

export default async function PublishingPage() {
  await requireSession();
  const [status, requests] = await Promise.all([getLinkedInPublishStatus(), getPublishRequests()]);
  return <AppShell><div className="page">
    <p className="eyebrow">Explicit external-action boundary</p>
    <h1>LinkedIn publish review.</h1>
    <div className="metrics publishMetrics">
      <article><span>Provider mode</span><strong>{status?.publishing_mode || "unavailable"}</strong><p>Real publishing switch: {status?.real_publish_enabled ? "enabled" : "off"}</p></article>
      <article><span>Connection</span><strong>{status?.connection_status || "unavailable"}</strong><p>Member authorization and scope status.</p></article>
      <article><span>Awaiting confirmation</span><strong>{status?.pending_confirmations ?? 0}</strong><p>Each request is frozen and expires.</p></article>
    </div>
    <section className="panel">
      <div className="panelTitle"><h2>Frozen request history</h2><span>Append-only audit lifecycle</span></div>
      <div className="publishList">{requests.length ? requests.map((request) => <article key={request.request_id}>
        <div className="publishMeta">
          <span>Request #{request.request_id} · package #{request.post_id} v{request.package_version}</span>
          <h2>{request.status.replaceAll("_", " ")}</h2>
          <p>Format {request.format} · {request.visibility} · fingerprint <code>{request.payload_fingerprint}</code></p>
          <small>Expires {new Date(request.expires_at).toLocaleString()}</small>
        </div>
        <div className="frozenPayload">
          <span>Exact frozen commentary</span>
          <p>{request.commentary}</p>
          {request.safe_error_summary ? <p className="formError">{request.safe_error_summary}</p> : null}
          {request.status === "awaiting_confirmation" ? <PublishRequestControls requestId={request.request_id} /> : null}
        </div>
      </article>) : <div className="empty"><strong>No frozen requests.</strong><p>Approve a content package, then create a frozen preview in Content Studio.</p></div>}</div>
    </section>
  </div></AppShell>;
}
