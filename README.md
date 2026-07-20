# Brain Section Pipeline

This repository is being shaped into a workflow for reconstructing 3D rat
brain histology data from 2D slide sections and registering the result to a
BrainGlobe rat atlas. The implementation is not finalized yet. This README
summarizes the planned direction and the expected implementation boundaries.

## Current Status

The current code can process Nikon ND2 slide images, merge channels, detect
individual tissue sections, save section crops, and write basic crop metadata.
The repository now also includes a BrainGlobe-preparation export stage that
turns those cropped 2D sections into an organized sample folder with
per-channel section images, registration-channel images, QC overlays, and a
sample-level manifest. The next stage after that is to align those sections
section-to-section and register the resulting stack to a rat atlas with
BrainGlobe tools.

BrainGlobe should be treated as the atlas and registration backend, especially
through `brainreg` and `brainglobe-atlasapi`. The custom code in this repository
should handle slide-specific preparation, section ordering, channel export,
metadata, quality control, and post-registration quantification.

For the current sparse-dataset goal, the primary workflow is now **slice-wise
atlas superimposition**, not full 3D reconstruction.

## Environment Setup

The recommended day-to-day environment is `histology`, created from
`environment.yml`:

```powershell
conda env create -f environment.yml
conda activate histology
python -m ipykernel install --user --name histology --display-name "Python (histology)"
```

This environment uses `conda-forge` plus `nodefaults` and installs the package
in editable mode with the `atlas` optional dependency group, which includes
`brainglobe-atlasapi` for sparse slice-wise atlas work. On some conda
installations, `conda env create -f ...` can still check configured
`defaults` channels before it finishes reading `nodefaults`. If that happens
and you see an Anaconda Terms of Service error, either accept the Anaconda ToS
for the local conda installation or recreate the environment with an explicit
conda-forge-only command:

```powershell
conda create -n histology --override-channels -c conda-forge python=3.11 pip ipykernel ipywidgets jupyterlab matplotlib "numpy<2.3" pillow pytest "scikit-image<0.26" "scipy<1.16" tk tifffile xarray
conda activate histology
python -m pip install -e ".[atlas]" --no-build-isolation
python -m ipykernel install --user --name histology --display-name "Python (histology)"
```

BrainGlobe atlas data are still downloaded separately the first time an atlas
is requested, for example when constructing
`BrainGlobeAtlas("whs_sd_rat_39um")`.

Dense 3D `brainreg` execution is intentionally isolated in a second
environment:

```powershell
conda env create -f environment-brainreg.yml
conda activate histology-brainreg
python -m ipykernel install --user --name histology-brainreg --display-name "Python (histology-brainreg)"
```

Use `histology-brainreg` only when you are ready to run dense-mode BrainReg
handoff commands. On Windows, the BrainReg CLI path can involve native
BrainReg/napari/Qt/NiftyReg components and has previously triggered a
`python.exe` application error (`0xc06d007f`) during environment verification.
The current sparse slice-wise workflow does not require launching
`brainreg.exe`.

## Planned Workflow

### 1. Inspect The Raw Slide Data

Input data are expected to be ND2 slide scanner files with multiple color
channels and multiple physical tissue sections per slide. For each acquisition,
record:

- sample ID;
- slide ID;
- channel names and biological meaning;
- pixel size in microns;
- section thickness in microns;
- section interval in microns;
- physical section order;
- anterior-posterior direction;
- any missing, folded, torn, or duplicated sections.

The section interval is critical for 3D reconstruction. If 40 um sections were
cut but only every fifth section was imaged, the z spacing for reconstruction is
200 um, not 40 um.

### 2. Extract Individual Sections From Slides

Use the existing ND2 pipeline to detect tissue pieces and export one image per
section. The current reusable entry points are:

