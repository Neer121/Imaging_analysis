# Constrained Affine Slice Registration

Date: 2026-07-17

## Goal And Motivation

Add an optional post-index affine refinement for slice-to-atlas overlays after
the atlas plane has already been selected. The goal is to absorb modest
histology distortion, such as unequal x/y shrinkage or tiny shear, without
allowing the transform to overfit a questionable atlas plane.

## Current Problem

The current final registration uses a similarity transform: translation,
rotation, and one uniform scale. Several overlays are close, but some still
show visible boundary mismatch that could plausibly come from tissue
anisotropy rather than wrong AP index alone.

## Why This Is Needed Now

Slide 1 now anchors near the expected AP coordinate and looks generally good.
The next likely improvement is not another broad atlas-index search, but a
slightly more flexible final transform that remains constrained and auditable.

## Affected Files

- `src/brain_section_pipeline/slice_registration.py`
- `scripts/register_slices_to_atlas.py`
- `tests/test_merge_and_crop.py`
- `change_log/`

## Public Parameters Or API Changes

Add optional registration parameters:

- `transform_model`: `similarity` or `affine`;
- `max_affine_anisotropy`: maximum fractional deviation between y/x scale;
- `max_affine_shear`: maximum shear coefficient;
- `affine_regularization_weight`: penalty weight for anisotropy and shear.

The default remains `similarity` to preserve existing behavior.

## Algorithm Details

1. Run the existing similarity registration exactly as before.
2. If `transform_model="affine"`, search a small grid around the similarity
   matrix:
   - y/x scale multipliers are bounded by `max_affine_anisotropy`;
   - shear is bounded by `max_affine_shear`;
   - a small translation refinement is allowed.
3. Score candidate affine transforms with the existing mask, boundary, center,
   and containment loss plus an affine regularization penalty.
4. Store affine parameters and penalty values in the registration manifest so
   humans can audit whether the extra freedom was used.

## Expected Behavior

- Similarity output remains unchanged by default.
- Affine mode can improve boundary fit when the slice is mildly stretched.
- Affine mode should not produce extreme stretching/shearing because the search
  bounds and regularization penalize overfitting.

## Verification

- Unit tests that default registration remains similarity.
- Unit tests that affine loss penalizes shear/anisotropy.
- A synthetic affine-like mask case where affine mode improves or matches
  similarity loss without exceeding configured bounds.
- Focused slice-registration test subset.

## Non-Goals

- Do not add local atlas-index refinement in this pass.
- Do not add manual landmark clicking.
- Do not implement nonlinear registration.
