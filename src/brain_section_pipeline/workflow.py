"""High-level orchestration for sparse slice-wise atlas workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .atlas_summary import AtlasSummaryConfig, AtlasSummaryResult, summarize_registered_slices_by_region
from .export import BrainGlobeExportConfig, BrainGlobeExportResult, export_sections_for_brainglobe
from .io import find_nd2_files
from .pipeline import PipelineConfig
from .qc import SliceAtlasQcConfig, SliceAtlasQcResult, generate_slice_atlas_qc
from .slice_atlas import SliceAtlasConfig, SliceAtlasResult, prepare_slice_atlas_inputs
from .slice_registration import SliceRegistrationConfig, SliceRegistrationResult, register_slices_to_atlas


@dataclass(frozen=True)
class SliceWorkflowResult:
    """Artifacts produced by a full sparse slice-wise atlas workflow run."""

    input_paths: list[Path]
    export_result: BrainGlobeExportResult
    slice_atlas_result: SliceAtlasResult
    qc_result: SliceAtlasQcResult | None
    registration_result: SliceRegistrationResult
    summary_result: AtlasSummaryResult | None


def run_slicewise_atlas_workflow(
    inputs: str | Path | Sequence[str | Path],
    output_dir: str | Path,
    *,
    pipeline_config: PipelineConfig | None = None,
    export_config: BrainGlobeExportConfig | None = None,
    slice_atlas_config: SliceAtlasConfig | None = None,
    qc_config: SliceAtlasQcConfig | None = None,
    registration_config: SliceRegistrationConfig | None = None,
    atlas_summary_config: AtlasSummaryConfig | None = None,
    generate_qc: bool = True,
    generate_summary: bool = True,
) -> SliceWorkflowResult:
    """Run export, atlas pairing, optional QC, registration, and optional summary."""

    nd2_paths = _resolve_nd2_inputs(inputs)
    export_result = export_sections_for_brainglobe(
        nd2_paths,
        output_dir,
        pipeline_config=pipeline_config,
        export_config=export_config,
    )
    slice_atlas_result = prepare_slice_atlas_inputs(
        export_result.manifest_path,
        config=slice_atlas_config,
    )

    qc_result: SliceAtlasQcResult | None = None
    if generate_qc:
        qc_result = generate_slice_atlas_qc(
            slice_atlas_result.manifest_path,
            config=qc_config,
        )

    registration_result = register_slices_to_atlas(
        slice_atlas_result.manifest_path,
        config=registration_config,
    )

    summary_result: AtlasSummaryResult | None = None
    if generate_summary:
        summary_result = summarize_registered_slices_by_region(
            registration_result.manifest_path,
            config=atlas_summary_config,
        )

    return SliceWorkflowResult(
        input_paths=nd2_paths,
        export_result=export_result,
        slice_atlas_result=slice_atlas_result,
        qc_result=qc_result,
        registration_result=registration_result,
        summary_result=summary_result,
    )


def _resolve_nd2_inputs(inputs: str | Path | Sequence[str | Path]) -> list[Path]:
    if isinstance(inputs, (str, Path)):
        candidate = Path(inputs)
        if candidate.is_dir():
            paths = find_nd2_files(candidate)
            if not paths:
                raise ValueError(f"No ND2 files were found under {candidate}.")
            return paths
        return [candidate]

    paths = [Path(path) for path in inputs]
    if not paths:
        raise ValueError("At least one ND2 input path is required.")
    return paths
