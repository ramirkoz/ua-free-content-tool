# UA FREE Content Tool v1.4.0-rc19

RC19 fixes the timezone architecture exposed by RC18 live use.

## What changed

- Stored timestamps remain UTC; RC19 changes presentation and working-day semantics only.
- The default program timezone is now the Windows/system timezone instead of a hard-coded city.
- Settings now include a **Program timezone** control:
  - `System (automatic)` / `Системний (автоматично)` follows the workstation timezone;
  - an explicit IANA timezone such as `Europe/Kyiv` or `Europe/Berlin` can be selected or typed.
- One working timezone is applied consistently to:
  - source `Last new item` and `Last check` timestamps;
  - Inbox `Last mention` timestamps;
  - timestamps of individual sources inside an editorial block;
  - publication Queue and publication History;
  - publication-slot calculations inherited from the existing scheduler;
  - RC18 daily Inbox rollover and the definition of the current working day.
- Daily Inbox rollover remains DST-safe and is re-armed after a timezone change.
- The original RC18 current-day cleanup behavior is preserved: previous-day stories are removed from the working Inbox without deleting history from the database.
- Portable builds include timezone data and Windows-to-IANA system-timezone detection dependencies.

## Compatibility

- No destructive database migration.
- Existing `Data` from RC18 is preserved.
- If no RC19 timezone preference exists, the application starts in `System (automatic)` mode.
