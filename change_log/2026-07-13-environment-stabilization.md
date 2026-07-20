# Environment Stabilization

Date: 2026-07-13

Git state: uncommitted changes in the working tree.

Implementation plan: [2026-07-13 Environment Stabilization](../implementation_plan/2026-07-13-environment-stabilization.md)

## What Changed

- Updated `environment.yml` so the main `histology` environment:
  - uses `conda-forge` plus `nodefaults`;
  - avoids `defaults` packages in the declared environment;
  - uses conservative upper bounds for `numpy`, `scipy`, and `scikit-image`;
  - installs the repository in editable mode with the atlas-only optional
    dependency group.
- Added `environment-brainreg.yml` for dense-mode BrainReg work:
  - uses the same conda channel policy and conservative scientific bounds;
  - installs the repository in editable mode with the `brainreg` optional
    dependency group.
- Updated `pyproject.toml` optional dependencies:
  - added `atlas` for `brainglobe-atlasapi` only;
  - added `brainreg` for `brainglobe-atlasapi` plus `brainreg`;
  - kept `brainglobe` as a compatibility alias for dense BrainGlobe
    dependencies.
- Updated `.gitignore` to ignore generated `*.egg-info/` packaging metadata.
- Added README setup instructions for:
  - the main `histology` environment;
  - a conda-forge-only fallback recreate command for conda installations that
    still check configured `defaults` Terms of Service before honoring
    `nodefaults`;
  - the separate `histology-brainreg` environment;
  - the distinction between BrainGlobe packages and downloaded atlas data;
  - the observed Windows BrainReg CLI/native crash risk.
- Added and indexed the implementation plan for this change.

## Why The Change Was Made

The recreated `histology` environment worked for package imports, but the
BrainReg CLI path triggered a Windows `python.exe` application error
(`0xc06d007f`) during verification. Since the current primary workflow is
sparse slice-wise atlas matching, BrainReg should not be required in the main
environment. Splitting the environments keeps day-to-day ND2 and atlas-plane
work lighter and isolates dense-mode BrainReg/napari/Qt/NiftyReg risk.

The conda environment creation also initially failed because the local conda
configuration consulted Anaconda `defaults` channels whose Terms of Service had
not been accepted. Adding `nodefaults` makes the environment specification
explicitly conda-forge-only, and the README now includes the explicit
`--override-channels` recreate command that worked on this machine.

## Verification Performed

- YAML parse check:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -c "import pathlib, yaml; [yaml.safe_load(pathlib.Path(p).read_text()) for p in ('environment.yml', 'environment-brainreg.yml')]; print('yaml ok')"
```

Result: `yaml ok`.

- Whitespace check:

```powershell
git diff --check
```

Result: no whitespace errors. Git reported line-ending warnings for files that
will be normalized to CRLF when Git next touches them.

- Package health check in the existing recreated environment:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pip check
```

Result: `No broken requirements found.`

- Main environment recreation:

```powershell
C:\Users\Cornell\miniconda3\Scripts\conda.exe remove -n histology --all -y --override-channels -c conda-forge
C:\Users\Cornell\miniconda3\Scripts\conda.exe create -n histology --override-channels -c conda-forge python=3.11 pip ipykernel ipywidgets jupyterlab matplotlib "numpy<2.3" pillow pytest "scikit-image<0.26" "scipy<1.16" tk tifffile xarray -y
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pip install -e ".[atlas]" --no-build-isolation
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m ipykernel install --user --name histology --display-name "Python (histology)"
```

Result: the old `histology` environment was removed and recreated. The package
installed in editable mode with `nd2` and `brainglobe-atlasapi`; the Jupyter
kernel was registered at
`C:\Users\Cornell\AppData\Roaming\jupyter\kernels\histology`.

- Recreated-environment import check:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -c "import sys; import brain_section_pipeline, nd2, brainglobe_atlasapi; print('imports ok', sys.version.split()[0])"
```

Result: `imports ok 3.11.15`.

- Recreated-environment BrainReg isolation check:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -c "import importlib.util; print(importlib.util.find_spec('brainreg'))"
```

Result: `None`, confirming `brainreg` is not installed in the main atlas-only
environment.

- Focused test run in the recreated environment:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -q
```

Result: `27 passed, 3 failed`. The failures are the same code/test issues
observed before recreating the environment: one crop-fragment merge expectation
and two tests that reference `BrainGlobeExportResult` without it being defined
in the test module.

- Atlas optional-extra metadata dry run:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pip install -e ".[atlas]" --dry-run --no-build-isolation
```

Result: metadata prepared successfully and pip reported it would install
`brain-section-pipeline-0.1.0`.

- BrainReg optional-extra metadata dry run:

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pip install -e ".[brainreg]" --dry-run --no-build-isolation
```

Result: metadata prepared successfully and pip reported it would install
`brain-section-pipeline-0.1.0`.

An earlier `pip install -e ".[atlas]" --dry-run` attempt without
`--no-build-isolation` failed because the sandbox blocked PyPI access while
pip tried to fetch isolated build dependencies. The no-build-isolation dry run
confirmed the project metadata using already installed build tooling.

## Result Or Observed Behavior

The repository now has separate environment specifications for:

- sparse slice-wise atlas work: `environment.yml` / `histology`;
- dense BrainReg handoff work: `environment-brainreg.yml` /
  `histology-brainreg`.

Future `conda env create -f environment.yml` runs should not require accepting
Anaconda `defaults` channel Terms of Service on conda installations that honor
`nodefaults` before checking configured channels. On this machine, that command
still failed before environment creation because the local conda installation
checked unaccepted `defaults` channels first; the explicit
`conda create --override-channels -c conda-forge ...` fallback succeeded.

## Known Limitations And Next Steps

- The recreated `histology` environment is now atlas-only. To use dense-mode
  BrainReg later, create `histology-brainreg` from `environment-brainreg.yml`.
- Plain `conda env create -f environment.yml` may still fail on this local
  conda installation until the configured Anaconda `defaults` channel Terms of
  Service are accepted or removed from configuration. The documented fallback
  command avoids `defaults` for the recreated main environment.
- The BrainReg CLI/native Windows crash path was not fixed in this change. Use
  `environment-brainreg.yml` only when dense-mode BrainReg execution is needed,
  and treat CLI startup as something to verify separately.
- BrainGlobe atlas datasets are not bundled with the environment. They still
  need to be downloaded by `brainglobe-atlasapi` when first requested.