- `find_nd2_files` for locating ND2 files;
- `read_nd2_image` for reading channel-first image data;
- `detect_section_crops` for tissue section detection;
- `merge_channels` for RGB preview images;
- `process_nd2_file` and `process_selected_files` for end-to-end crop export.

Expected outputs for this stage:

```text
sample_id/
  sections_rgb/
    section001.tif
    section002.tif
  sections_channels/
    ch0/
    ch1/
    ch2/
  qc/
    slide_crop_overlays/
  section_manifest.csv
```

The section manifest should become the central handoff file. It should preserve
the source ND2 file, crop box, channel mapping, section index, slide position,
z position, pixel size, section thickness, section interval, and QC notes.

### 3. Select The Registration Channel

For BrainGlobe registration, use a structural or background-like channel when
possible. A strong sparse signal channel is usually a poor registration target.

Recommended channel roles:

- registration channel: autofluorescence, counterstain, or broad tissue signal;
- signal channels: marker channels used for downstream quantification;
- RGB preview: human QC only, not the primary registration input.

If no clean background channel exists, build a registration image from a robust
combination of channels and validate it visually before running atlas
registration.

### 4. Pair Each Section To An Atlas Plane

For sparse datasets, the first useful registration target is a corresponding
2D atlas plane for each histology section, not a full 3D reconstruction.

Recommended sparse-mode steps:

1. Confirm biological section order and gross orientation manually.
2. Choose a rat atlas such as `whs_sd_rat_39um`.
3. Assign an atlas plane to each section.
4. Export atlas reference and annotation planes for each section.
5. Generate coarse overlay QC previews.
6. Refine registration section-by-section only where needed.

### 5. Order And Align 2D Sections For Dense Mode

Before using BrainGlobe, the section images must be placed in biological order
and aligned to each other. This is the main custom part of the workflow.

Planned alignment stages:

1. Sort sections by slide and physical position.
2. Manually correct the order if slide layout does not match biological order.
3. Normalize orientation so every section has the same left-right and
   dorsal-ventral convention.
4. Perform rigid or affine section-to-section alignment.
5. Optionally apply non-rigid correction for local tissue distortion.
6. Export a coherent 3D image stack for the registration channel.
7. Apply the same transforms to all signal channels.

For sparse datasets, such as only a small number of widely spaced sections,
full 3D reconstruction may be unreliable. In that case, the safer path is
slice-wise atlas-plane matching followed by section-level atlas summaries.

### 6. Register The Stack To A Rat Atlas With BrainGlobe

Once a coherent 3D stack exists, run `brainreg` with a rat atlas. Candidate
atlases include:

- `whs_sd_rat_39um`: Waxholm Space Sprague Dawley rat atlas;
- `swc_female_rat_50um`: SWC female rat atlas;
- `whs_sd_swc_female_rat_39um`: SWC female rat template aligned to Waxholm
  Space annotations.

The command shape is expected to be:

```powershell
brainreg path\to\registration_channel path\to\brainreg_output `
  -v Z_UM Y_UM X_UM `
  --orientation ORIENTATION `
  --atlas whs_sd_rat_39um `
  -a path\to\signal_channel_1 path\to\signal_channel_2
```

The exact `-v` order and `--orientation` value must be verified against the
prepared stack before production use.

Expected `brainreg` outputs include:

- `registered_atlas.tiff`;
- `registered_hemispheres.tiff`;
- `boundaries.tiff`;
- `downsampled.tiff`;
- `downsampled_standard_*.tiff`;
- deformation fields;
- `volumes.csv`;
- `brainreg.json`.

### 7. Quantify Signals By Atlas Region

After registration, use the warped atlas annotation image to summarize signal
or detected objects by anatomical region.

Planned measurements:

- mean, median, max, and integrated intensity per region and channel;
- labelled cell or object counts per region;
- normalized density per atlas volume or sampled section area;
- hemisphere-specific summaries when relevant;
- QC flags for regions affected by missing or damaged sections.

