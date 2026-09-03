# UA FREE Content Tool v1.4.0-rc10

RC10 adds an explicit **«ОПУБЛІКУВАТИ ЗАРАЗ»** mode to the Publication tab.

## Publish now

- A new button is placed beside **«СХВАЛИТИ Й ПОСТАВИТИ В ЧЕРГУ»**.
- It uses the currently selected concrete destinations, the saved editor text, source-link option, media/gallery, and the per-destination donation policy exactly like normal publication.
- The user receives an explicit confirmation showing the selected destinations before any external write begins.
- Publish-now work is prioritized ahead of ordinary overdue queue work and bypasses the five-minute catch-up throttle between the selected immediate destinations.
- Existing queue slots are not consumed, moved, delayed or recalculated.
- Publish-now technical batches are hidden from normal active queue listings and excluded from per-destination latest-slot calculations.
- After each attempt, the real request time is restored before the record is shown in **Історія публікацій**.
- A destination already queued for the same material is not duplicated and its queue row is not changed.
- A destination that already has a terminal result for the same material is not published again accidentally.
- If the application was interrupted during an immediate external request, existing outcome-unknown safety still applies: the app does not blindly retry an ambiguous platform write.

## Preserved from RC9

- Automatic source-type detection and editable source type/name/address.
- Shift/Ctrl/Ctrl+A/Delete source selection and bulk deletion.
- Per-profile publication schedules remain authoritative; the obsolete global schedule UI stays removed.
- Existing Data, queues, media references, tokens, profiles, destination schedules and learning history are preserved. No database schema migration.
