"use client";

import { useActionState } from "react";
import type { ResearchResource } from "@/lib/api";
import { createPost, type CreatePostState } from "./actions";

const initialState: CreatePostState = { error: "", created: false };

export function CreatePostForm({ resources }: { resources: ResearchResource[] }) {
  const [state, action, pending] = useActionState(createPost, initialState);
  const readyResources = resources.filter((item) => item.research_brief_json);
  return <form action={action} className="createPostForm" encType="multipart/form-data">
    <div className="formIntro">
      <div><p className="eyebrow">Start here</p><h2>Create a post</h2></div>
      <p>The Research, Hook, Carousel, and Caption agents will build one reviewable package. Nothing is published.</p>
    </div>
    <label>Post topic<input name="topic" placeholder="What should this post help people understand?" required maxLength={200}/></label>
    <label>Research brief<select name="research_resource_id" defaultValue=""><option value="">Use my context below</option>{readyResources.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select><small>{readyResources.length ? `${readyResources.length} completed brief${readyResources.length === 1 ? "" : "s"} available` : "Run research on the Signals page to use a saved brief."}</small></label>
    <label className="wideField">Context or point of view<textarea name="inspiration_notes" rows={5} placeholder="Your thesis, interpretation, examples, or constraints. This stays distinct from sourced facts." maxLength={6000}/></label>
    <div className="imageFields">
      <label>Upload an image<input name="image" type="file" accept="image/jpeg,image/png,image/webp"/><small>JPEG, PNG, or WebP. Maximum 10 MB.</small></label>
      <label>Text over the image<input name="overlay_text" placeholder="Optional headline placed on your image" maxLength={500}/></label>
      <label>Image description<input name="image_alt_text" placeholder="Required when uploading an image" maxLength={500}/></label>
      <label className="checkField"><input name="generate_image" type="checkbox"/>Create a branded card if I do not upload an image</label>
      <small className="uploadRule">If both options are selected, your uploaded image always wins.</small>
    </div>
    <button className="primaryAction" type="submit" disabled={pending}>{pending ? "Building package…" : "Create review draft"}</button>
    {state.error ? <p className="formError">{state.error}</p> : null}
    {state.created ? <p className="formSuccess">Draft created below. Review it before approval.</p> : null}
  </form>;
}
