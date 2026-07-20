# Atlas Index Suggestion

Date: 2026-07-14

## Goal And Motivation

Add a first-milestone mechanism for suggesting the correct BrainGlobe atlas
slice index for each isolated histology section. The immediate goal is to help
choose a plausible AP atlas plane per slice while keeping a human-review path
for anatomical judgment.

## Current Problem

The sparse slice-wise workflow can register a section to a chosen atlas plane,
but the correct `atlas_slice_index` is currently selected manually. The Slide 5
smoke run showed that registration quality depends heavily on the chosen atlas
plane. AP `-7.25 mm` and Paxinos/Gaidi figure 49 style coordinates are useful
manual references, but the repository does not yet provide a way to search a
local window of atlas planes, rank candidates, or preserve alternate overlays
for review.

## Why This Is Needed Now

The user is reasonably happy with the refined overlay mechanics and now wants
the next workflow bottleneck addressed: identifying the correct atlas index for
each slice. A first implementation should pick a best candidate automatically
while still storing the other top candidates for human review.

## Git Or Worktree State

`git status --short` shows existing uncommitted environment and registration
refinement edits. This change should build on those edits and avoid reverting
them.

## Affected Files

- `src/brain_section_pipeline/atlas_indexing.py`: new candidate-search module.
- `src/brain_section_pipeline/__init__.py`: export the new public API.
- `scripts/suggest_atlas_indices.py`: CLI entry point.
- `tests/test_merge_and_crop.py`: focused tests for AP/index conversion,
  candidate ranking, and selected manifest output.
- `README.md`: document the new first-milestone workflow.
- `implementation_plan/README.md`: index this plan.
- `change_log/`: document the completed implementation and verification.

## Public Parameters Or API Changes

Add:

- `AtlasIndexSuggestionConfig`;
- `AtlasIndexSuggestionResult`;
- `suggest_atlas_indices(...)`;
- AP-to-index and index-to-AP helpers.

The CLI should support:

- `--start-ap-mm` or `--start-slice-index`;
- `--section-interval-um` and `--direction`;
- `--search-radius-slices`;
- `--top-n`;
- `--sample-id`;
- `--section-source`;
- registration tuning passthrough for the constrained registration defaults.

## Expected Behavior

For each selected section, the stage should:

- estimate an expected atlas index;
- search a local atlas-index window;
- run constrained 2D registration against each candidate;
- rank candidates by a combined score;
- mark one machine-selected best candidate;
- save the other top candidates for human review;
- generate a top-candidate overlay grid;
- write a selected slice-atlas manifest that can feed into
  `register_slices_to_atlas`.

## Verification

- Run syntax checks for the new module and CLI.
- Add focused unit tests using a fake atlas loader.
- Run focused tests for atlas index suggestion.
- Optionally run a small candidate search on Slide 5 if practical.

## Non-Goals

- Do not implement global multi-slice dynamic programming yet.
- Do not implement full automatic anatomical landmark recognition.
- Do not replace human review.
- Do not rerun ND2 export.
