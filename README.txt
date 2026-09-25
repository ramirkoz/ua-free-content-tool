UA FREE Content Tool v2.0.0-rc37 — MANUAL TEST

Recovery release on top of RC36.

RC37:
- restores the per-profile/page/channel publication schedule block in Settings;
- reuses destination_schedules_v1_4.json and the existing DestinationScheduleStore;
- current “Meta / Facebook Pages” settings label no longer hides the schedule UI;
- imported legacy data with malformed non-numeric topic-search IDs is skipped instead of crashing “Пошук схожих за темою матеріалів”.

RC34-RC36 Fact Guard fixes are retained.
