# Slice Registration Fit Tuning

Date: 2026-07-17

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-07-17 Slice Registration Fit Tuning](../implementation_plan/2026-07-17-slice-registration-fit-tuning.md)

## What Changed

- Added `translation_initialization` to `SliceRegistrationConfig`:
  - `tissue_centroid` maps the section tissue centroid to the atlas centroid;
  - `crop_center` keeps the older crop-center behavior.
- Changed the registration script default to tissue-centroid translation
  initialization.
- Added `mask_overlay_to_tissue` to `SliceRegistrationConfig`.
- Added display-only overlay mask controls:
  - `overlay_mask_threshold_quantile`;
  - `overlay_mask_dilation_px`.
- Added outer-boundary containment controls:
  - `boundary_fit_threshold_quantile`;
  - `boundary_fit_dilation_px`;
  - `boundary_fit_weight`;
  - `boundary_containment_weight`.
- Updated overlay composition so section signal outside a permissive warped
  display mask is hidden by default, leaving a dim atlas reference rather than
  a red rectangular crop background.
- Added `--translation-initialization` and `--show-crop-background` to
  `scripts/register_slices_to_atlas.py`.
- Added `--overlay-mask-threshold-quantile` and
  `--overlay-mask-dilation-px` to `scripts/register_slices_to_atlas.py`.
- Added `--boundary-fit-threshold-quantile`,
  `--boundary-fit-dilation-px`, `--boundary-fit-weight`, and
  `--boundary-containment-weight` to `scripts/register_slices_to_atlas.py`.
- Added boundary-fit metrics to registration manifests:
  - `registration_boundary_area_ratio`;
  - `registration_boundary_extent_y_ratio`;
  - `registration_boundary_extent_x_ratio`;
  - `registration_boundary_outside_fraction`.
- Updated atlas-index candidate scoring to use the same boundary-aware fit
  metrics, including boundary area/extent ratios and outside-atlas fraction.
- Added boundary-aware registration controls to `scripts/suggest_atlas_indices.py`
  so top-5 candidate grids can be ranked with the same mechanics as final
  overlays.
- Reused prepared section crops and masks during atlas-index candidate scoring
  so each atlas candidate does not recompute the same section tissue masks.
- Passed warped section masks into atlas-index review overlays when available.
- Added focused tests for tissue-centroid initialization and masked overlay
  rendering.
- Updated README usage guidance.

## Why

RM014 Slide 2 overlays appeared partly off center and visually cluttered by
rectangular crop background. The old initialization assumed the crop center was
also the tissue center, which is not reliable for asymmetric crops. The overlay
display also made low-level crop background look like aligned tissue.

The first masked-overlay version reused the strict registration mask and faded
too much real slice texture. The final display design therefore separates the
strict registration mask from a more permissive overlay display mask.

Follow-up review showed that the visible slice boundary remained too large
relative to the atlas outline. The final fit therefore adds a boundary
containment term based on a lower-threshold outer slice mask. This term can be
tuned independently from inner-anatomy overlap.

After that, atlas-index scoring also needed to be updated. Otherwise candidate
ranking could still prefer atlas planes that score well on inner-mask overlap
while letting the visible slice boundary spill outside the atlas outline.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "slice_registration or register_slices_to_atlas or boundary_fit or display_tissue_mask or suggest_atlas_indices or atlas_index_ap_conversion" -q
```

Result: `15 passed, 30 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py --help
```

Result: command completed successfully and displayed the new candidate
registration controls, including the boundary-fit options.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\register_slices_to_atlas.py outputs\rm014_slide02_full_ap0_to_minus1_spacing650um\atlas_overlay_rtl_ap0_to_minus1_spacing650um\atlas_index_suggestions_paxinos_ap0_to_minus1\selected_slice_atlas_manifest.csv --output-dir outputs\rm014_slide02_paxinos_ap0_minus1_registration_tissue_centroid_v2 --translation-initialization tissue_centroid --max-rotation-degrees 4 --min-scale-factor 0.7 --max-scale-factor 1.1 --translation-search-fraction 0.35 --area-loss-weight 0.15 --extent-loss-weight 0.5 --center-loss-weight 0.8
```

Result: completed successfully and wrote tuned Slide 2 overlays.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\register_slices_to_atlas.py outputs\rm014_slide02_full_ap0_to_minus1_spacing650um\atlas_overlay_rtl_ap0_to_minus1_spacing650um\atlas_index_suggestions_paxinos_ap0_to_minus1\selected_slice_atlas_manifest.csv --output-dir outputs\rm014_slide02_paxinos_ap0_minus1_registration_tissue_centroid_v3 --translation-initialization tissue_centroid --max-rotation-degrees 4 --min-scale-factor 0.7 --max-scale-factor 1.1 --translation-search-fraction 0.35 --area-loss-weight 0.15 --extent-loss-weight 0.5 --center-loss-weight 0.8 --overlay-mask-threshold-quantile 0.35 --overlay-mask-dilation-px 10
```

Result: completed successfully and wrote tuned Slide 2 overlays with a more
permissive display mask that preserves visible brain-slice texture better than
the strict-mask v2 output.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\register_slices_to_atlas.py outputs\rm014_slide02_full_ap0_to_minus1_spacing650um\atlas_overlay_rtl_ap0_to_minus1_spacing650um\atlas_index_suggestions_paxinos_ap0_to_minus1\selected_slice_atlas_manifest.csv --output-dir outputs\rm014_slide02_paxinos_ap0_minus1_registration_boundary_contained_v5_soft --translation-initialization tissue_centroid --max-rotation-degrees 1 --min-scale-factor 0.65 --max-scale-factor 1.05 --translation-search-fraction 0.30 --area-loss-weight 0.15 --extent-loss-weight 0.5 --center-loss-weight 0.8 --overlay-mask-threshold-quantile 0.35 --overlay-mask-dilation-px 10 --boundary-fit-threshold-quantile 0.35 --boundary-fit-dilation-px 0 --boundary-fit-weight 0.25 --boundary-containment-weight 0.9
```

Result: completed successfully. This softer boundary-containment run reduced
slice scale while keeping rotation close to zero. It is the preferred Slide 2
boundary-fit output from this pass.

Compared with the previous Slide 2 registration, Dice improved for all four
sections:

- section 1: `0.524` to `0.573`;
- section 2: `0.502` to `0.563`;
- section 3: `0.495` to `0.555`;
- section 4: `0.504` to `0.545`.

```powershell
git diff --check
```

Result: no whitespace errors. Git reported existing CRLF normalization warnings
for several working-tree files.

## Output Artifacts

- Tuned overlays:
  `outputs/rm014_slide02_paxinos_ap0_minus1_registration_boundary_contained_v5_soft/overlays`
- Comparison contact sheet:
  `outputs/rm014_slide02_paxinos_ap0_minus1_registration_boundary_containment_comparison.png`

## Known Limitations

- The tuned similarity transform improves global centering and overlap but does
  not solve atlas-plane mismatch.
- Some remaining outline disagreement on Slide 2 likely reflects atlas index,
  atlas convention, or atlas-template differences rather than only transform
  fitting.
- This is still a similarity transform, not nonlinear tissue deformation.
