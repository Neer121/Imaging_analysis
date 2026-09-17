# Independent Atlas Search Stride

Date: 2026-08-28

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-08-28 Independent Atlas Search Stride](../implementation_plan/2026-08-28-independent-atlas-search-stride.md)

## What Changed

- Added `search_stride_slices` and `search_refine_radius_slices` to
  `AtlasIndexSuggestionConfig`.
- Exposed matching CLI options in `scripts/suggest_atlas_indices.py`.
- Generalized the existing coarse-to-fine candidate search so independent
  `best_score` workflows can scan every section coarsely and then refine around
  each section's own best coarse atlas index.
- Added a focused fake-atlas test for the new independent coarse-to-fine search
  path.

## Why

The requested Slide 4 run needed each section to select an atlas index
independently across AP `-6` to `-3` mm. Exhaustive per-section scoring over
that whole range was too slow for quick review, especially with large crops.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "coarse_to_fine_search or detection_plane_sanitizes_selected_channel_only or atlas_index or suggest_atlas or oblique"
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\crop.py src\brain_section_pipeline\atlas_indexing.py scripts\suggest_atlas_indices.py
git diff --check
```

Results:

- Affected crop/indexing tests: 11 passed.
- Python compile checks passed.
- `git diff --check` passed with only LF-to-CRLF warnings.

## Result

The Slide 4 independent AP search completed using:

```text
selection_strategy = best_score
AP range = -6 to -3 mm
search_stride_slices = 5
search_refine_radius_slices = 5
```

## Known Limitations And Next Steps

- The stopped exhaustive/angle-expanded searches may leave partial review
  directories. Use the `stride5` output directory from this completed run as the
  primary result.
- Coarse-to-fine search can miss a narrow optimum if the stride is too large.
  Decrease `search_stride_slices` or increase `search_refine_radius_slices`
  when final review suggests a nearby missed candidate.
