import { AppShell } from "@/components/app-shell";
import { getContentPackages, getResearchResources } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { approvePackage } from "./actions";
import { FreezeRequestForm } from "./freeze-request-form";
import { ContentControls } from "./content-controls";
import { CreatePostForm } from "./create-post-form";

export default async function StudioPage() {
  await requireSession();
  const [packages, resources] = await Promise.all([getContentPackages(), getResearchResources()]);
  return <AppShell><div className="page">
    <p className="eyebrow">Creation graph</p>
    <h1>Content Studio</h1>
    <section className="panel createPostPanel"><CreatePostForm resources={resources}/></section>
    <section className="panel">
      <div className="panelTitle"><h2>Research → Hook → Carousel → Caption</h2><span>{packages.length} review items</span></div>
      <div className="contentList">{packages.length ? packages.map((item) => <article key={item.id}>
        <div className="contentPreview">
          <span>Package #{item.id} · version {item.package_version} · {item.status.replaceAll("_", " ")}{item.image_source && item.image_source !== "none" ? ` · ${item.image_source} image` : ""}</span>
          <h2>{item.topic || "Source-backed content package"}</h2>
          {item.image_source && item.image_source !== "none" ? <img className="contentImage" src={`/api/content/${item.id}/image`} alt={item.image_alt_text || "Content draft image"}/> : null}
          <p>{item.draft_text}</p>
        </div>
        <div className="contentActions">
          <ContentControls postId={item.id} />
          {item.status !== "approved_for_later_posting" ? <form action={approvePackage}>
            <input type="hidden" name="post_id" value={item.id} />
            <button className="primaryAction" type="submit">Approve for later</button>
            <small>Internal approval only. Nothing is published.</small>
          </form> : <FreezeRequestForm postId={item.id} />}
        </div>
      </article>) : <div className="empty"><strong>No content packages yet.</strong><p>Use the form above to create your first review draft.</p></div>}</div>
    </section>
  </div></AppShell>;
}
