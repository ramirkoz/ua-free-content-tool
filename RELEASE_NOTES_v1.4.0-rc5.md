# UA FREE Content Tool v1.4.0-rc5

RC5 fixes two RC4 UI-state regressions reported during live editorial use.

## Duplicate review columns

- Proposal and reason columns no longer use Tk Treeview automatic stretching.
- Manual column widths stay at the width chosen by the editor instead of snapping back when the maximized window is recalculated.
- Added horizontal and vertical scrollbars so wide custom layouts remain usable.
- Existing persisted column widths continue to be loaded from and saved to `Data/duplicate_dialog_layout_v1_4.json`.

## Publication profile presets

- RC4 no longer lets transient checkbox changes overwrite the remembered publication target set.
- Loading an existing material, rebuilding dynamic destinations, applying recommendations, or temporarily selecting all profiles no longer becomes the next default by accident.
- The remembered target set is now written only by authoritative user actions: approving a material, explicitly applying a preset, or saving a preset.
- Fresh materials continue to restore the last actually used target set.

No publication-storage or database-schema change is included in RC5.