BrainGlobe Atlas API should provide atlas metadata and structure lookup, while
the repository code should perform dataset-specific table generation.

### 8. Quality Control And Review

Every sample should have QC outputs before downstream interpretation:

- slide crop overlays;
- section order preview;
- aligned stack preview;
- atlas boundary overlay on registered data;
- region summary sanity checks;
- notes for missing, folded, torn, or low-signal sections.

Registration should be rejected or repeated if major landmarks, ventricles,
cortex outline, hippocampus, striatum, or cerebellar boundaries are visibly
misaligned for the target analysis.

## Implementation Overview

### Existing Components

The current package already contains the first stage of the workflow:

```text
src/brain_section_pipeline/
  io.py        ND2 discovery and reading
  crop.py      tissue section detection and crop export
  merge.py     channel scaling and RGB merging
  pipeline.py  end-to-end ND2 crop processing
```

Existing scripts:

```text
scripts/
  preview_nd2.py  downsampled section preview and crop QC
```

These components should remain responsible for raw ND2 ingestion and section
crop generation.

### Planned Source Modules

The next implementation should be added as small reusable modules under
`src/brain_section_pipeline/`, not embedded directly in notebooks.

Proposed modules:

```text
src/brain_section_pipeline/
  export.py              prepare BrainGlobe-ready section folders
  section_manifest.py    validate and edit section metadata
  slice_atlas.py         export per-section atlas planes for sparse mode
  qc.py                  generate slice-wise atlas overlays and review outputs
  slice_registration.py  register each section to its chosen atlas plane
  stack.py               build ordered channel stacks from section images
  alignment.py           run or wrap section-to-section registration
  brainglobe_api.py      small BrainGlobe Atlas API helper layer
  brainreg_runner.py     construct and run brainreg commands
  atlas_summary.py       summarize intensity or objects by atlas region
```

The current implementation priority is sparse slice-wise atlas mode first, with
3D stack and `brainreg` support kept available for later dense datasets.

### Planned Command-Line Entry Points

Proposed scripts:

```text
scripts/
  export_sections.py       export per-section, per-channel image folders
  prepare_slice_atlas.py   export per-section atlas planes for sparse mode
  generate_slice_atlas_qc.py create per-section atlas overlay previews
  register_slices_to_atlas.py run slice-wise 2D registration to atlas planes
  build_stack.py           build an ordered 3D stack from the manifest
  run_brainreg.py          run brainreg with recorded voxel size/orientation
  summarize_atlas.py       produce region-level signal summaries
```

The scripts should be thin clients around package functions. They should not
contain the core image-processing logic.

### BrainGlobe API Usage

Use `brainglobe-atlasapi` for atlas inspection and structure metadata:

```python
from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas

atlas = BrainGlobeAtlas("whs_sd_rat_39um")
reference = atlas.reference
annotation = atlas.annotation
structures = atlas.lookup_df
resolution = atlas.resolution
orientation = atlas.orientation
mask = atlas.get_structure_mask("HIP")
```

Expected uses in this repository:

- verify the selected rat atlas exists locally;
- record atlas name, version, orientation, resolution, and shape;
- map structure IDs to acronyms and names;
- create region masks for analysis or QC;
- summarize registered data by atlas annotations.

Use `brainreg` itself as the registration engine through its command-line
interface unless a stable internal Python API is needed later.

### Metadata Contract

The pipeline should produce and preserve a machine-readable manifest. A minimal
manifest row should include:

```text
sample_id
slide_id
source_file
section_index
section_label
crop_x
crop_y
crop_width
crop_height
pixel_size_x_um
pixel_size_y_um
section_thickness_um
section_interval_um
z_position_um
registration_channel
channel_0_name
channel_1_name
channel_2_name
include_in_stack
qc_status
qc_notes
```

This contract is more important than the exact file layout, because it defines
how raw slide sections become a reproducible 3D reconstruction input.

## What To Do For Your Rat-Slice Workflow

