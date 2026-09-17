# Oblique Atlas Plane And Nonlinear Refinement

Date: 2026-08-24

## Goal And Motivation

Improve slice-to-atlas overlay accuracy by adding two registration refinements
inspired by BrainJ/ABBA-style workflows:

- optional atlas plane-angle search during atlas-index suggestion;
- optional conservative nonlinear boundary refinement after the existing
  similarity/affine 2D fit.

The goal is to improve practical overlay mechanics while preserving the current
default behavior unless the user explicitly enables the new options.

## Current Problem

The current atlas-index suggestion assumes each atlas candidate is a strict
coronal/AP plane. If the physical tissue section was cut with a small oblique
angle, the selected AP index can be plausible while the atlas outline still has
the wrong shape. The final 2D affine fit can compensate by stretching or
shearing, but that can distort the slice rather than fixing the atlas-plane
mismatch.

The final registration also stops at similarity or constrained affine. This has
worked better than the initial overlay, but small residual boundary mismatches
remain after AP index selection. A light nonlinear pass could improve review
overlays if it is bounded, optional, and clearly recorded.

## Why This Is Needed Now

The user has reviewed multiple slide runs and found that rotation and centering
are now much better, but atlas index/plane mismatch and residual local boundary
fit remain limiting. The previous BrainJ/ABBA method review identified atlas
cutting-angle search and staged nonlinear refinement as the next high-value
steps.

## Affected Files

- `src/brain_section_pipeline/atlas_indexing.py`
- `src/brain_section_pipeline/slice_registration.py`
- `scripts/suggest_atlas_indices.py`
- `scripts/register_slices_to_atlas.py`
- `tests/test_merge_and_crop.py`
- `implementation_plan/README.md`
- `change_log/`

## Public Parameters Or API Changes

Add atlas plane-angle search settings to `AtlasIndexSuggestionConfig` and
`scripts/suggest_atlas_indices.py`:

- `atlas_plane_angle_search`;
- `atlas_plane_pitch_degrees`;
- `atlas_plane_yaw_degrees`.

Add nonlinear refinement settings to `SliceRegistrationConfig` and
`scripts/register_slices_to_atlas.py`:

- `nonlinear_refinement_model`: `none` or `boundary_spline`;
- `nonlinear_max_displacement_px`;
- `nonlinear_control_point_spacing_px`;
- `nonlinear_iterations`;
- `nonlinear_boundary_sample_step`.

## Algorithm Details

Atlas plane-angle search extracts candidate atlas planes from the 3D atlas by
allowing the AP/slice-axis coordinate to vary smoothly across the 2D output
plane:

```text
slice_axis_coordinate =
  base_index
  + tan(pitch) * row_physical_offset / slice_axis_resolution
  + tan(yaw) * col_physical_offset / slice_axis_resolution
```

Zero pitch/yaw should produce the same slice as the existing exact atlas slice
extraction. Nonzero angles are sampled with linear interpolation for reference
images and nearest-neighbor interpolation for annotation masks.

The optional nonlinear refinement runs after the current affine/similarity fit.
It estimates boundary-to-boundary displacement vectors from warped section
boundary pixels toward the nearest atlas boundary, smooths those vectors into a
dense displacement field, clips displacement magnitude, and applies the field to
the already warped section/masks. This is an overlay-focused local correction,
not a replacement for the saved global affine matrix.

## Expected Behavior

- Default atlas suggestion and registration outputs are unchanged when new
  options are disabled.
- Enabling angle search expands atlas candidates from AP-only to AP plus
  labeled pitch/yaw plane candidates.
- Top candidate grids, candidate manifests, selected manifests, selected
  choices, preview names/titles, and metadata record the selected pitch/yaw.
- Enabling nonlinear boundary refinement writes the refined overlay as the main
  overlay and also saves an affine-before overlay for review.
- Registration manifests and metadata record nonlinear model, displacement, and
  boundary metric changes.

## Verification

- Add focused tests for exact zero-angle extraction, nonzero oblique extraction,
  candidate manifest angle fields, and nonlinear refinement metadata.
- Run the focused pytest file.
- Run `git diff --check`.

## Non-Goals

- Do not install Elastix or ABBA in this step.
- Do not implement manual landmark picking.
- Do not make nonlinear refinement the default.
- Do not change the current WHS atlas source.
