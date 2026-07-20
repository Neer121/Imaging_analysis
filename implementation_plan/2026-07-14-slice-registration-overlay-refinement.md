# Slice Registration Overlay Refinement

Date: 2026-07-14

## Goal And Motivation

Improve the final slice-to-atlas overlay so the transformed histology section
is less likely to appear oversized or spuriously rotated when registering real
ND2-derived section crops to BrainGlobe atlas planes.

## Current Problem

The Slide 5 smoke run completed, but visual inspection showed the final
registration overlays were rotated left and too large for both detected
sections. The registration manifest reported successful transforms, but those
transforms used scales around `0.06` and rotations near `-28` to `-29` degrees.

The current registration initializes scale from the ratio of atlas mask area to
histology tissue-mask area. For large slide crops, that area ratio can produce
a transform whose bounding box is wider than the atlas plane even when overlap
metrics look acceptable. The current registration also initializes rotation
from mask image moments, which can be unstable for histology crops with uneven
signal or remaining off-section background.

## Why This Is Needed Now

The user asked why the final overlay looked rotated and too large and asked to
refine the overlay mechanism. This needs a code change because the issue is in
the default similarity-transform initialization and scoring, not only in a
runtime parameter choice.

## Git Or Worktree State

`git status --short` already shows uncommitted environment-stabilization edits
from the prior environment work. This change should not revert those edits.

## Affected Files

- `src/brain_section_pipeline/slice_registration.py`: refine scale and
  rotation initialization, add shape-aware registration loss terms, and record
  richer diagnostics.
- `scripts/register_slices_to_atlas.py`: expose new registration tuning
  options where useful.
- `tests/test_merge_and_crop.py`: add focused tests for bbox-fit scale
  initialization and oversize penalty behavior.
- `implementation_plan/README.md`: index this plan.
- `change_log/`: document the completed refinement after verification.

## Public Parameters Or API Changes

Add optional fields to `SliceRegistrationConfig`:

- `initial_rotation_degrees`: default `0.0`; use `None` to initialize rotation
  from mask moments.
- `scale_initialization`: default `"bbox_fit"`; keep `"area"` available for
  compatibility experiments.
- `area_loss_weight`: weight for penalizing warped-mask area mismatch.
- `extent_loss_weight`: weight for penalizing warped-mask bounding-box
  mismatch.
- `center_loss_weight`: weight for penalizing warped-mask center offset from
  the atlas mask center.

The CLI should expose the most useful controls without changing existing
required arguments.

## Expected Behavior

For real slide crops, the default transform should start from a section scale
that fits within the atlas mask bounding box rather than one derived only from
area. The optimizer should penalize transforms that make the warped tissue
substantially larger or smaller than the atlas mask, and it should avoid large
left/right rotations unless the loss clearly supports them.
The refined scale search should respect the configured scale bounds during
both coarse and refinement passes, so a bbox-fit initial scale cannot silently
grow beyond the requested maximum.

The refined overlay should still write the same output artifacts:

- warped section TIFFs;
- registration overlay PNGs;
- registration manifest;
- registration metadata.

## Verification

- Run focused unit tests for slice registration.
- Run the existing focused repository test command where practical.
- Rerun the Slide 5 mid-AP registration stage into a separate output
  directory and inspect the resulting overlay and registration metrics.

## Non-Goals

- Do not implement full non-linear registration.
- Do not solve atlas-slice selection automatically in this change.
- Do not rerun the full ND2 export stage unless needed.
- Do not change the 3D BrainReg handoff path.