For slide images with multiple isolated sections, the practical path is:

1. Run the ND2 isolation pipeline and export a BrainGlobe-preparation dataset.
2. Inspect the QC overlays and sample manifest to confirm section detection,
   order, and spacing metadata.
3. In sparse mode, assign each section to a rat atlas plane.
4. Export atlas reference and annotation planes per section.
5. Review coarse overlay QC previews and adjust atlas-plane choices as needed.
6. Run real 2D slice-to-atlas registration for each paired section.
7. Only move to stack-building and `brainreg` if you later decide to pursue a
   dense 3D workflow.

For your preferred atlas: the Gaidi lab viewer is useful as a visual reference,
but the production path in this repository should start with a BrainGlobe atlas
that is directly supported by `brainreg`. `whs_sd_rat_39um` is the best default
here because it is natively available through BrainGlobe's atlas ecosystem.

## BrainGlobe Preparation Export

The new reusable entry point is `export_sections_for_brainglobe`.

Example:

```python
from brain_section_pipeline import (
    BrainGlobeExportConfig,
    PipelineConfig,
    export_sections_for_brainglobe,
)

pipeline_config = PipelineConfig(
    mask_channel=0,
    min_area=1_000_000,
    margin=250,
    sort_mode="row_right_to_left",
)

export_config = BrainGlobeExportConfig(
    sample_id="rat_01",
    atlas_name="whs_sd_rat_39um",
    registration_channel=0,
    section_thickness_um=40.0,
    section_interval_um=200.0,
    orientation="asl",
)

result = export_sections_for_brainglobe(
    [
        r"data\Slide_01.nd2",
        r"data\Slide_02.nd2",
        r"data\Slide_03.nd2",
    ],
    output_dir=r"outputs",
    pipeline_config=pipeline_config,
    export_config=export_config,
)
```

This creates a sample folder like:

```text
outputs/
  rat_01/
    section_manifest.csv
    sample_metadata.json
    sections_rgb/
    sections_registration/
    sections_channels/
      ch0/
      ch1/
      ch2/
    qc/
      slide_crop_overlays/
    slide_outputs/
```

The most important handoff file is `section_manifest.csv`. It records the
global section index, slide source, crop geometry, exported file paths, pixel
size, section spacing, z position, registration channel, and QC status.

## Slice-Wise Atlas Mode

For the current goal, use the new slice-wise atlas helpers before thinking
about `brainreg`.

The reusable atlas-plane exporter is `prepare_slice_atlas_inputs`.

Example:

```python
from brain_section_pipeline import SliceAtlasConfig, prepare_slice_atlas_inputs

slice_result = prepare_slice_atlas_inputs(
    r"outputs\rat_01\section_manifest.csv",
    config=SliceAtlasConfig(
        atlas_name="whs_sd_rat_39um",
        anatomical_axis="ap",
        start_slice_index=80,
        slice_index_step=2,
        allowed_qc_statuses=("approved", "pending"),
    ),
)
```

This writes one atlas reference plane and one atlas annotation plane per
selected section.

If you know only an approximate AP coordinate or atlas index, use the atlas
index suggester before committing to a slice-atlas manifest:

```python
from brain_section_pipeline import AtlasIndexSuggestionConfig, suggest_atlas_indices

suggestion_result = suggest_atlas_indices(
    r"outputs\rat_01\section_manifest.csv",
    config=AtlasIndexSuggestionConfig(
        atlas_name="whs_sd_rat_39um",
        start_ap_mm=-7.30,
        search_radius_slices=25,
        top_n=5,
    ),
)
```

This searches a local window of atlas planes for each selected section, runs the
same constrained 2D registration used by the final overlay stage, ranks the
candidates, and writes:

- `atlas_index_candidates.csv` with the top candidates and registration metrics;
- `review_grids/section*_candidate_grid.png` with the top candidates side by
  side for human review;
