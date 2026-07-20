# Landmark And Boundary Atlas Scoring

Date: 2026-07-17

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-07-17 Landmark And Boundary Atlas Scoring](../implementation_plan/2026-07-17-landmark-boundary-atlas-scoring.md)

## What Changed

- Added symmetric section/atlas boundary-distance metrics for atlas-index
  candidate scoring.
- Added dorsal midline anchor detection for the top-central notch/divot region.
- Added candidate-score penalties for:
  - boundary distance;
  - dorsal midline anchor mismatch.
- Added `boundary_distance_weight` and `dorsal_midline_weight` to
  `AtlasIndexSuggestionConfig`.
- Added `--boundary-distance-weight` and `--dorsal-midline-weight` to
  `scripts/suggest_atlas_indices.py`.
- Added candidate manifest fields for the new alignment metrics:
  - `registration_boundary_distance_norm`;
  - `registration_dorsal_midline_distance`;
  - `registration_dorsal_midline_y_offset`;
  - `registration_dorsal_midline_x_offset`;
  - dorsal-anchor detected flags for section and atlas masks.
- Reused the warped boundary mask from slice registration for cleaner candidate
  contour scoring.
- Added focused tests for candidate score penalties, dorsal notch detection,
  and shifted-boundary/shifted-notch penalties.

## Why

Recent overlays improved in rotation, centering, and scale, but the remaining
errors appear tied to atlas-plane choice and anatomically meaningful outline
fit. Gross overlap metrics can still select candidates that look plausible by
area while missing the dorsal midline notch or visible outer contour.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "dorsal_midline or anatomical_alignment or atlas_candidate_score" -q
```

Result: `4 passed, 46 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "suggest_atlas_indices or atlas_index_ap_conversion or atlas_candidate_score" -q
```

Result: `9 passed, 41 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "atlas_index or suggest_atlas_indices or slice_registration or register_slices_to_atlas or dorsal_midline or anatomical_alignment" -q
```

Result: `15 passed, 35 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py --help
```

Result: command completed successfully and displayed the new scoring-weight
options.

## Known Limitations

- Dorsal midline detection is mask-based and may be less informative on damaged
  slices or slices where the top surface is missing.
- The new scoring changes atlas candidate ranking; it does not add manual
  point correction or nonlinear registration.
- The defaults are intentionally modest and may need empirical tuning after
  reviewing real Slide 1/2/3 candidate grids.
