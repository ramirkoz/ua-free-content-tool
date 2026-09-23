# UA FREE Content Tool v2.0.0-rc23 — MANUAL TEST

- Fixed Windows process handle counter: the RC22 diagnostic path referenced `ctypes` without importing it, so `process_handle_count` silently became `-1`.
- Fixed Google Drive heartbeat expiry: cached OAuth access tokens are now refreshed once automatically after HTTP 401 for metadata, downloads and uploads. A normal access-token expiry no longer permanently silences telemetry.
- Keeps the RC22 HTTP resource lifecycle fix and independent heartbeat transport.
- Auto-update promotion remains disabled for this manual test build.