- `selected_atlas_indices.csv` with the machine-selected best atlas index per
  section;
- `selected_slice_atlas_manifest.csv`, which can be passed directly to
  `register_slices_to_atlas`.

The selected candidate is rank 1. The other saved candidates are intended for
manual review rather than automatic downstream registration.

Atlas-index candidate ranking uses the current boundary-aware registration
score. In addition to Dice/IoU and center/extent penalties, it penalizes
candidates whose lower-threshold visible slice boundary is oversized or falls
outside the atlas mask. The `suggest_atlas_indices.py` script exposes the same
fit controls as `register_slices_to_atlas.py`, including
`--translation-initialization`, `--boundary-fit-weight`, and
`--boundary-containment-weight`, so atlas-plane selection and final overlay
generation can use matched mechanics.

If the physical spacing between isolated sections is known, use
`selection_strategy="spacing_locked"` so the first section anchors the series
and later sections follow the known anatomical interval:

```python
spacing_result = suggest_atlas_indices(
    r"outputs\rat_01\section_manifest.csv",
    config=AtlasIndexSuggestionConfig(
        atlas_name="whs_sd_rat_39um",
        start_ap_mm=-7.30,
        section_interval_um=200.0,
        direction="posterior",
        selection_strategy="spacing_locked",
        search_radius_slices=25,
        top_n=5,
    ),
)
```

In this mode, the first section still selects the best-scoring candidate within
the requested search window. Each later section is selected by stepping from
that first selected atlas index using `section_interval_um` and the atlas
resolution. Nearby candidates are still stored in the review grids, and the
selected spacing-locked candidate is highlighted even when it is not the
highest-scoring local overlay.

If the starting AP estimate may be far from the true first section, use a broad
first-section anchor search:

```powershell
python scripts\suggest_atlas_indices.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --start-ap-mm -7.30 `
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

Here `--anchor-search-radius-slices` applies only to the first selected section.
The normal `--search-radius-slices` still controls the small review window for
later spacing-derived sections. This matters when the first estimate is only a
rough guess: in the WHS 39 um atlas, AP `-7.0 mm` and AP `+2.75 mm` are more
than 250 atlas slices apart. Use `--anchor-search-stride-slices` and
`--anchor-refine-radius-slices` for a faster coarse-to-fine first-section scan;
otherwise a broad anchor radius evaluates every atlas plane in the window.
Use `--min-ap-mm` and `--max-ap-mm` when the section is known to come from a
plausible AP interval, and `--ap-prior-mm` with `--ap-prior-weight` when you
want a soft preference near an expected coordinate rather than a hard single
index.

By default, AP values use the pipeline's existing WHS/native coordinate
conversion. If you want the command line and CSV outputs to speak a
Paxinos/Gaidi-style Bregma AP convention while still using `whs_sd_rat_39um`
for atlas images and masks, set `ap_coordinate_system="paxinos"` or pass
`--ap-coordinate-system paxinos`. The optional
`ap_coordinate_offset_mm`/`--ap-coordinate-offset-mm` stores a calibration
offset between the user-facing Paxinos coordinate and the WHS/native AP
coordinate:

```text
whs_native_ap_mm = paxinos_ap_mm + ap_coordinate_offset_mm
```

Use an offset of `0.0` when you want the Paxinos/Gaidi AP numbers to map
directly to the current WHS plane convention. If a calibration slice shows that
the two coordinate references are shifted for a dataset, set the offset
explicitly and the same conversion will be applied to `--start-ap-mm`,
`--min-ap-mm`, `--max-ap-mm`, and `--ap-prior-mm`. The candidate and selected
CSV files record both the configured user-facing AP values and the underlying
`atlas_native_ap_mm` values used to index the WHS volume.

