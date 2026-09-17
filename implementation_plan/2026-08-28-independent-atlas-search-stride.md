# Independent Atlas Search Stride

Date: 2026-08-28

## Goal And Motivation

Make independent per-slice atlas-index selection practical for broad AP ranges
by allowing every selected section to use coarse-to-fine candidate search.

## Current Problem

The Slide 4 AP-only independent run over AP `-6` to `-3` mm took too long. The
existing coarse-to-fine settings only apply to the first anchor section, which
helps spacing-locked workflows but does not help independent `best_score`
selection for every section.

## Why This Is Needed Now

The user wants each identified Slide 4 slice to choose its atlas index
separately within the same AP range. Without a per-row coarse stride, this means
scoring every atlas plane in the range for every section, which is slow for
large full-resolution crops.

## Affected Files

- `src/brain_section_pipeline/atlas_indexing.py`
- `scripts/suggest_atlas_indices.py`
- `tests/test_merge_and_crop.py`
- `implementation_plan/README.md`
- `change_log/`

## Public Parameters Or API Changes

Add to `AtlasIndexSuggestionConfig` and `scripts/suggest_atlas_indices.py`:

- `search_stride_slices`: coarse candidate stride for non-anchor searches;
- `search_refine_radius_slices`: fine search radius around the best coarse
  candidate.

Existing `anchor_search_stride_slices` and `anchor_refine_radius_slices` remain
available and still take precedence for the first section when set.

## Expected Behavior

- Default behavior remains exhaustive local search with stride 1.
- When `search_stride_slices > 1`, each eligible section first scores coarse
  candidates, then rescans a smaller local window around its own best coarse
  index.
- AP min/max constraints continue to apply to both the coarse and refined
  candidate sets.

## Verification

- Add a focused fake-atlas test proving independent sections write selected
  outputs when `search_stride_slices > 1`.
- Rerun affected atlas-index tests.
- Rerun the Slide 4 independent AP range selection with stride/refine settings.

## Non-Goals

- Do not change spacing-locked semantics.
- Do not change candidate scoring weights.
