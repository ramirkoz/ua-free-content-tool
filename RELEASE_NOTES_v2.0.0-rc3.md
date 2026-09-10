# UA FREE Content Tool v2.0.0-rc3

Hotfix release for two field failures observed during RC2 burn-in.

- Google Drive transport now tries every public DNS address until one connects, avoiding false failures when Windows receives an unusable first IPv6/IPv4 route.
- Safe Drive GET/HEAD operations receive one short transient retry; upload/create POST operations are not blindly replayed after ambiguous transport failures.
- Google Drive access tokens are proactively refreshed after 45 minutes instead of being cached forever.
- Small but usable static images are minimally upscaled before Drive upload. Telegram 320×175 preview photos now become 329×180 instead of being rejected by the historical 180px floor.
- Truly tiny image inputs below 96px on the shortest side remain blocked; small animated GIFs are not silently flattened.
- No database reset and no change to the RC30 compatibility data model.
