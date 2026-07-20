# Paxinos AP Coordinate Convention

Date: 2026-07-16

## Goal And Motivation

Add a user-facing AP coordinate convention for atlas-index suggestion so users
can enter AP coordinates in a Paxinos/Gaidi-style Bregma reference while the
pipeline continues to use the BrainGlobe `whs_sd_rat_39um` atlas for image and
mask overlays.

## Current Problem

The atlas-index suggester currently treats AP values as an implicit
BrainGlobe/WHS coordinate derived from the volume center and orientation. This
works mechanically, but the command-line interface does not say which AP
convention is being used, and there is no way to record or apply a calibration
offset between a user-facing Paxinos/Gaidi coordinate and the WHS plane index.

This makes it easy to mix atlas coordinate conventions when selecting slices by
AP range or when interpreting `selected_atlas_indices.csv`.

## Why This Is Needed Now

The overlay mechanics are now usable enough that AP-index selection is the main
workflow bottleneck. The user wants to keep WHS for the actual atlas images and
masks while expressing AP positions in the Paxinos/Gaidi convention used during
manual anatomical review.

## Affected Files

- `src/brain_section_pipeline/atlas_indexing.py`
- `src/brain_section_pipeline/__init__.py`
- `scripts/suggest_atlas_indices.py`
- `tests/test_merge_and_crop.py`
- `README.md`
- `implementation_plan/README.md`
- `change_log/`

## Public Parameters Or API Changes

Add `ap_coordinate_system` to `AtlasIndexSuggestionConfig`:

- `atlas`: existing behavior, where AP coordinates are the WHS/native
  coordinate derived from the BrainGlobe atlas volume.
- `paxinos`: AP coordinates are user-facing Paxinos/Gaidi-style coordinates.

Add `ap_coordinate_offset_mm` to `AtlasIndexSuggestionConfig`:

- conversion rule: `atlas_native_ap_mm = user_ap_mm + ap_coordinate_offset_mm`;
- default is `0.0`, preserving the current mapping until a dataset-specific
  calibration offset is known.

Expose the same options in `scripts/suggest_atlas_indices.py`.

## Expected Behavior

- Existing calls behave the same by default.
- When `ap_coordinate_system="paxinos"`, user inputs such as `start_ap_mm`,
  `min_ap_mm`, `max_ap_mm`, and `ap_prior_mm` are interpreted as
  Paxinos/Gaidi-style AP coordinates.
- Candidate, selected, and metadata outputs record both the configured
  user-facing AP coordinate and the underlying WHS/native AP coordinate.
- Spacing-locked index stepping continues to use physical section spacing and
  atlas resolution, so later slices remain anchored to the selected first WHS
  atlas plane.

## Verification

- Add unit tests for the explicit AP coordinate conversion with an offset.
- Add a CLI/API test that verifies a Paxinos AP range filters candidates via
  the converted WHS-native coordinate and records both coordinate values.
- Run focused atlas-index tests.
- Run `git diff --check`.

## Non-Goals

- Do not replace `whs_sd_rat_39um` atlas images or masks.
- Do not scrape or import the Gaidi web viewer atlas imagery.
- Do not claim a universal WHS-to-Paxinos offset; the offset remains explicit
  and user-configurable.
