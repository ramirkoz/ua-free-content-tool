# UA FREE Content Tool 2.0.0-rc60

Live media-behavior repair after operator testing of RC59.

- Opening a material no longer silently starts a source-media scan. Media discovery starts only after the operator clicks «Знайти медіа в джерелах».
- The media progress bar now tracks the actual requested work: source discovery, selected candidate download, Google Drive upload, and local-file upload. It stops and resets after completion or failure.
- Selected single-video/photo downloads use the same busy-state path as multi-selection, eliminating the RC59 case where the bar was static during the actual download/upload stage.
- Keeps the restored human-readable media filenames from RC59.
- Adds a second, exact-post Telegram discovery path through the public `t.me/s/<channel>/<post>` page when the embed page returns no usable media. The fallback is scoped to the requested `data-post` block so neighbouring channel posts are not harvested.
- Keeps bounded retries for Telegram embed/player pages and media downloads.
- Adds RC60 regressions for no implicit scan, progress tied to real media transfer, local upload progress, exact public-post scoping, and Telegram fallback recovery.

RC60 supersedes the RC59 test artifact for live operator validation.
