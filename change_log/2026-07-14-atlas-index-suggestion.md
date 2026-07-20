# Atlas Index Suggestion

Date: 2026-07-14

Git state: uncommitted changes in the working tree.

Implementation plan: [2026-07-14 Atlas Index Suggestion](../implementation_plan/2026-07-14-atlas-index-suggestion.md)

## What Changed

- Added `src/brain_section_pipeline/atlas_indexing.py` with:
  - `AtlasIndexSuggestionConfig`;
  - `AtlasIndexSuggestionResult`;
  - `suggest_atlas_indices(...)`;
  - AP-coordinate/index conversion helpers.
- Exposed the new API from `brain_section_pipeline.__init__`.
- Added `scripts/suggest_atlas_indices.py` for command-line candidate search.
- Added focused tests for AP/index conversion and candidate suggestion output.
- Updated the README sparse slice-wise workflow to document the atlas-index
  suggestion stage and its review artifacts.

## Why The Change Was Made

The slice-wise workflow could already register a histology section to a chosen
BrainGlobe atlas plane, but choosing that plane was still manual. The Slide 5
smoke runs showed that the overlay mechanics were useful once the atlas plane
was close, so the next workflow bottleneck was searching nearby planes, ranking
them, selecting the best candidate automatically, and preserving alternate
top candidates for human review.

## Verification Performed

- Syntax check:

```powershell
python -m py_compile src\brain_section_pipeline\atlas_indexing.py scripts\suggest_atlas_indices.py
```

Result: passed.

- Focused atlas-index tests:

```powershell
pytest tests\test_merge_and_crop.py -q -k "atlas_index or suggest_atlas_indices"
```

Result: `2 passed, 33 deselected`.

- Broader focused test file:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -q
```

Result: `32 passed, 3 failed`. The failures are the pre-existing
crop-fragment merge expectation and two workflow tests that reference
`BrainGlobeExportResult` without importing or defining it.

- Import smoke check:

```powershell
python -c "from brain_section_pipeline import AtlasIndexSuggestionConfig, suggest_atlas_indices; print(AtlasIndexSuggestionConfig.__name__, callable(suggest_atlas_indices))"
```

Result: `AtlasIndexSuggestionConfig True`.

- CLI help check:

```powershell
python scripts\suggest_atlas_indices.py --help
```

Result: usage text printed successfully.

- Slide 5 real-data smoke run around the figure-49 estimate:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py outputs\slide05_slicewise_smoke\slide05\section_manifest.csv --output-dir outputs\slide05_slicewise_smoke\slide05\atlas_index_suggestions_fig49_r2 --atlas whs_sd_rat_39um --sample-id slide05 --start-slice-index 699 --search-radius-slices 2 --top-n 5
```

Result: completed in about 63 seconds. The run wrote two review grids and
selected atlas index `697` for both detected Slide 5 sections.

- Downstream registration smoke using the selected manifest:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\register_slices_to_atlas.py outputs\slide05_slicewise_smoke\slide05\atlas_index_suggestions_fig49_r2\selected_slice_atlas_manifest.csv --output-dir outputs\slide05_slicewise_smoke\slide05\atlas_index_suggestions_fig49_r2\selected_slice_registration
```

Result: completed in about 13 seconds and wrote
`selected_slice_registration/slice_registration_manifest.csv`.

## Result Or Observed Behavior

The new stage writes:

- `atlas_index_candidates.csv` with the top candidates and registration metrics;
- `review_grids/section*_candidate_grid.png` for human inspection;
- `selected_atlas_indices.csv` with the machine-selected best atlas plane;
- `selected_slice_atlas_manifest.csv` for downstream
  `register_slices_to_atlas.py` execution;
- selected reference, annotation, section, and overlay files under
  `selected/`.

For the Slide 5 smoke run, the key outputs are under:

```text
outputs/slide05_slicewise_smoke/slide05/atlas_index_suggestions_fig49_r2/
```

## Known Limitations And Next Steps

- The score is still based on 2D similarity-registration fit metrics, not
  anatomical landmark recognition.
- The selected rank-1 candidate should be treated as a suggestion, not a final
  anatomical decision.
- The search is currently independent per section. A future milestone should
  add multi-section consistency, expected spacing constraints, and optional
  dynamic programming across an ordered slide or sample.
