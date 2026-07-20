# Environment Stabilization

Date: 2026-07-13

## Goal And Motivation

Make the repository environment easier to recreate and safer to use on Windows
for the current ND2-to-slice-wise-atlas workflow. The main goal is to keep the
day-to-day `histology` environment focused on stable sparse slice-wise work,
while keeping dense-mode `brainreg` support available in a separate opt-in
environment.

## Current Problem

Creating the current `environment.yml` with plain `conda env create -f
environment.yml` can fail on this machine because conda consults Anaconda
`defaults` channels whose Terms of Service have not been accepted. The
successful workaround used `conda-forge` only.

The current environment file also installs `brainreg` directly into the main
workflow environment. That brings in napari, Qt, and bundled/native NiftyReg
pieces. During verification, starting the BrainReg CLI path produced a Windows
`python.exe` application error (`0xc06d007f`) and direct import of
`brainreg.core.cli` did not return promptly. This suggests the dense BrainReg
CLI path is a separate environment risk from the repository's current
slice-wise atlas workflow.

Finally, the environment file is lightly pinned, so it can resolve to very new
scientific packages. The recreated environment pulled newer versions than the
code was originally tested around, and the focused test command showed existing
repo test failures. Keeping conservative upper bounds should make future
recreates less surprising.

## Why This Is Needed Now

The user asked to implement the recommended environment changes after the
freshly recreated environment showed a BrainReg-related native Windows error.
The sparse slice-wise pipeline should remain convenient to run without being
blocked by dense-mode BrainReg CLI instability.

## Git Or Worktree State

`git status --short` showed only an untracked generated editable-install
artifact at `src/brain_section_pipeline.egg-info/` before these edits. The
change should ignore that generated metadata rather than treating it as source.

## Affected Files

- `environment.yml`: make the main environment conda-forge-only, conservative,
  and focused on slice-wise atlas work.
- `environment-brainreg.yml`: add a separate dense-mode BrainReg environment.
- `pyproject.toml`: split optional extras so atlas-only and BrainReg workflows
  can be installed separately.
- `.gitignore`: ignore generated Python packaging metadata.
- `README.md`: document environment creation, atlas-data download state, and
  the BrainReg Windows caveat.
- `implementation_plan/README.md`: index this plan.
- `change_log/`: document the completed environment change after verification.

## Public Parameters Or API Changes

No runtime API changes are intended.

Optional dependency groups should become clearer:

- `atlas`: BrainGlobe Atlas API only, for sparse slice-wise atlas work.
- `brainreg`: BrainGlobe Atlas API plus `brainreg`, for dense-mode handoff.
- `brainglobe`: retained as a compatibility alias for dense-mode BrainGlobe
  dependencies.

## Expected Behavior

`environment.yml` should declare a conda-forge-only environment with
`nodefaults`. If the local conda executable still consults configured
`defaults` channels before honoring `nodefaults`, the README should document a
reliable explicit `conda create --override-channels -c conda-forge ...`
fallback instead of requiring the user to accept Anaconda Terms of Service.

The main `histology` environment should install the package in editable mode
with atlas-only BrainGlobe support and should be sufficient for ND2 ingestion,
slice isolation, slice-wise atlas plane export, QC overlays, slice-wise
registration, and atlas summaries.

Dense-mode `brainreg` work should use the separate BrainReg environment file
so BrainReg/napari/Qt/NiftyReg native issues are isolated from the main
slice-wise workflow.

## Verification

- Read the updated YAML files for valid conda/pip structure.
- Run `git diff --check`.
- Run focused import checks in the existing recreated environment where
  practical.
- Do not relaunch the BrainReg CLI repeatedly because the current Windows
  native error path has already been observed.

## Non-Goals

- Do not debug or patch upstream BrainReg, napari, Qt, or NiftyReg internals in
  this change.
- Do not remove dense-mode support from repository code.
- Do not accept Anaconda Terms of Service automatically.
- Do not attempt to download atlas data as part of environment creation.
