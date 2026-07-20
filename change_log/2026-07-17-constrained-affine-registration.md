# Constrained Affine Slice Registration

Date: 2026-07-17

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-07-17 Constrained Affine Slice Registration](../implementation_plan/2026-07-17-constrained-affine-registration.md)

## What Changed

- Added optional `transform_model` support to `SliceRegistrationConfig`:
  - `similarity` keeps the existing translation/rotation/uniform-scale model;
  - `affine` runs a constrained affine refinement after similarity fitting.
- Added affine controls:
  - `max_affine_anisotropy`;
  - `max_affine_shear`;
  - `affine_regularization_weight`.
- Added affine overfit regularization so anisotropic scale and shear must
  improve the fit enough to justify their added flexibility.
- Added registration manifest fields:
  - `registration_transform_model`;
  - `registration_scale_y`;
  - `registration_scale_x`;
  - `registration_affine_anisotropy`;
  - `registration_affine_shear`;
  - `registration_affine_regularization_penalty`.
- Added `--transform-model affine` and related affine-bound options to
  `scripts/register_slices_to_atlas.py`.
- Added focused tests for affine regularization and bounded affine metadata.
- Replaced tiny affine-helper matrix multiplications with explicit scalar math
  after a Windows fatal exception occurred during test execution.

## Why

Recent Slide 1 overlays are close enough that the remaining mismatch may be
caused by mild tissue distortion rather than a wholly wrong atlas plane. A
constrained affine pass gives the final overlay a little more flexibility while
keeping the transform auditable and bounded.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "affine or slice_registration or register_slices_to_atlas or boundary_fit_loss" -q
```

Result: `9 passed, 43 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "atlas_index or suggest_atlas_indices or slice_registration or register_slices_to_atlas or dorsal_midline or anatomical_alignment or affine" -q
```

Result: `17 passed, 35 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\register_slices_to_atlas.py --help
```

Result: command completed successfully and displayed the new affine options.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\register_slices_to_atlas.py outputs\rm014_slide01_landmark_anchor_ap1p5_4p0_prior2p75_spacing600\atlas_index_suggestions\selected_slice_atlas_manifest.csv --output-dir outputs\rm014_slide01_landmark_anchor_ap1p5_4p0_prior2p75_spacing600\registration_constrained_affine --transform-model affine --translation-initialization tissue_centroid --max-rotation-degrees 1 --min-scale-factor 0.65 --max-scale-factor 1.05 --translation-search-fraction 0.30 --max-affine-anisotropy 0.10 --max-affine-shear 0.04 --affine-regularization-weight 0.08 --area-loss-weight 0.15 --extent-loss-weight 0.5 --center-loss-weight 0.8 --overlay-mask-threshold-quantile 0.35 --overlay-mask-dilation-px 10 --boundary-fit-threshold-quantile 0.35 --boundary-fit-weight 0.25 --boundary-containment-weight 0.9
```

Result: completed successfully. Sections 2, 4, and 6 used bounded anisotropy
of `0.05` or `-0.05`; sections 1, 3, and 5 stayed at the similarity solution;
no section used shear.

```powershell
git diff --check
```

Result: no whitespace errors. Git reported existing CRLF normalization warnings
for several working-tree files.

## Output Artifacts

- Slide 1 constrained-affine overlays:
  `outputs/rm014_slide01_landmark_anchor_ap1p5_4p0_prior2p75_spacing600/registration_constrained_affine/overlays`
- Slide 1 constrained-affine contact sheet:
  `outputs/rm014_slide01_landmark_anchor_ap1p5_4p0_prior2p75_spacing600/registration_constrained_affine/slide01_constrained_affine_contact_sheet.png`

## Known Limitations

- Affine mode is optional and not yet enabled by default.
- The affine search is a bounded grid refinement, not a continuous optimizer.
- This does not add local atlas-index refinement or nonlinear registration.