```powershell
python scripts\suggest_atlas_indices.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --ap-coordinate-system paxinos `
  --ap-coordinate-offset-mm 0.0 `
  --start-ap-mm 2.75 `
  --min-ap-mm 1.5 `
  --max-ap-mm 4.0 `
  --section-interval-um 600 `
  --direction posterior `
  --selection-strategy spacing_locked `
  --top-n 5
```

If you do not know the AP interval, enable automatic AP-range estimation:

```powershell
python scripts\suggest_atlas_indices.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --start-ap-mm -7.30 `
  --section-interval-um 600 `
  --direction posterior `
  --selection-strategy spacing_locked `
  --auto-ap-range `
  --auto-ap-range-stride-slices 10 `
  --auto-ap-range-top-n 5 `
  --auto-ap-range-padding-mm 0.75 `
  --anchor-search-radius-slices 300 `
  --anchor-search-stride-slices 10 `
  --anchor-refine-radius-slices 15 `
  --search-radius-slices 5 `
  --top-n 5
```

Automatic AP-range estimation compares the first section's gross tissue
silhouette to atlas annotation silhouettes and derives a bounded AP interval
before registration scoring. Treat this as experimental: gross silhouettes can
look similar across distant AP positions, especially for damaged or partial
sections. Manual `--min-ap-mm` and `--max-ap-mm` values take precedence when
supplied and remain the preferred option when you know the approximate
anatomical region.

Then generate coarse review overlays:

```python
from brain_section_pipeline import SliceAtlasQcConfig, generate_slice_atlas_qc

qc_result = generate_slice_atlas_qc(
    slice_result.manifest_path,
    config=SliceAtlasQcConfig(),
)
```

This creates overlay previews that place each section onto the chosen atlas
plane using a simple bounding-box fit. These previews are for fast QC and atlas
plane review; they are not final anatomical registrations.

There are also thin script wrappers:

```powershell
python scripts\prepare_slice_atlas.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --anatomical-axis ap `
  --start-slice-index 80 `
  --slice-index-step 2

python scripts\suggest_atlas_indices.py outputs\rat_01\section_manifest.csv `
  --atlas whs_sd_rat_39um `
  --start-ap-mm -7.30 `
  --section-interval-um 200 `
  --direction posterior `
  --selection-strategy spacing_locked `
  --anchor-search-radius-slices 300 `
  --anchor-search-stride-slices 10 `
  --anchor-refine-radius-slices 15 `
  --search-radius-slices 25 `
  --top-n 5

python scripts\generate_slice_atlas_qc.py outputs\rat_01\slice_atlas\slice_atlas_manifest.csv

python scripts\register_slices_to_atlas.py outputs\rat_01\slice_atlas\slice_atlas_manifest.csv `
  --max-rotation-degrees 30 `
  --translation-search-fraction 0.2
```

When using `suggest_atlas_indices.py`, use its
`selected_slice_atlas_manifest.csv` as the input to
`register_slices_to_atlas.py`.

For sparse histology sections where the tissue is not centered inside its crop,
prefer the default tissue-centroid translation initialization. This maps the
section tissue centroid to the atlas centroid before the local fit search. The
overlay PNGs also hide section pixels outside a permissive warped display mask
by default, which avoids treating rectangular crop background as aligned tissue
without using the stricter registration mask to fade real brain texture. Tune
this display-only mask with `--overlay-mask-threshold-quantile` and
`--overlay-mask-dilation-px`. Use `--translation-initialization crop_center` to
recover the older crop-center initialization, or `--show-crop-background` when
you explicitly want to see the full warped crop rectangle.

If the visible slice boundary is consistently larger than the atlas boundary,
enable or tune the outer-boundary containment term. This uses a lower-threshold
slice mask to discourage transforms where the visible slice extends beyond the
selected atlas plane:

