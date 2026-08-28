import { chooseVariant, revisePackage } from "./actions";

export function ContentControls({ postId }: Readonly<{ postId: number }>) {
  return <div className="editorControls">
    <form action={chooseVariant}>
      <input type="hidden" name="post_id" value={postId} />
      <label>Variant<select name="variant_number" defaultValue="1"><option value="1">Variant 1</option><option value="2">Variant 2</option><option value="3">Variant 3</option></select></label>
      <button className="secondaryAction" type="submit">Select variant</button>
    </form>
    <form action={revisePackage}>
      <input type="hidden" name="post_id" value={postId} />
      <label>Revision<select name="revision_type" defaultValue="make_more_concise"><option value="make_more_concise">More concise</option><option value="make_more_personal">More personal</option><option value="make_more_analytical">More analytical</option><option value="make_more_practical">More practical</option><option value="reduce_hype">Reduce hype</option><option value="regenerate_hook">Regenerate hook</option><option value="custom_revision">Custom revision</option></select></label>
      <input name="revision_notes" maxLength={2000} placeholder="Optional constraints or custom revision notes" />
      <button className="secondaryAction" type="submit">Create new version</button>
    </form>
  </div>;
}
