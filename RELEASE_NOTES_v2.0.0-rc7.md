# UA FREE Content Tool v2.0.0-rc7

RC7 fixes human-facing media filenames used by Google Drive and external publishing platforms.

## Changes

- New media uploads are named from the publication headline instead of the original CDN/hash filename.
- Readable names keep a short stable publication suffix, for example: `Зрозумілий заголовок - post-1842.jpg`.
- Source media, local files and manually supplied URLs all use the same naming rule because the managed Drive client enforces it centrally.
- When an existing publication with already attached legacy hash-named media is opened, RC7 renames that managed Drive file to the readable publication name and updates the local media metadata.
- Publication runtime also rewrites the multipart upload filename from the publication title, so older already-attached media no longer leaks opaque Drive/CDN names into LinkedIn or Threads notifications.
- Filename normalization preserves Ukrainian and Latin letters, digits and a compact post ID while keeping the correct media extension and the existing 160-character safety limit.

No database reset or destructive migration is introduced. Existing Data is reused normally.
