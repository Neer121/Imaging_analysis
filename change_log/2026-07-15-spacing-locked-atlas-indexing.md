# Spacing-Locked Atlas Indexing

Date: 2026-07-15

Git state: uncommitted changes in the working tree.

Implementation plan: [2026-07-15 Spacing-Locked Atlas Indexing](../implementation_plan/2026-07-15-spacing-locked-atlas-indexing.md)

## What Changed

- Added `selection_strategy` to `AtlasIndexSuggestionConfig`.
- Preserved the existing `best_score` behavior as the default.
- Added `anchor_search_radius_slices` to `AtlasIndexSuggestionConfig`.
- Added `anchor_search_stride_slices` and `anchor_refine_radius_slices` for
  faster coarse-to-fine first-section anchor scans.
- Added AP constraints to `AtlasIndexSuggestionConfig`:
  - `min_ap_mm`;
  - `max_ap_mm`;
  - `ap_prior_mm`;
  - `ap_prior_weight`.
- Added experimental automatic AP-range estimation to
  `AtlasIndexSuggestionConfig`:
  - `auto_ap_range`;
  - `auto_ap_range_stride_slices`;
  - `auto_ap_range_top_n`;
  - `auto_ap_range_padding_mm`;
  - `auto_ap_range_shape_size`;
  - `auto_ap_range_tissue_quantile`.
- Added `spacing_locked` behavior where:
  - the first selected section is chosen by best local registration score;
  - later sections are selected by stepping from the first selected atlas index
    using `section_interval_um` or `slice_index_step`;
  - nearby candidates are still ranked and saved for human review;
  - the spacing-selected candidate is highlighted in review grids.
- Added `--selection-strategy best_score|spacing_locked` to
  `scripts/suggest_atlas_indices.py`.
- Added `--anchor-search-radius-slices` to allow a broad first-section search
  without broadening every later spacing-locked section.
- Added `--anchor-search-stride-slices` and `--anchor-refine-radius-slices` to
  keep broad anchor searches tractable.
- Added `--min-ap-mm`, `--max-ap-mm`, `--ap-prior-mm`, and
  `--ap-prior-weight` to constrain broad atlas-index searches to plausible AP
  regions.
- Added `--auto-ap-range` and related tuning flags to estimate AP bounds from
  the first section's gross tissue silhouette when manual AP bounds are not
  supplied.
- Added candidate/selected manifest fields for selection strategy, expected
  index, expected AP coordinate, score rank, and search radius.
- Added README guidance and a synthetic unit test for spacing-locked behavior.

## Why The Change Was Made

The prior atlas-index suggester could use section spacing to estimate a local
search center, but every section still selected independently by registration
score. That meant a corrected first-section choice did not automatically anchor
the rest of the anatomical series. For physically ordered histology sections,
the known spacing should be allowed to constrain subsequent atlas-plane choices.

A later RM014 Slide 1 review showed that the first-section anchor itself also
needed a wider search option. The bad AP `-7 mm` run started around WHS index
`699` and used a small local search radius, so it only evaluated AP values near
`-7 mm`. The expected AP `+2.75 mm` plane is around WHS index `441`, hundreds
of atlas slices away from that local window.

## Verification Performed

- Syntax check:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\atlas_indexing.py scripts\suggest_atlas_indices.py
```

Result: passed.

- Focused atlas-index tests:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -q -k "atlas_index or suggest_atlas_indices"
```

Result: `3 passed, 33 deselected`.

- CLI help check:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py --help
```

Result: usage text includes `--selection-strategy`.

- CLI help check after anchor-radius addition:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py --help
```

Result: usage text includes `--anchor-search-radius-slices`.

- RM014 Slide 1 broad anchor rerun from the old AP `-7.3` starting estimate:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py outputs\rm014_slide01_anchor_search_apminus7_fix\section001_upper_left_manifest.csv --output-dir outputs\rm014_slide01_anchor_search_apminus7_fix\anchor_search_radius300_stride10_refine15 --atlas whs_sd_rat_39um --sample-id rm014_slide01 --start-slice-index 699 --selection-strategy best_score --search-radius-slices 5 --anchor-search-radius-slices 300 --anchor-search-stride-slices 10 --anchor-refine-radius-slices 15 --top-n 10
```

Result: selected index `617`, AP `-4.095`, score `0.362`.

- RM014 Slide 1 targeted expected-neighborhood check around AP `+2.75`:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py outputs\rm014_slide01_anchor_search_apminus7_fix\section001_upper_left_manifest.csv --output-dir outputs\rm014_slide01_anchor_search_apminus7_fix\target_ap275_r10 --atlas whs_sd_rat_39um --sample-id rm014_slide01 --start-ap-mm 2.75 --selection-strategy best_score --search-radius-slices 10 --top-n 10
```

Result: selected index `439`, AP `+2.847`, score `0.247`.

This confirms the first failure was candidate coverage, but the remaining
failure is score quality: the current registration-score heuristic still
prefers an anatomically wrong AP `-4.1 mm` plane over the expected AP `+2.75 mm`
neighborhood for this upper-left Slide 1 section.

