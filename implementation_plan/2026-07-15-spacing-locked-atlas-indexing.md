# Spacing-Locked Atlas Indexing

Date: 2026-07-15

## Goal And Motivation

Add an atlas-index suggestion mode that uses known anatomical spacing between
histology sections. The first selected section should still use the current
candidate-search mechanism to find the right neighborhood in the atlas, but
later sections should be assigned atlas indices by stepping from that selected
first atlas index using a user-provided section spacing.

## Current Problem

`suggest_atlas_indices` already accepts `section_interval_um`, but each section
is still selected independently by registration score around its own expected
index. If the first section search corrects the starting plane from the user's
rough estimate, later sections do not inherit that correction. That can make a
series internally inconsistent even when the physical spacing between sections
is known from slicing.

Follow-up RM014 Slide 1 tests exposed two related anchor-selection problems:

- a local first-section search cannot recover when the rough starting AP is far
  from the true anatomical plane;
- after broad anchor search was added, the registration-overlap score still
  preferred an anatomically wrong AP `-4.1 mm` plane over the expected
  AP `+2.75 mm` neighborhood.

The selection stage therefore needs explicit anatomical constraints in addition
to wider search coverage.

## Why This Is Needed Now

The atlas overlay mechanics and top-candidate review grids are useful, but the
next anatomical constraint is ordered spacing. The user wants to preserve the
current candidate-review workflow while allowing the program to start from a
good first-slice choice and then use known section spacing to pick subsequent
atlas planes.

## Affected Files

- `src/brain_section_pipeline/atlas_indexing.py`
- `scripts/suggest_atlas_indices.py`
- `tests/test_merge_and_crop.py`
- `README.md`
- `implementation_plan/README.md`
- `change_log/`

## Public Parameters Or API Changes

Add `selection_strategy` to `AtlasIndexSuggestionConfig`:

- `best_score`: current default behavior, selecting the highest-scoring
  candidate independently for every section.
- `spacing_locked`: select the best-scoring candidate for the first section,
  then select later sections by stepping from that first selected index using
  `section_interval_um` or `slice_index_step`.

Add a CLI option:

```text
--selection-strategy best_score|spacing_locked
```

Add optional first-section broad-search controls:

- `anchor_search_radius_slices`;
- `anchor_search_stride_slices`;
- `anchor_refine_radius_slices`.

Add optional AP constraints:

- `min_ap_mm` and `max_ap_mm` to filter evaluated candidates to an anatomical
  AP interval;
- `ap_prior_mm` and `ap_prior_weight` to apply a soft distance penalty around
  an expected AP.
- `auto_ap_range` to estimate a plausible AP interval from the first section's
  normalized tissue silhouette when manual AP bounds are not supplied.

## Expected Behavior

In spacing-locked mode:

- section 1 searches the normal candidate window and selects the best score;
- later sections compute their expected selected atlas index from the first
  selected index plus the signed anatomical spacing;
- a broad first-section anchor search can use coarse-to-fine stride/refinement
  to avoid evaluating every atlas plane in a large radius;
- optional AP bounds prevent impossible atlas regions from winning broad
  searches;
- optional AP priors can guide selection toward a known approximate anatomical
  region without forcing a single index;
- automatic AP range estimation can propose a bounded first-section search
  interval while still allowing manual AP bounds to override it;
- top-candidate overlays are still generated for human review;
- the selected candidate is marked even when it is not the highest-scoring
  registration candidate;
- selected manifests remain compatible with `register_slices_to_atlas.py`.

## Verification

- Add a unit test proving that a corrected first-slice choice anchors later
  spacing-locked selections.
- Run focused atlas-index tests.
- Run syntax/import checks for the module and CLI.
- Run `git diff --check`.

## Non-Goals

- Do not implement global dynamic programming across sections.
- Do not infer section spacing from image data.
- Do not remove the existing score-based independent selection mode.
- Do not treat automatic AP range estimation as definitive anatomy; it remains
  a first-pass gross-shape constraint that should be reviewed.
