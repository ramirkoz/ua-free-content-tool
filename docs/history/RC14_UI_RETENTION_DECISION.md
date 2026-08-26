# RC14 UI and retention decision

Live RC13 evidence showed the publication backend continuing to work while the desktop UI could appear hung during startup. The root cause class is synchronous SQLite/Data maintenance and refresh work before Tk reaches a healthy event loop, amplified by a large live database.

RC14 therefore separates UI startup from Data maintenance and constrains operational publication history to seven days. Older sent publication packages are retained in SQLite archive tables so audit/dedup evidence survives while normal history/statistics queries stay bounded.

No database schema-version bump is required because the archive tables are additive and created lazily. Existing RC13 Data remains directly usable.
