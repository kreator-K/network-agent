# LinkedIn Image Upload Security

Image packages accept only approved JPG/JPEG, PNG, or GIF files whose extension,
signature, dimensions, configured size, hash, and alt text validate. The upload
destination must be HTTPS on an allowlisted LinkedIn host. Redirects are disabled,
the OAuth token is not sent to the upload host, and complete upload URLs are not
stored. A failed image never becomes a text-only post.
