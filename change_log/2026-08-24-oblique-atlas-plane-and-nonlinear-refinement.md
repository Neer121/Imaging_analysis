# Oblique Atlas Plane And Nonlinear Refinement

Date: 2026-08-24

Git state: uncommitted changes in the working tree. The existing untracked
`work/` directory was present before this implementation and was not modified
for source behavior.

Implementation plan:
[2026-08-24 Oblique Atlas Plane And Nonlinear Refinement](../implementation_plan/2026-08-24-oblique-atlas-plane-and-nonlinear-refinement.md)

## What Changed

- Added optional atlas plane-angle search to
  `src/brain_section_pipeline/atlas_indexing.py`.
  - `AtlasIndexSuggestionConfig` now accepts `atlas_plane_angle_search`,
    `atlas_plane_pitch_degrees`, and `atlas_plane_yaw_degrees`.
  - Candidate extraction can sample oblique 2D planes from the 3D atlas volume.
  - Candidate grids, selected atlas preview titles, selected manifests,
    selected choices, and candidate manifests now record pitch/yaw degrees.
- Added optional boundary-spline nonlinear refinement to
  `src/brain_section_pipeline/slice_registration.py`.
  - `SliceRegistrationConfig` now accepts `nonlinear_refinement_model`,
    `nonlinear_max_displacement_px`, `nonlinear_control_point_spacing_px`,
    `nonlinear_iterations`, and `nonlinear_boundary_sample_step`.
  - The refinement is disabled by default.
  - When enabled, registration writes the refined overlay as the main overlay
    and stores an affine-before overlay in `affine_overlays/`.
  - Registration manifests record nonlinear model, iterations, and
    displacement metrics.
- Exposed the new options in:
  - `scripts/suggest_atlas_indices.py`;
  - `scripts/register_slices_to_atlas.py`.
- Updated `README.md` with examples for atlas plane-angle search and optional
  boundary-spline refinement.
- Added focused tests for:
  - zero-angle atlas extraction preserving exact slice behavior;
  - angle candidate manifest fields;
  - conservative boundary-spline refinement reducing a simple shifted-boundary
    mismatch.

## Why

The user was still seeing residual slice-to-atlas fit issues after improving
centering, rotation, boundary containment, and affine fit. BrainJ/ABBA-style
workflows suggest two high-value additions: searching the atlas cutting plane
instead of AP alone, and optionally applying a controlled nonlinear cleanup
after the global registration.

## Verification

Commands run:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\slice_registration.py src\brain_section_pipeline\atlas_indexing.py scripts\suggest_atlas_indices.py scripts\register_slices_to_atlas.py
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "oblique_atlas_plane or records_oblique or boundary_spline"
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "atlas_index or suggest_atlas or export_selected_atlas or slice_registration or boundary_fit or affine or oblique or boundary_spline"
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py --help
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\register_slices_to_atlas.py --help
git diff --check
```

Results:

- Focused new tests: 3 passed.
- Affected atlas/registration subset: 18 passed.
- Script help commands completed successfully and show the new options.
- `git diff --check` completed successfully, with only LF-to-CRLF warnings.

Full-file pytest was also run:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py
```

Result: 53 passed and 3 failed. The failures appear unrelated to this change:

- `test_detect_section_crops_merges_moderately_smaller_fragment_companion`
  expected one crop box but got two.
- Two workflow tests reference `BrainGlobeExportResult` without importing it,
  causing `NameError`.

## Known Limitations And Next Steps

- Angle search currently supports pitch/yaw AP offsets across the 2D atlas
  plane. It does not yet estimate a shared animal-level cutting angle across
  all sections.
- The boundary-spline refinement is a conservative overlay cleanup step, not a
  substitute for correct atlas index and plane selection.
- A future refinement should add key-slice approval and shared angle/spacing
  regularization across an entire slide or animal.
