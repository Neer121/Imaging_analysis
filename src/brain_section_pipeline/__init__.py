"""ND2 channel merging and brain section crop pipeline."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "BrainRegConfig": ("brainreg_runner", "BrainRegConfig"),
    "BrainRegPreparationResult": ("brainreg_runner", "BrainRegPreparationResult"),
    "CropBox": ("crop", "CropBox"),
    "CropDetectionResult": ("crop", "CropDetectionResult"),
    "DEFAULT_CHANNEL_COLORS": ("merge", "DEFAULT_CHANNEL_COLORS"),
    "BrainGlobeExportConfig": ("export", "BrainGlobeExportConfig"),
    "BrainGlobeExportResult": ("export", "BrainGlobeExportResult"),
    "AtlasSummaryConfig": ("atlas_summary", "AtlasSummaryConfig"),
    "AtlasSummaryResult": ("atlas_summary", "AtlasSummaryResult"),
    "AtlasIndexSuggestionConfig": ("atlas_indexing", "AtlasIndexSuggestionConfig"),
    "AtlasIndexSuggestionResult": ("atlas_indexing", "AtlasIndexSuggestionResult"),
    "AtlasPreviewExportResult": ("atlas_indexing", "AtlasPreviewExportResult"),
    "ap_mm_to_atlas_index": ("atlas_indexing", "ap_mm_to_atlas_index"),
    "atlas_index_to_ap_mm": ("atlas_indexing", "atlas_index_to_ap_mm"),
    "atlas_native_ap_mm_to_coordinate_ap_mm": ("atlas_indexing", "atlas_native_ap_mm_to_coordinate_ap_mm"),
    "coordinate_ap_mm_to_atlas_native_ap_mm": ("atlas_indexing", "coordinate_ap_mm_to_atlas_native_ap_mm"),
    "Nd2Image": ("io", "Nd2Image"),
    "PipelineConfig": ("pipeline", "PipelineConfig"),
    "ProcessingResult": ("pipeline", "ProcessingResult"),
    "SliceAtlasConfig": ("slice_atlas", "SliceAtlasConfig"),
    "SliceAtlasQcConfig": ("qc", "SliceAtlasQcConfig"),
    "SliceAtlasQcResult": ("qc", "SliceAtlasQcResult"),
    "SliceAtlasResult": ("slice_atlas", "SliceAtlasResult"),
    "SliceRegistrationConfig": ("slice_registration", "SliceRegistrationConfig"),
    "SliceRegistrationResult": ("slice_registration", "SliceRegistrationResult"),
    "SliceWorkflowResult": ("workflow", "SliceWorkflowResult"),
    "StackBuildConfig": ("stack", "StackBuildConfig"),
    "StackBuildResult": ("stack", "StackBuildResult"),
    "build_stack_from_manifest": ("stack", "build_stack_from_manifest"),
    "crop_sections": ("crop", "crop_sections"),
    "detect_section_crops": ("crop", "detect_section_crops"),
    "prepare_brainreg_run": ("brainreg_runner", "prepare_brainreg_run"),
    "find_nd2_files": ("io", "find_nd2_files"),
    "export_sections_for_brainglobe": ("export", "export_sections_for_brainglobe"),
    "export_selected_atlas_previews": ("atlas_indexing", "export_selected_atlas_previews"),
    "generate_slice_atlas_qc": ("qc", "generate_slice_atlas_qc"),
    "merge_channels": ("merge", "merge_channels"),
    "prepare_slice_atlas_inputs": ("slice_atlas", "prepare_slice_atlas_inputs"),
    "process_nd2_file": ("pipeline", "process_nd2_file"),
    "process_selected_files": ("pipeline", "process_selected_files"),
    "read_nd2_image": ("io", "read_nd2_image"),
    "register_slices_to_atlas": ("slice_registration", "register_slices_to_atlas"),
    "run_slicewise_atlas_workflow": ("workflow", "run_slicewise_atlas_workflow"),
    "suggest_atlas_indices": ("atlas_indexing", "suggest_atlas_indices"),
    "robust_scale": ("merge", "robust_scale"),
    "sanitize_array": ("merge", "sanitize_array"),
    "select_nd2_files_dialog": ("io", "select_nd2_files_dialog"),
    "summarize_registered_slices_by_region": ("atlas_summary", "summarize_registered_slices_by_region"),
    "summarize_nd2": ("io", "summarize_nd2"),
    "run_prepared_brainreg": ("brainreg_runner", "run_prepared_brainreg"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
