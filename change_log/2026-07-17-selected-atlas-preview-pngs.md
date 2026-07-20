# Selected Atlas Preview PNGs

Date: 2026-07-17

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-07-17 Selected Atlas Preview PNGs](../implementation_plan/2026-07-17-selected-atlas-preview-pngs.md)

## What Changed

- Added atlas-only preview PNG generation for selected atlas planes.
- `suggest_atlas_indices` now writes:
  - one selected atlas preview PNG per section;
  - a selected atlas contact sheet;
  - preview paths in `selected_slice_atlas_manifest.csv` and
    `selected_atlas_indices.csv`;
  - preview paths in `atlas_index_suggestions.json`.
- Added `export_selected_atlas_previews(...)` for regenerating previews from an
  existing `selected_slice_atlas_manifest.csv`.
- Added `scripts/export_selected_atlas_previews.py`.
- Exported `AtlasPreviewExportResult` and `export_selected_atlas_previews` from
  the package top level.
- Added focused tests for automatic preview generation and standalone preview
  export.

## Why

Atlas-index review is easier when the selected atlas planes can be inspected
without histology overlay clutter. This creates a review checkpoint between
atlas-index suggestion and final slice registration.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "selected_atlas_previews or suggest_atlas_indices_writes_selected_manifest" -q
```

Result: `2 passed, 51 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "atlas_index or suggest_atlas_indices or selected_atlas_previews" -q
```

Result: `8 passed, 45 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\export_selected_atlas_previews.py --help
```

Result: command completed successfully and displayed the preview export
options.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\export_selected_atlas_previews.py outputs\rm014_slide01_landmark_anchor_ap1p5_4p0_prior2p75_spacing600\atlas_index_suggestions\selected_slice_atlas_manifest.csv
```

Result: completed successfully and wrote 6 Slide 1 atlas-only preview PNGs and
a contact sheet.

## Output Artifacts

- Slide 1 atlas preview PNGs:
  `outputs/rm014_slide01_landmark_anchor_ap1p5_4p0_prior2p75_spacing600/atlas_index_suggestions/selected/atlas_previews`
- Slide 1 atlas preview contact sheet:
  `outputs/rm014_slide01_landmark_anchor_ap1p5_4p0_prior2p75_spacing600/atlas_index_suggestions/selected/selected_atlas_contact_sheet.png`

## Known Limitations

- This is a static PNG review checkpoint, not an interactive approval GUI.
- It shows atlas reference and annotation boundary only; it intentionally does
  not include histology overlay content.
