# Selected Atlas Preview PNGs

Date: 2026-07-17

## Goal And Motivation

Add a human review checkpoint between atlas-index suggestion and final overlay
registration. After section crops are made and atlas indices are suggested, the
pipeline should export easy-to-open PNGs of the selected atlas planes before
histology overlays are generated.

## Current Problem

The selected atlas reference and annotation planes are saved as TIFFs, but
there is no atlas-only PNG preview/contact sheet designed for quick review.
Candidate overlay grids mix atlas and histology, which can make it harder to
judge whether the atlas plane itself looks plausible.

## Why This Is Needed Now

Recent Slide 1 results are good enough that fine AP/index review matters.
Being able to inspect the chosen rat atlas planes before final registration
will make it easier to decide whether the selected AP series looks anatomically
reasonable.

## Affected Files

- `src/brain_section_pipeline/atlas_indexing.py`
- `src/brain_section_pipeline/__init__.py`
- `scripts/suggest_atlas_indices.py`
- new script under `scripts/`
- `tests/test_merge_and_crop.py`
- `change_log/`

## Public Parameters Or API Changes

Add reusable export support for selected atlas previews:

- PNG preview per selected section;
- contact sheet for all selected sections;
- optional standalone script to regenerate previews from
  `selected_slice_atlas_manifest.csv`.

The suggestion step should write previews by default. Existing command inputs
should remain compatible.

## Expected Behavior

- `suggest_atlas_indices` writes atlas-only PNGs to a predictable preview
  folder.
- Each preview shows the atlas reference plane with annotation boundary and
  section/index/AP labels.
- The selected atlas manifest records each preview path.
- A contact sheet summarizes all selected atlas planes for fast human review.

## Verification

- Unit tests for preview PNG/contact-sheet generation from a synthetic selected
  manifest.
- Focused atlas-index suggestion tests to confirm preview paths are written.
- CLI help check for the standalone preview script.

## Non-Goals

- Do not build an interactive GUI approval step.
- Do not change atlas-index scoring in this pass.
- Do not change final overlay registration behavior.
