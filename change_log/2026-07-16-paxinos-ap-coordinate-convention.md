# Paxinos AP Coordinate Convention

Date: 2026-07-16

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-07-16 Paxinos AP Coordinate Convention](../implementation_plan/2026-07-16-paxinos-ap-coordinate-convention.md)

## What Changed

- Added `ap_coordinate_system` to `AtlasIndexSuggestionConfig` with:
  - `atlas` for the existing WHS/native AP convention;
  - `paxinos` for user-facing Paxinos/Gaidi-style Bregma AP coordinates.
- Added `ap_coordinate_offset_mm` with the conversion:

```text
atlas_native_ap_mm = user_ap_mm + ap_coordinate_offset_mm
```

- Added coordinate conversion helpers:
  - `coordinate_ap_mm_to_atlas_native_ap_mm`;
  - `atlas_native_ap_mm_to_coordinate_ap_mm`.
- Updated AP-index conversion, AP candidate filtering, AP priors, automatic AP
  range metadata, and candidate scoring to honor the configured AP coordinate
  convention.
- Updated candidate, selected, and metadata outputs to record both:
  - configured user-facing AP values such as `atlas_ap_mm` and
    `selected_ap_mm`;
  - underlying WHS/native AP values such as `atlas_native_ap_mm` and
    `selected_native_ap_mm`.
- Added CLI options to `scripts/suggest_atlas_indices.py`:
  - `--ap-coordinate-system atlas|paxinos`;
  - `--ap-coordinate-offset-mm`.
- Updated README usage guidance and the implementation-plan index.
- Added focused unit coverage for Paxinos offset conversion and AP-bound
  filtering.

## Why

The pipeline should continue to use `whs_sd_rat_39um` for actual atlas images
and masks, but users need to enter and review AP values in the same
Paxinos/Gaidi-style convention they use for manual anatomical interpretation.
Making the coordinate convention explicit avoids silently mixing WHS/native AP
coordinates with Bregma-referenced AP coordinates.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "atlas_index_ap_conversion or suggest_atlas_indices" -q
```

Result: `7 passed, 33 deselected`.

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe scripts\suggest_atlas_indices.py --help
```

Result: command completed successfully and displayed the new
`--ap-coordinate-system` and `--ap-coordinate-offset-mm` options.

```powershell
git diff --check
```

Result: no whitespace errors. Git reported existing CRLF normalization warnings
for several working-tree files.

## Known Limitations

- This does not replace the WHS atlas imagery or annotations with Gaidi/Paxinos
  images.
- The default offset is `0.0`. A biologically correct WHS-to-Paxinos offset may
  need to be calibrated from known slices or landmarks before being used for a
  final dataset.
- Automatic AP-range estimation remains experimental and can still select a
  poor anatomical neighborhood if gross tissue shapes are ambiguous.
