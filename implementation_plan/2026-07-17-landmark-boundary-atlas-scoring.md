# Landmark And Boundary Atlas Scoring

Date: 2026-07-17

## Goal And Motivation

Improve slice-to-atlas overlay quality by making atlas-index candidate scoring
more anatomically aware. The immediate target is the dorsal midline notch/divot
and global boundary correspondence, because visual review shows that rotation
and centering have improved but atlas-plane selection and outline fit still
need stronger guidance.

## Current Problem

Candidate ranking currently relies mostly on overlap, scale/extent penalties,
centering, and boundary containment. Those metrics can still favor a candidate
whose gross mask overlaps reasonably while missing clear anatomical cues such
as the dorsal midline convergence point or having a visibly displaced outer
contour.

## Why This Is Needed Now

Recent Slide 2 and Slide 3 overlays are closer than earlier outputs, but the
remaining mismatch appears dominated by choosing the best atlas plane and by
matching visible anatomical landmarks rather than only matching total mask
area.

## Affected Files

- `src/brain_section_pipeline/atlas_indexing.py`
- `tests/test_merge_and_crop.py`
- `scripts/suggest_atlas_indices.py` if new scoring weights need CLI exposure
- `change_log/`

## Public Parameters Or API Changes

Add optional scoring weights to `AtlasIndexSuggestionConfig`:

- `boundary_distance_weight`;
- `dorsal_midline_weight`.

Defaults should enable modest penalties without requiring user input. Existing
commands should continue to work.

## Algorithm Details

For each candidate after similarity registration:

1. Use the warped display/boundary mask and atlas mask.
2. Compute a symmetric boundary distance score using distance transforms of
   each mask boundary, normalized by atlas size.
3. Detect a dorsal midline notch anchor from each mask:
   - find the dorsal/top mask surface profile;
   - restrict to the central x-window;
   - choose the deepest local dorsal indentation relative to nearby surface
     points;
   - fall back to the top-central surface point when no strong indentation is
     present.
4. Add normalized y/x offset penalties between the warped section anchor and
   atlas anchor.
5. Store the metrics in candidate manifests so review grids can be audited.

## Expected Behavior

- Atlas candidates whose outer contours are closer should score higher.
- Candidates that align the dorsal midline notch/divot better should score
  higher.
- If a notch cannot be detected, scoring should degrade gracefully rather than
  failing the run.

## Verification

- Unit tests for dorsal anchor detection on synthetic masks.
- Unit tests that candidate score prefers lower boundary-distance and
  landmark-offset metrics when other metrics are equal.
- Focused atlas-index and registration test subset.

## Non-Goals

- Do not implement manual point clicking in this pass.
- Do not add nonlinear registration in this pass.
- Do not replace WHS atlas overlays with the Gaidi/Paxinos atlas image data.