```powershell
python scripts\register_slices_to_atlas.py outputs\rat_01\selected_slice_atlas_manifest.csv `
  --translation-initialization tissue_centroid `
  --max-rotation-degrees 1 `
  --min-scale-factor 0.65 `
  --max-scale-factor 1.05 `
  --boundary-fit-threshold-quantile 0.35 `
  --boundary-fit-weight 0.25 `
  --boundary-containment-weight 0.9 `
  --overlay-mask-threshold-quantile 0.35 `
  --overlay-mask-dilation-px 10
```

Increase `--boundary-containment-weight` when the visible slice remains too
large, or decrease it if the slice becomes too small relative to inner anatomy.

For a single-command sparse workflow test, use:

```powershell
python scripts\run_slicewise_workflow.py "path\to\slides_or_folder" `
  --output-dir outputs `
  --sample-id rat_01 `
  --atlas whs_sd_rat_39um `
  --sort-mode row_right_to_left `
  --final-box-padding 32 `
  --start-slice-index 80 `
  --slice-index-step 2
```

This wrapper runs section export, atlas-plane preparation, optional QC
overlays, slice registration, and optional atlas summaries in sequence.

The registration stage is `register_slices_to_atlas`.

Example:

```python
from brain_section_pipeline import SliceRegistrationConfig, register_slices_to_atlas

registration_result = register_slices_to_atlas(
    slice_result.manifest_path,
    config=SliceRegistrationConfig(
        max_rotation_degrees=0.0,
        min_scale_factor=0.8,
        max_scale_factor=1.0,
    ),
)
```

This stage writes:

- a warped section image for each atlas-paired slice;
- a registration overlay for visual review;
- a registration manifest with transform parameters and overlap metrics.

The current transform model is slice-wise similarity registration
(scale/rotation/translation) against the selected 2D atlas plane. That makes
it a real reusable section-to-atlas alignment stage for sparse workflows, but
it is still intentionally separate from 3D reconstruction and full atlas-plane
search. The default registration now initializes scale from the section and
atlas mask bounding boxes, keeps rotation fixed at neutral orientation unless
you opt into a rotation search, and penalizes substantial warped-mask size and
center mismatches. This makes the final overlays less likely to look oversized,
off-center, or spuriously rotated for large slide-derived crops.

Once those warped sections exist, the next reusable step is
`summarize_registered_slices_by_region`.

Example:

```python
from brain_section_pipeline import AtlasSummaryConfig, summarize_registered_slices_by_region

summary_result = summarize_registered_slices_by_region(
    registration_result.manifest_path,
    config=AtlasSummaryConfig(
        include_background=False,
        min_region_pixels=8,
    ),
)
```

This writes:

- a per-section per-region CSV summary;
- an aggregate per-region CSV across all registered slices;
- a JSON metadata sidecar describing the summary run.

There is also a thin script wrapper:

```powershell
python scripts\summarize_atlas.py outputs\rat_01\slice_atlas\slice_registration\slice_registration_manifest.csv `
  --min-region-pixels 8
```

## Running BrainGlobe After Export In Dense Mode

The export stage does not run `brainreg` for you yet. The next step is to use
`sections_registration/` plus the section manifest to build an ordered volume
with the correct z spacing, then run `brainreg` on that volume.

The reusable stack builder is `build_stack_from_manifest`.

Example:

```python
from brain_section_pipeline import StackBuildConfig, build_stack_from_manifest

stack_result = build_stack_from_manifest(
    r"outputs\rat_01\section_manifest.csv",
    config=StackBuildConfig(
        source_kind="registration",
        placement_mode="center",
        allowed_qc_statuses=("approved", "pending"),
    ),
)
```

This writes a stack TIFF and a JSON sidecar under:

```text
outputs/
  rat_01/
    stacks/
      rat_01_registration_stack.tif
      rat_01_registration_stack.json
```

There is also a thin script wrapper:

```powershell
python scripts\build_stack.py outputs\rat_01\section_manifest.csv `
  --source-kind registration `
  --placement-mode center `
  --qc-status approved
```

Current stack-placement modes:

