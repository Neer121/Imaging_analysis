# Slice Registration Fit Tuning

Date: 2026-07-17

## Goal And Motivation

Improve final 2D slice-to-atlas overlay fits for RM014 Slide 2 without changing
the selected atlas indices. The overlays should be less sensitive to asymmetric
crop padding and should avoid showing rectangular low-level background as if it
were aligned tissue.

## Current Problem

The current registration initializes translation by mapping the center of the
cropped section image to the atlas mask centroid. If the actual tissue centroid
is not at the crop center, the fit can start off-center and the coarse search
may not fully recover. The overlay display also blends the warped image
everywhere, including background fluorescence from the rectangular crop, which
makes the visual result look offset or oversized even when the tissue mask
overlap is moderate.

Slide 2 tuning runs showed that wider scale/rotation ranges can improve Dice
and IoU, but very wide rotation often hits the search bounds and visually
tilts the whole rectangular crop. A better default should first fix centroid
initialization and mask the display layer.

## Why This Is Needed Now

The user reviewed the Slide 2 outputs and reported that atlas outlines did not
match the slices well and that slices appeared off center. Before refining
atlas-index selection further, the final overlay registration should use a more
stable initialization and produce clearer visual QC images.

## Affected Files

- `src/brain_section_pipeline/slice_registration.py`
- `src/brain_section_pipeline/atlas_indexing.py`
- `scripts/register_slices_to_atlas.py`
- `scripts/suggest_atlas_indices.py`
- `tests/test_merge_and_crop.py`
- `README.md`
- `implementation_plan/README.md`
- `change_log/`

## Public Parameters Or API Changes

Add `translation_initialization` to `SliceRegistrationConfig`:

- `crop_center`: existing behavior, mapping the crop center to atlas centroid.
- `tissue_centroid`: maps the section tissue centroid to the atlas centroid
  while preserving rotation and scale about the crop center.

Add overlay display controls:

- `mask_overlay_to_tissue`: when true, hide section overlay pixels outside the
  section tissue mask.
- `overlay_mask_threshold_quantile`: a more permissive threshold used only for
  overlay display, separate from the stricter registration mask.
- `overlay_mask_dilation_px`: optional display-mask dilation so dim tissue
  near the tissue edge remains visible.

Add outer-boundary fit controls:

- `boundary_fit_threshold_quantile`: lower-threshold mask used to estimate the
  visible outer slice boundary.
- `boundary_fit_dilation_px`: optional dilation for the outer-boundary fit
  mask.
- `boundary_fit_weight`: weight for matching the outer slice boundary to the
  atlas mask.
- `boundary_containment_weight`: weight for penalizing visible slice boundary
  outside the atlas mask.

Expose these options in `scripts/register_slices_to_atlas.py`.

## Expected Behavior

- New registrations can initialize from the section tissue centroid to reduce
  systematic off-center overlays.
- Overlay PNGs can hide rectangular crop background outside the tissue mask
  without using the strict registration mask as the display mask.
- The actual brain slice should remain visually rich in the overlay, with dim
  tissue texture preserved inside a permissive foreground mask.
- The optimizer should use the lower-threshold outer slice boundary to keep the
  visible slice from being scaled larger than the selected atlas plane.
- Atlas-index candidate scoring should use the same boundary containment
  metrics so top-5 atlas-plane review grids are ranked with the current overlay
  mechanics rather than the older inner-mask-only fit.
- Existing output manifests remain compatible with downstream code.
- Registration metrics should remain available and comparable.

## Verification

- Add focused tests for tissue-centroid initialization and masked overlay
  behavior.
- Run focused slice registration tests.
- Run a Slide 2 tuned registration with the new options.
- Run `git diff --check`.

## Non-Goals

- Do not change atlas-index selection in this step.
- Do not implement nonlinear or landmark-based registration.
- Do not replace WHS atlas masks.
