UA FREE Content Tool v2.0.0-rc38 — MANUAL TEST

Cumulative recovery release on top of RC37.

RC37 retained:
- per-profile/page/channel publication schedule block in Settings;
- destination_schedules_v1_4.json / DestinationScheduleStore;
- hardened imported legacy topic-search IDs.

RC38 Fact Guard:
- full-form measurement units in Ukrainian, Russian and English normalize to the same canonical units as abbreviations;
- km/км, m/м, kg/кг, MW/МВт, GW/ГВт, GB/ГБ, MB/МБ and TB/ТБ are normalized consistently;
- common grammatical forms are supported;
- unit parsing uses word boundaries so ordinary words are not misread as units;
- real changed values remain blocked.

All RC34-RC36 Fact Guard fixes are retained.
