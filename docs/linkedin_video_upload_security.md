# LinkedIn Video Upload Security

Only an approved MP4 owned by the authenticated member is accepted. The file
hash and size are frozen before confirmation. Provider upload URLs are validated,
never stored, and never receive the OAuth bearer token. Multipart results are
finalized before the returned Video URN is used in the Posts API. Uncertain
uploads are not retried automatically.