- RM014 Slide 1 constrained anchor search:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py outputs\rm014_slide01_anchor_search_apminus7_fix\section001_upper_left_manifest.csv --output-dir outputs\rm014_slide01_anchor_search_apminus7_fix\anchor_search_ap_bounds_1p5_4p0_prior2p75 --atlas whs_sd_rat_39um --sample-id rm014_slide01 --start-slice-index 699 --selection-strategy best_score --search-radius-slices 5 --anchor-search-radius-slices 300 --anchor-search-stride-slices 10 --anchor-refine-radius-slices 15 --min-ap-mm 1.5 --max-ap-mm 4.0 --ap-prior-mm 2.75 --ap-prior-weight 0.05 --top-n 10
```

Result: selected index `439`, AP `+2.847`, score `0.242`. This is close to the
expected AP `+2.75` starting region and excludes the anatomically wrong AP
`-4.1 mm` winner from the unconstrained broad search.

- RM014 Slide 1 automatic AP-range test:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py outputs\rm014_slide01_anchor_search_apminus7_fix\section001_upper_left_manifest.csv --output-dir outputs\rm014_slide01_anchor_search_apminus7_fix\auto_ap_range_shape_profile_q50 --atlas whs_sd_rat_39um --sample-id rm014_slide01 --start-slice-index 699 --selection-strategy best_score --search-radius-slices 5 --anchor-search-radius-slices 300 --anchor-search-stride-slices 10 --anchor-refine-radius-slices 15 --auto-ap-range --auto-ap-range-stride-slices 10 --auto-ap-range-top-n 5 --auto-ap-range-padding-mm 0.75 --auto-ap-range-tissue-quantile 0.5 --top-n 10
```

Result: automatic range estimation selected an AP interval of about
`-13.542` to `-10.482` and the final selector chose index `843`, AP `-12.909`.
This is not anatomically correct for the expected AP `+2.75` region, so the
current automatic estimator should be considered experimental. Manual AP bounds
remain the preferred method for this slide.

- AP/index diagnostic for the bad RM014 Slide 1 run:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -c "from brain_section_pipeline import ap_mm_to_atlas_index; shape=(1024,512,512); res=(39,39,39); print(ap_mm_to_atlas_index(-7.0, shape=shape, resolution_um=res, orientation='asr')); print(ap_mm_to_atlas_index(2.75, shape=shape, resolution_um=res, orientation='asr'))"
```

Result: AP `-7.0 mm` maps to index `691`, and AP `+2.75 mm` maps to
index `441`, a distance of `250` atlas slices. The prior local search could not
evaluate the expected AP neighborhood.

- Broader focused test file:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -q
```

Result: `33 passed, 3 failed`. The failures are the pre-existing
crop-fragment merge expectation and two workflow tests that reference
`BrainGlobeExportResult` without importing or defining it.

- Whitespace check:

```powershell
git diff --check
```

Result: no whitespace errors. Git reported line-ending warnings for files that
will be normalized to CRLF when Git next touches them.

## Result Or Observed Behavior

Users can now run:

```powershell
python scripts\suggest_atlas_indices.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --start-ap-mm -7.30 `
  --section-interval-um 200 `
  --direction posterior `
  --selection-strategy spacing_locked `
  --search-radius-slices 25 `
  --top-n 5
```

The selected manifest still feeds directly into `register_slices_to_atlas.py`.
The review grids still preserve nearby alternatives, but the selected overlay
is highlighted so a reviewer can see when anatomical spacing overrode the local
best-score candidate.

When the first AP estimate is rough, run a broad first-section anchor search:

```powershell
python scripts\suggest_atlas_indices.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --start-slice-index 699 `
  --section-interval-um 600 `
  --direction posterior `
  --selection-strategy spacing_locked `
  --anchor-search-radius-slices 300 `
  --anchor-search-stride-slices 10 `
  --anchor-refine-radius-slices 15 `
  --min-ap-mm 1.5 `
  --max-ap-mm 4.0 `
  --ap-prior-mm 2.75 `
  --ap-prior-weight 0.05 `
  --search-radius-slices 5 `
  --top-n 5
```

This lets the first section search broadly from the rough starting estimate
while later sections still use a small review window around the spacing-derived
index.

Automatic range estimation can be enabled when no manual AP interval is known:

```powershell
python scripts\suggest_atlas_indices.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --start-slice-index 699 `
  --selection-strategy spacing_locked `
  --auto-ap-range `
  --anchor-search-radius-slices 300 `
  --anchor-search-stride-slices 10 `
  --anchor-refine-radius-slices 15 `
  --search-radius-slices 5 `
  --top-n 5
```

This mode uses gross silhouette matching and should be reviewed carefully.

## Known Limitations And Next Steps

- This is still a first-section anchor plus fixed-spacing rule, not global
  optimization across all sections.
- The mode assumes the selected manifest order matches anatomical order.
- Future work could add per-section spacing tables, skipped-section handling,
  and global consistency scoring.
