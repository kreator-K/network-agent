# LinkedIn Multi-Image Runbook

Approve a package containing 2–20 ordered image assets and alt text. Run
`/prepare_publish <post_id>`, inspect every preview and hash, then use the exact
request ID with `/confirm_publish`. Any failed image blocks the whole post; do
not retry an uncertain request or downgrade it to one image.