- `center`: pad every section onto a common canvas centered by crop size.
- `original_coords`: place every section using its original slide crop bounds
  (`y0`, `x0`, `y1`, `x1`) from the manifest.

Important caveat: this stack builder preserves order and spacing metadata, but
it does not perform section-to-section image registration yet. It is a
reproducible intermediate volume, not a substitute for rigid or nonrigid
alignment when anatomical consistency matters.

The new reusable `brainreg` handoff is `prepare_brainreg_run`.

Example:

```python
from brain_section_pipeline import BrainRegConfig, prepare_brainreg_run

brainreg_result = prepare_brainreg_run(
    r"outputs\rat_01\stacks\rat_01_registration_stack.json",
    config=BrainRegConfig(
        additional_channels=(1, 2),
        debug=True,
        save_original_orientation=True,
    ),
)
```

This writes a prepared folder containing:

```text
outputs/
  rat_01/
    stacks/
      brainreg_input/
        registration/
          slice_0001.tif
          slice_0002.tif
        additional/
          ch1/
          ch2/
        brainreg_output/
        run_brainreg.ps1
        brainreg_preparation.json
```

There is also a thin script wrapper:

```powershell
python scripts\run_brainreg.py outputs\rat_01\stacks\rat_01_registration_stack.json `
  --additional-channel 1 `
  --additional-channel 2 `
  --debug `
  --save-original-orientation
```

This step does three practical things:

- reads the stack JSON sidecar to recover voxel size and section-selection
  settings;
- expands the 3D TIFF stack into the slice-directory layout that `brainreg`
  expects;
- builds a reproducible `brainreg` command and writes it to
  `run_brainreg.ps1`.

Conceptually, the command will look like:

```powershell
brainreg path\to\prepared_registration_slices path\to\brainreg_output `
  -v Z_UM Y_UM X_UM `
  --orientation asl `
  --atlas whs_sd_rat_39um
```

Important caveat: `brainreg` expects a coherent 3D volume. If your sample has
only sparse sections with large anatomical gaps, do not expect whole-brain
registration quality to be good without either section-to-section
reconstruction or slice-wise atlas matching.

### Current Preparation Milestone

The repository now implements both sparse slice-wise atlas preparation and the
earlier dense-mode stack/BrainGlobe handoff pieces:

1. Read all ND2 files for a sample.
2. Detect and crop sections.
3. Export RGB previews and raw per-channel TIFF crops.
4. Write a sample-level `section_manifest.csv`.
5. Include physical metadata fields for pixel size, section thickness, section
   interval, and z position.
6. Generate QC overlays.
7. Optionally load `BrainGlobeAtlas` to write atlas metadata.
8. Export per-section atlas reference and annotation planes for sparse mode.
9. Generate coarse slice-to-atlas overlay previews for sparse mode.
10. Run per-section 2D slice-to-atlas registration for sparse mode.
11. Summarize warped sections by atlas region for sparse mode.
12. Build an ordered stack TIFF from the sample manifest for dense mode.
13. Prepare a `brainreg` input directory and command from that stack metadata
    for dense mode.

This milestone makes the dataset inspectable and ready for either sparse
slice-wise atlas matching now or fuller 3D `brainreg` workflows later.

## References

- [BrainGlobe documentation](https://brainglobe.info/documentation/)
- [brainreg documentation](https://brainglobe.info/documentation/brainreg/index.html)
- [brainreg command-line tool](https://brainglobe.info/documentation/brainreg/user-guide/brainreg-cli.html)
- [BrainGlobeAtlas API](https://brainglobe.info/documentation/brainglobe-atlasapi/api/brainglobe_atlasapi.bg_atlas.BrainGlobeAtlas.html)
- [BrainGlobe histology segmentation guide](reference/brainglobe-histology-segmentation-guide.md)
- [Paperflow reconstruction review](paperflow/2d-rat-slice-3d-reconstruction/reviews/brainj-vs-brainglobe-workflows.md)
