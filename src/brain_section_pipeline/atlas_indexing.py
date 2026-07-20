"""Suggest atlas slice indices for sparse slice-wise registration."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy import ndimage
from tifffile import imread, imwrite

from .slice_registration import (
    SliceRegistrationConfig,
    _bbox,
    _boundary_mask,
    _compose_overlay,
    _grayscale_image,
    _prepare_section_registration_input,
    _register_prepared_section_to_atlas,
    _resize_image,
    _tissue_mask,
)


AxisName = Literal["ap", "si", "dv", "rl", "ml"]
DirectionName = Literal["posterior", "anterior"]
SectionSource = Literal["registration", "rgb", "channel"]
SelectionStrategy = Literal["best_score", "spacing_locked"]
APCoordinateSystem = Literal["atlas", "paxinos"]


@dataclass(frozen=True)
class AtlasIndexSuggestionConfig:
    """Configuration for atlas-index candidate search."""

    atlas_name: str = "whs_sd_rat_39um"
    anatomical_axis: AxisName = "ap"
    ap_coordinate_system: APCoordinateSystem = "atlas"
    ap_coordinate_offset_mm: float = 0.0
    section_source: SectionSource = "registration"
    channel: int | None = None
    sample_id: str | None = None
    require_include_in_stack: bool = True
    start_ap_mm: float | None = None
    start_slice_index: int | None = None
    section_interval_um: float | None = None
    slice_index_step: int = 0
    direction: DirectionName = "posterior"
    selection_strategy: SelectionStrategy = "best_score"
    search_radius_slices: int = 25
    anchor_search_radius_slices: int | None = None
    anchor_search_stride_slices: int = 1
    anchor_refine_radius_slices: int | None = None
    min_ap_mm: float | None = None
    max_ap_mm: float | None = None
    ap_prior_mm: float | None = None
    ap_prior_weight: float = 0.0
    auto_ap_range: bool = False
    auto_ap_range_stride_slices: int = 10
    auto_ap_range_top_n: int = 5
    auto_ap_range_padding_mm: float = 0.75
    auto_ap_range_shape_size: int = 96
    auto_ap_range_tissue_quantile: float = 0.5
    top_n: int = 5
    boundary_distance_weight: float = 0.35
    dorsal_midline_weight: float = 0.45
    registration_config: SliceRegistrationConfig = field(default_factory=SliceRegistrationConfig)
    output_name: str = "atlas_index_suggestions"
    candidate_manifest_name: str = "atlas_index_candidates.csv"
    selected_manifest_name: str = "selected_slice_atlas_manifest.csv"
    selected_choices_name: str = "selected_atlas_indices.csv"
    metadata_name: str = "atlas_index_suggestions.json"


@dataclass(frozen=True)
class AtlasIndexSuggestionResult:
    """Artifacts produced by atlas-index candidate search."""

    output_dir: Path
    candidate_manifest_path: Path
    selected_manifest_path: Path
    selected_choices_path: Path
    metadata_path: Path
    review_grid_paths: list[Path]
    selected_section_indices: list[int]
    atlas_preview_paths: list[Path]
    atlas_preview_contact_sheet_path: Path | None


@dataclass(frozen=True)
class AtlasPreviewExportResult:
    """Atlas-only PNG previews exported from a selected slice-atlas manifest."""

    output_dir: Path
    preview_paths: list[Path]
    contact_sheet_path: Path | None


def suggest_atlas_indices(
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    config: AtlasIndexSuggestionConfig | None = None,
) -> AtlasIndexSuggestionResult:
    """Search nearby atlas planes and pick a best atlas index per section."""

    cfg = config or AtlasIndexSuggestionConfig()
    manifest = Path(manifest_path)
    rows = _selected_rows(_read_manifest_rows(manifest), cfg)
    if not rows:
        raise ValueError("No section rows were selected for atlas-index suggestion.")
    if cfg.selection_strategy not in {"best_score", "spacing_locked"}:
        raise ValueError("selection_strategy must be 'best_score' or 'spacing_locked'.")
    _validate_ap_coordinate_config(cfg.ap_coordinate_system, cfg.ap_coordinate_offset_mm)

    atlas = _load_atlas(cfg.atlas_name)
    atlas_reference = np.asarray(atlas.reference)
    atlas_annotation = np.asarray(atlas.annotation)
    atlas_orientation = str(getattr(atlas, "orientation", "")).lower()
    atlas_resolution = list(getattr(atlas, "resolution", []))
    slice_axis = _axis_index_from_orientation(atlas_orientation, cfg.anatomical_axis)

    target_dir = Path(output_dir) if output_dir is not None else manifest.parent / cfg.output_name
    candidates_dir = target_dir / "candidates"
    review_grid_dir = target_dir / "review_grids"
    selected_reference_dir = target_dir / "selected" / "atlas_reference"
    selected_annotation_dir = target_dir / "selected" / "atlas_annotation"
    selected_sections_dir = target_dir / "selected" / "sections"
    selected_overlay_dir = target_dir / "selected" / "overlays"
    selected_atlas_preview_dir = target_dir / "selected" / "atlas_previews"
    for directory in (
        candidates_dir,
        review_grid_dir,
        selected_reference_dir,
        selected_annotation_dir,
        selected_sections_dir,
        selected_overlay_dir,
        selected_atlas_preview_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    candidate_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    selected_choice_rows: list[dict[str, Any]] = []
    review_grid_paths: list[Path] = []
    atlas_preview_paths: list[Path] = []
    selected_section_indices: list[int] = []
    spacing_anchor_index: int | None = None
    spacing_step_indices = _spacing_step_indices(
        cfg,
        resolution_um=float(atlas_resolution[slice_axis]),
        orientation=atlas_orientation,
        axis_index=slice_axis,
    )
    if cfg.selection_strategy == "spacing_locked" and len(rows) > 1 and spacing_step_indices == 0:
        raise ValueError("spacing_locked selection requires section_interval_um or a non-zero slice_index_step.")
    auto_ap_range_result: dict[str, Any] | None = None
    effective_min_ap_mm = cfg.min_ap_mm
    effective_max_ap_mm = cfg.max_ap_mm
    if cfg.auto_ap_range and cfg.min_ap_mm is None and cfg.max_ap_mm is None:
        first_section_image = _grayscale_image(_section_source_path(rows[0], cfg))
        auto_ap_range_result = _estimate_auto_ap_range(
            first_section_image,
            atlas_annotation=atlas_annotation,
            atlas_resolution=atlas_resolution,
            atlas_orientation=atlas_orientation,
            slice_axis=slice_axis,
            cfg=cfg,
        )
        effective_min_ap_mm = float(auto_ap_range_result["min_ap_mm"])
        effective_max_ap_mm = float(auto_ap_range_result["max_ap_mm"])

    for ordinal, row in enumerate(rows):
        section_index = int(row["section_index"])
        if cfg.selection_strategy == "spacing_locked" and ordinal > 0:
            if spacing_anchor_index is None:
                raise ValueError("spacing_locked selection could not establish a first-section anchor.")
            expected_index = int(
                np.clip(
                    spacing_anchor_index + ordinal * spacing_step_indices,
                    0,
                    atlas_reference.shape[slice_axis] - 1,
                )
            )
            forced_selected_index: int | None = expected_index
        else:
            expected_index = _expected_index_for_row(
                ordinal,
                cfg,
                axis_length=atlas_reference.shape[slice_axis],
                resolution_um=float(atlas_resolution[slice_axis]),
                orientation=atlas_orientation,
                axis_index=slice_axis,
            )
            forced_selected_index = None
        expected_ap_mm = atlas_index_to_ap_mm(
            expected_index,
            shape=atlas_reference.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
            coordinate_system=cfg.ap_coordinate_system,
            ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
        )
        expected_atlas_native_ap_mm = atlas_index_to_ap_mm(
            expected_index,
            shape=atlas_reference.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
        )
        search_radius = _search_radius_for_row(ordinal, cfg)
        section_path = _section_source_path(row, cfg)
        section_image = _grayscale_image(section_path)
        prepared_section = _prepare_section_registration_input(section_image, cfg.registration_config)
        section_candidate_dir = candidates_dir / f"section{section_index:03d}"
        section_candidate_dir.mkdir(parents=True, exist_ok=True)

        ranked = _rank_candidates_for_row(
            ordinal,
            cfg,
            expected_index=expected_index,
            search_radius=search_radius,
            axis_length=atlas_reference.shape[slice_axis],
            atlas_reference=atlas_reference,
            atlas_annotation=atlas_annotation,
            atlas_resolution=atlas_resolution,
            atlas_orientation=atlas_orientation,
            slice_axis=slice_axis,
            section_image=section_image,
            prepared_section=prepared_section,
            min_ap_mm=_constraint_for_row(ordinal, cfg, effective_min_ap_mm),
            max_ap_mm=_constraint_for_row(ordinal, cfg, effective_max_ap_mm),
            ap_prior_mm=_constraint_for_row(ordinal, cfg, cfg.ap_prior_mm),
            ap_prior_weight=cfg.ap_prior_weight if _constraints_apply_to_row(ordinal, cfg) else 0.0,
        )

        ranked.sort(key=lambda item: item["score"], reverse=True)
        if not ranked:
            raise ValueError(f"No atlas candidates were produced for section {section_index}.")
        for score_rank, candidate in enumerate(ranked, start=1):
            candidate["score_rank"] = score_rank

        selected = _select_candidate(ranked, forced_selected_index)
        selected_index = int(selected["atlas_slice_index"])
        top_candidates = _review_candidates(ranked, top_n=cfg.top_n, forced_index=selected_index)
        for candidate in top_candidates:
            candidate["is_selected_candidate"] = int(candidate["atlas_slice_index"]) == selected_index

        overlay_paths: list[Path] = []
        for review_rank, candidate in enumerate(top_candidates, start=1):
            is_selected = int(candidate["atlas_slice_index"]) == selected_index
            atlas_slice_index = int(candidate["atlas_slice_index"])
            overlay_path = section_candidate_dir / f"rank{review_rank:02d}_index{atlas_slice_index:04d}_overlay.png"
            Image.fromarray(candidate["overlay"], mode="RGB").save(overlay_path)
            overlay_paths.append(overlay_path)

            candidate_rows.append(
                _candidate_manifest_row(
                    row,
                    review_rank=review_rank,
                    is_selected=is_selected,
                    selection_strategy=cfg.selection_strategy,
                    search_radius=search_radius,
                    expected_index=expected_index,
                    expected_ap_mm=expected_ap_mm,
                    expected_atlas_native_ap_mm=expected_atlas_native_ap_mm,
                    overlay_path=overlay_path,
                    candidate=candidate,
                )
            )

        grid_path = review_grid_dir / f"section{section_index:03d}_candidate_grid.png"
        _write_candidate_grid(top_candidates, overlay_paths, grid_path)
        review_grid_paths.append(grid_path)

        if cfg.selection_strategy == "spacing_locked" and ordinal == 0:
            spacing_anchor_index = selected_index

        selected_reference_path = selected_reference_dir / f"section{section_index:03d}_atlas_reference.tif"
        selected_annotation_path = selected_annotation_dir / f"section{section_index:03d}_atlas_annotation.tif"
        selected_section_path = selected_sections_dir / f"section{section_index:03d}_section.tif"
        selected_overlay_path = selected_overlay_dir / f"section{section_index:03d}_selected_overlay.png"
        selected_atlas_preview_path = (
            selected_atlas_preview_dir
            / f"section{section_index:03d}_atlas_index{selected_index:04d}_ap{_ap_label_for_filename(selected['atlas_ap_mm'])}.png"
        )
        imwrite(selected_reference_path, selected["reference_slice"])
        imwrite(selected_annotation_path, selected["annotation_slice"])
        imwrite(selected_section_path, selected["section_image"])
        Image.fromarray(selected["overlay"], mode="RGB").save(selected_overlay_path)
        _write_atlas_preview_png(
            selected["reference_slice"],
            selected["annotation_slice"],
            selected_atlas_preview_path,
            title=_atlas_preview_title(
                section_index=section_index,
                atlas_slice_index=selected_index,
                atlas_ap_mm=float(selected["atlas_ap_mm"]),
                atlas_native_ap_mm=float(selected["atlas_native_ap_mm"]),
                ap_coordinate_system=cfg.ap_coordinate_system,
            ),
        )
        atlas_preview_paths.append(selected_atlas_preview_path)

        selected_rows.append(
            {
                **row,
                "atlas_name": cfg.atlas_name,
                "atlas_orientation": atlas_orientation,
                "atlas_axis_name": cfg.anatomical_axis,
                "atlas_axis_index": slice_axis,
                "ap_coordinate_system": cfg.ap_coordinate_system,
                "ap_coordinate_offset_mm": cfg.ap_coordinate_offset_mm,
                "atlas_slice_index": selected_index,
                "atlas_ap_mm": selected["atlas_ap_mm"],
                "atlas_native_ap_mm": selected["atlas_native_ap_mm"],
                "atlas_reference_path": str(selected_reference_path),
                "atlas_annotation_path": str(selected_annotation_path),
                "section_source_kind": cfg.section_source,
                "section_source_path": str(selected_section_path),
                "atlas_index_score": selected["score"],
                "atlas_index_candidate_rank": selected["score_rank"],
                "atlas_index_selection_strategy": cfg.selection_strategy,
                "atlas_index_expected_slice_index": expected_index,
                "atlas_index_expected_ap_mm": expected_ap_mm,
                "atlas_index_expected_native_ap_mm": expected_atlas_native_ap_mm,
                "atlas_index_review_grid_path": str(grid_path),
                "atlas_index_selected_overlay_path": str(selected_overlay_path),
                "atlas_index_selected_atlas_preview_path": str(selected_atlas_preview_path),
            }
        )
        selected_choice_rows.append(
            {
                "section_index": section_index,
                "selected_atlas_slice_index": selected_index,
                "selected_ap_mm": selected["atlas_ap_mm"],
                "selected_native_ap_mm": selected["atlas_native_ap_mm"],
                "expected_atlas_slice_index": expected_index,
                "expected_ap_mm": expected_ap_mm,
                "expected_native_ap_mm": expected_atlas_native_ap_mm,
                "score": selected["score"],
                "score_rank": selected["score_rank"],
                "boundary_distance_norm": selected["registration"].get("boundary_distance_norm", 1.0),
                "dorsal_midline_distance": selected["registration"].get("dorsal_midline_distance", 1.0),
                "dorsal_midline_y_offset": selected["registration"].get("dorsal_midline_y_offset", 0.0),
                "dorsal_midline_x_offset": selected["registration"].get("dorsal_midline_x_offset", 0.0),
                "selection_strategy": cfg.selection_strategy,
                "search_radius_slices": search_radius,
                "effective_min_ap_mm": _constraint_for_row(ordinal, cfg, effective_min_ap_mm),
                "effective_max_ap_mm": _constraint_for_row(ordinal, cfg, effective_max_ap_mm),
                "ap_coordinate_system": cfg.ap_coordinate_system,
                "ap_coordinate_offset_mm": cfg.ap_coordinate_offset_mm,
                "review_grid_path": str(grid_path),
                "selected_overlay_path": str(selected_overlay_path),
                "selected_atlas_preview_path": str(selected_atlas_preview_path),
            }
        )
        selected_section_indices.append(section_index)

    candidate_manifest_path = target_dir / cfg.candidate_manifest_name
    selected_manifest_path = target_dir / cfg.selected_manifest_name
    selected_choices_path = target_dir / cfg.selected_choices_name
    metadata_path = target_dir / cfg.metadata_name
    atlas_preview_contact_sheet_path = (
        target_dir / "selected" / "selected_atlas_contact_sheet.png" if atlas_preview_paths else None
    )
    if atlas_preview_contact_sheet_path is not None:
        _write_atlas_preview_contact_sheet(atlas_preview_paths, atlas_preview_contact_sheet_path)
    _write_manifest(candidate_manifest_path, candidate_rows)
    _write_manifest(selected_manifest_path, selected_rows)
    _write_manifest(selected_choices_path, selected_choice_rows)
    _write_json(
        metadata_path,
        {
            "input_manifest_path": str(manifest),
            "atlas_name": cfg.atlas_name,
            "atlas_orientation": atlas_orientation,
            "atlas_resolution_um": atlas_resolution,
            "atlas_shape": list(atlas_reference.shape),
            "slice_axis_index": slice_axis,
            "slice_axis_name": cfg.anatomical_axis,
            "ap_coordinate_system": cfg.ap_coordinate_system,
            "ap_coordinate_offset_mm": cfg.ap_coordinate_offset_mm,
            "selected_section_indices": selected_section_indices,
            "atlas_preview_paths": [str(path) for path in atlas_preview_paths],
            "atlas_preview_contact_sheet_path": str(atlas_preview_contact_sheet_path)
            if atlas_preview_contact_sheet_path is not None
            else None,
            "auto_ap_range": auto_ap_range_result,
            "config": _config_for_json(cfg),
        },
    )

    return AtlasIndexSuggestionResult(
        output_dir=target_dir,
        candidate_manifest_path=candidate_manifest_path,
        selected_manifest_path=selected_manifest_path,
        selected_choices_path=selected_choices_path,
        metadata_path=metadata_path,
        review_grid_paths=review_grid_paths,
        selected_section_indices=selected_section_indices,
        atlas_preview_paths=atlas_preview_paths,
        atlas_preview_contact_sheet_path=atlas_preview_contact_sheet_path,
    )


def export_selected_atlas_previews(
    selected_manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    contact_sheet_name: str = "selected_atlas_contact_sheet.png",
) -> AtlasPreviewExportResult:
    """Export atlas-only PNG previews from a selected slice-atlas manifest."""

    manifest = Path(selected_manifest_path)
    rows = _read_manifest_rows(manifest)
    if not rows:
        raise ValueError("The selected slice-atlas manifest is empty.")

    preview_dir = Path(output_dir) if output_dir is not None else manifest.parent / "selected" / "atlas_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_paths: list[Path] = []
    for row in rows:
        section_index = int(row["section_index"])
        atlas_slice_index = int(row["atlas_slice_index"])
        atlas_ap_mm = float(row["atlas_ap_mm"])
        atlas_native_ap_mm = float(row.get("atlas_native_ap_mm", atlas_ap_mm))
        preview_path = (
            preview_dir
            / f"section{section_index:03d}_atlas_index{atlas_slice_index:04d}_ap{_ap_label_for_filename(atlas_ap_mm)}.png"
        )
        reference = np.asarray(imread(row["atlas_reference_path"]))
        annotation = np.asarray(imread(row["atlas_annotation_path"]))
        _write_atlas_preview_png(
            reference,
            annotation,
            preview_path,
            title=_atlas_preview_title(
                section_index=section_index,
                atlas_slice_index=atlas_slice_index,
                atlas_ap_mm=atlas_ap_mm,
                atlas_native_ap_mm=atlas_native_ap_mm,
                ap_coordinate_system=row.get("ap_coordinate_system", "atlas"),
            ),
        )
        preview_paths.append(preview_path)

    contact_sheet_path = preview_dir.parent / contact_sheet_name if preview_paths else None
    if contact_sheet_path is not None:
        _write_atlas_preview_contact_sheet(preview_paths, contact_sheet_path)

    return AtlasPreviewExportResult(
        output_dir=preview_dir,
        preview_paths=preview_paths,
        contact_sheet_path=contact_sheet_path,
    )


def ap_mm_to_atlas_index(
    ap_mm: float,
    *,
    shape: tuple[int, ...] | list[int],
    resolution_um: tuple[float, ...] | list[float],
    orientation: str,
    axis_index: int = 0,
    coordinate_system: APCoordinateSystem = "atlas",
    ap_coordinate_offset_mm: float = 0.0,
) -> int:
    """Convert an approximate AP coordinate in mm to a BrainGlobe atlas index."""

    resolution = float(resolution_um[axis_index])
    center_um = float(shape[axis_index]) * resolution / 2.0
    axis_char = orientation[axis_index].lower()
    atlas_native_ap_mm = coordinate_ap_mm_to_atlas_native_ap_mm(
        ap_mm,
        coordinate_system=coordinate_system,
        ap_coordinate_offset_mm=ap_coordinate_offset_mm,
    )
    ap_um = float(atlas_native_ap_mm) * 1000.0
    if axis_char == "a":
        index = round((center_um - ap_um) / resolution)
    elif axis_char == "p":
        index = round((center_um + ap_um) / resolution)
    else:
        raise ValueError(f"Atlas axis {axis_index} is not AP-like for orientation {orientation!r}.")
    return int(np.clip(index, 0, int(shape[axis_index]) - 1))


def atlas_index_to_ap_mm(
    atlas_index: int,
    *,
    shape: tuple[int, ...] | list[int],
    resolution_um: tuple[float, ...] | list[float],
    orientation: str,
    axis_index: int = 0,
    coordinate_system: APCoordinateSystem = "atlas",
    ap_coordinate_offset_mm: float = 0.0,
) -> float:
    """Convert a BrainGlobe atlas index to an approximate AP coordinate in mm."""

    resolution = float(resolution_um[axis_index])
    center_um = float(shape[axis_index]) * resolution / 2.0
    axis_char = orientation[axis_index].lower()
    position_um = float(atlas_index) * resolution
    if axis_char == "a":
        atlas_native_ap_mm = (center_um - position_um) / 1000.0
    elif axis_char == "p":
        atlas_native_ap_mm = (position_um - center_um) / 1000.0
    else:
        raise ValueError(f"Atlas axis {axis_index} is not AP-like for orientation {orientation!r}.")
    return atlas_native_ap_mm_to_coordinate_ap_mm(
        atlas_native_ap_mm,
        coordinate_system=coordinate_system,
        ap_coordinate_offset_mm=ap_coordinate_offset_mm,
    )


def coordinate_ap_mm_to_atlas_native_ap_mm(
    ap_mm: float,
    *,
    coordinate_system: APCoordinateSystem = "atlas",
    ap_coordinate_offset_mm: float = 0.0,
) -> float:
    """Convert a configured user-facing AP coordinate to WHS/native atlas AP."""

    _validate_ap_coordinate_config(coordinate_system, ap_coordinate_offset_mm)
    if coordinate_system == "atlas":
        return float(ap_mm)
    if coordinate_system == "paxinos":
        return float(ap_mm) + float(ap_coordinate_offset_mm)
    raise ValueError(f"Unsupported AP coordinate system: {coordinate_system!r}.")


def atlas_native_ap_mm_to_coordinate_ap_mm(
    atlas_native_ap_mm: float,
    *,
    coordinate_system: APCoordinateSystem = "atlas",
    ap_coordinate_offset_mm: float = 0.0,
) -> float:
    """Convert WHS/native atlas AP to the configured user-facing AP coordinate."""

    _validate_ap_coordinate_config(coordinate_system, ap_coordinate_offset_mm)
    if coordinate_system == "atlas":
        return float(atlas_native_ap_mm)
    if coordinate_system == "paxinos":
        return float(atlas_native_ap_mm) - float(ap_coordinate_offset_mm)
    raise ValueError(f"Unsupported AP coordinate system: {coordinate_system!r}.")


def _validate_ap_coordinate_config(
    coordinate_system: str,
    ap_coordinate_offset_mm: float,
) -> None:
    if coordinate_system not in {"atlas", "paxinos"}:
        raise ValueError("ap_coordinate_system must be 'atlas' or 'paxinos'.")
    if coordinate_system == "atlas" and abs(float(ap_coordinate_offset_mm)) > 1e-12:
        raise ValueError("ap_coordinate_offset_mm can only be used with ap_coordinate_system='paxinos'.")


def _candidate_manifest_row(
    source_row: dict[str, str],
    *,
    review_rank: int,
    is_selected: bool,
    selection_strategy: SelectionStrategy,
    search_radius: int,
    expected_index: int,
    expected_ap_mm: float,
    expected_atlas_native_ap_mm: float,
    overlay_path: Path,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    registration = candidate["registration"]
    return {
        "section_index": int(source_row["section_index"]),
        "candidate_rank": review_rank,
        "score_rank": candidate.get("score_rank", review_rank),
        "is_selected": is_selected,
        "selection_strategy": selection_strategy,
        "search_radius_slices": search_radius,
        "expected_atlas_slice_index": expected_index,
        "expected_ap_mm": expected_ap_mm,
        "expected_native_ap_mm": expected_atlas_native_ap_mm,
        "ap_coordinate_system": candidate.get("ap_coordinate_system", "atlas"),
        "ap_coordinate_offset_mm": candidate.get("ap_coordinate_offset_mm", 0.0),
        "atlas_slice_index": int(candidate["atlas_slice_index"]),
        "atlas_ap_mm": candidate["atlas_ap_mm"],
        "atlas_native_ap_mm": candidate["atlas_native_ap_mm"],
        "score": candidate["score"],
        "base_score": candidate.get("base_score", candidate["score"]),
        "ap_prior_penalty": candidate.get("ap_prior_penalty", 0.0),
        "overlay_path": str(overlay_path),
        "registration_status": registration["status"],
        "registration_loss": registration["loss"],
        "registration_dice": registration["dice"],
        "registration_iou": registration["iou"],
        "registration_scale": registration["scale"],
        "registration_rotation_degrees": registration["rotation_degrees"],
        "registration_warped_area_ratio": registration["warped_area_ratio"],
        "registration_warped_extent_y_ratio": registration["warped_extent_y_ratio"],
        "registration_warped_extent_x_ratio": registration["warped_extent_x_ratio"],
        "registration_warped_center_y_offset": registration.get("warped_center_y_offset", 0.0),
        "registration_warped_center_x_offset": registration.get("warped_center_x_offset", 0.0),
        "registration_boundary_area_ratio": registration.get("boundary_area_ratio", 1.0),
        "registration_boundary_extent_y_ratio": registration.get("boundary_extent_y_ratio", 1.0),
        "registration_boundary_extent_x_ratio": registration.get("boundary_extent_x_ratio", 1.0),
        "registration_boundary_outside_fraction": registration.get("boundary_outside_fraction", 0.0),
        "registration_boundary_distance_norm": registration.get("boundary_distance_norm", 1.0),
        "registration_dorsal_midline_distance": registration.get("dorsal_midline_distance", 1.0),
        "registration_dorsal_midline_y_offset": registration.get("dorsal_midline_y_offset", 0.0),
        "registration_dorsal_midline_x_offset": registration.get("dorsal_midline_x_offset", 0.0),
        "registration_section_dorsal_midline_detected": registration.get("section_dorsal_midline_detected", False),
        "registration_atlas_dorsal_midline_detected": registration.get("atlas_dorsal_midline_detected", False),
    }


def _candidate_score(
    registration: dict[str, Any],
    *,
    boundary_distance_weight: float = 0.35,
    dorsal_midline_weight: float = 0.45,
) -> float:
    if registration.get("status") != "ok":
        return -1e6

    dice = float(registration.get("dice", 0.0))
    iou = float(registration.get("iou", 0.0))
    loss = float(registration.get("loss", 1.0))
    area_penalty = _log_ratio_penalty(float(registration.get("warped_area_ratio", 1.0)))
    extent_penalty = 0.5 * (
        _log_ratio_penalty(float(registration.get("warped_extent_y_ratio", 1.0)))
        + _log_ratio_penalty(float(registration.get("warped_extent_x_ratio", 1.0)))
    )
    center_penalty = abs(float(registration.get("warped_center_y_offset", 0.0))) + abs(
        float(registration.get("warped_center_x_offset", 0.0))
    )
    boundary_area_ratio = float(registration.get("boundary_area_ratio", 1.0))
    boundary_extent_y_ratio = float(registration.get("boundary_extent_y_ratio", 1.0))
    boundary_extent_x_ratio = float(registration.get("boundary_extent_x_ratio", 1.0))
    boundary_outside_fraction = float(registration.get("boundary_outside_fraction", 0.0))
    boundary_area_penalty = _log_ratio_penalty(boundary_area_ratio)
    boundary_extent_penalty = 0.5 * (
        _log_ratio_penalty(boundary_extent_y_ratio) + _log_ratio_penalty(boundary_extent_x_ratio)
    )
    boundary_distance_penalty = float(registration.get("boundary_distance_norm", 1.0))
    dorsal_midline_penalty = float(registration.get("dorsal_midline_distance", 1.0))
    boundary_excess_penalty = (
        max(0.0, boundary_area_ratio - 1.0)
        + max(0.0, boundary_extent_y_ratio - 1.0)
        + max(0.0, boundary_extent_x_ratio - 1.0)
    )
    return float(
        dice
        + 0.5 * iou
        - 0.15 * loss
        - 0.20 * area_penalty
        - 0.45 * extent_penalty
        - 0.40 * center_penalty
        - 0.25 * boundary_area_penalty
        - 0.45 * boundary_extent_penalty
        - 0.90 * boundary_outside_fraction
        - 0.45 * boundary_excess_penalty
        - max(0.0, float(boundary_distance_weight)) * boundary_distance_penalty
        - max(0.0, float(dorsal_midline_weight)) * dorsal_midline_penalty
    )


def _anatomical_alignment_metrics(registration: dict[str, Any], atlas_mask: np.ndarray) -> dict[str, Any]:
    section_mask = _registration_section_boundary_mask(registration)
    if section_mask is None:
        return _empty_anatomical_alignment_metrics()

    section = np.asarray(section_mask, dtype=bool)
    atlas = np.asarray(atlas_mask, dtype=bool)
    if not np.any(section) or not np.any(atlas):
        return _empty_anatomical_alignment_metrics()

    boundary_metrics = _boundary_distance_metrics(section, atlas)
    dorsal_metrics = _dorsal_midline_alignment_metrics(section, atlas)
    return {**boundary_metrics, **dorsal_metrics}


def _registration_section_boundary_mask(registration: dict[str, Any]) -> np.ndarray | None:
    for key in ("_warped_boundary_mask", "_warped_display_mask", "_warped_mask"):
        value = registration.get(key)
        if value is not None:
            return np.asarray(value, dtype=bool)
    return None


def _empty_anatomical_alignment_metrics() -> dict[str, Any]:
    return {
        "boundary_distance_pixels": float("inf"),
        "boundary_distance_norm": 1.0,
        "dorsal_midline_distance": 1.0,
        "dorsal_midline_y_offset": 0.0,
        "dorsal_midline_x_offset": 0.0,
        "section_dorsal_midline_y": None,
        "section_dorsal_midline_x": None,
        "atlas_dorsal_midline_y": None,
        "atlas_dorsal_midline_x": None,
        "section_dorsal_midline_detected": False,
        "atlas_dorsal_midline_detected": False,
    }


def _boundary_distance_metrics(section_mask: np.ndarray, atlas_mask: np.ndarray) -> dict[str, float]:
    section_boundary = _boundary_mask(section_mask)
    atlas_boundary = _boundary_mask(atlas_mask)
    if not np.any(section_boundary) or not np.any(atlas_boundary):
        return {
            "boundary_distance_pixels": float("inf"),
            "boundary_distance_norm": 1.0,
        }

    section_to_atlas = ndimage.distance_transform_edt(np.logical_not(atlas_boundary))
    atlas_to_section = ndimage.distance_transform_edt(np.logical_not(section_boundary))
    section_distance = float(np.mean(section_to_atlas[section_boundary]))
    atlas_distance = float(np.mean(atlas_to_section[atlas_boundary]))
    distance_pixels = 0.5 * (section_distance + atlas_distance)
    atlas_bbox = _bbox(atlas_mask)
    if atlas_bbox is None:
        normalizer = float(max(atlas_mask.shape))
    else:
        atlas_height = max(1.0, float(atlas_bbox[1] - atlas_bbox[0]))
        atlas_width = max(1.0, float(atlas_bbox[3] - atlas_bbox[2]))
        normalizer = float(np.hypot(atlas_height, atlas_width))
    return {
        "boundary_distance_pixels": distance_pixels,
        "boundary_distance_norm": min(1.0, distance_pixels / max(1.0, normalizer)),
    }


def _dorsal_midline_alignment_metrics(section_mask: np.ndarray, atlas_mask: np.ndarray) -> dict[str, Any]:
    section_anchor = _dorsal_midline_anchor(section_mask)
    atlas_anchor = _dorsal_midline_anchor(atlas_mask)
    if section_anchor is None or atlas_anchor is None:
        return {
            "dorsal_midline_distance": 1.0,
            "dorsal_midline_y_offset": 0.0,
            "dorsal_midline_x_offset": 0.0,
            "section_dorsal_midline_y": None,
            "section_dorsal_midline_x": None,
            "atlas_dorsal_midline_y": None,
            "atlas_dorsal_midline_x": None,
            "section_dorsal_midline_detected": False,
            "atlas_dorsal_midline_detected": False,
        }

    atlas_bbox = _bbox(atlas_mask)
    if atlas_bbox is None:
        atlas_height = max(1.0, float(atlas_mask.shape[0]))
        atlas_width = max(1.0, float(atlas_mask.shape[1]))
    else:
        atlas_height = max(1.0, float(atlas_bbox[1] - atlas_bbox[0]))
        atlas_width = max(1.0, float(atlas_bbox[3] - atlas_bbox[2]))
    y_offset = (float(section_anchor["y"]) - float(atlas_anchor["y"])) / atlas_height
    x_offset = (float(section_anchor["x"]) - float(atlas_anchor["x"])) / atlas_width
    return {
        "dorsal_midline_distance": float(np.hypot(y_offset, x_offset)),
        "dorsal_midline_y_offset": float(y_offset),
        "dorsal_midline_x_offset": float(x_offset),
        "section_dorsal_midline_y": float(section_anchor["y"]),
        "section_dorsal_midline_x": float(section_anchor["x"]),
        "atlas_dorsal_midline_y": float(atlas_anchor["y"]),
        "atlas_dorsal_midline_x": float(atlas_anchor["x"]),
        "section_dorsal_midline_detected": bool(section_anchor["detected"]),
        "atlas_dorsal_midline_detected": bool(atlas_anchor["detected"]),
    }


def _dorsal_midline_anchor(mask: np.ndarray) -> dict[str, Any] | None:
    binary = np.asarray(mask, dtype=bool)
    bbox = _bbox(binary)
    if bbox is None:
        return None

    y0, y1, x0, x1 = bbox
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    column_x: list[int] = []
    top_y: list[float] = []
    for x in range(x0, x1):
        ys = np.flatnonzero(binary[y0:y1, x])
        if ys.size:
            column_x.append(x)
            top_y.append(float(y0 + ys[0]))
    if not column_x:
        return None

    xs = np.asarray(column_x, dtype=np.int32)
    tops = np.asarray(top_y, dtype=np.float32)
    smooth_size = max(3, min(15, int(round(width * 0.05)) | 1))
    smoothed = ndimage.median_filter(tops, size=smooth_size, mode="nearest")

    center_x = 0.5 * float(x0 + x1 - 1)
    central_half_width = max(2.0, 0.20 * float(width))
    central = np.abs(xs.astype(np.float32) - center_x) <= central_half_width
    if not np.any(central):
        central = np.ones_like(xs, dtype=bool)

    central_indices = np.flatnonzero(central)
    local_values = smoothed[central_indices]
    max_value = float(local_values.max())
    tied = central_indices[np.flatnonzero(local_values == max_value)]
    if tied.size > 1:
        chosen = int(tied[np.argmin(np.abs(xs[tied].astype(np.float32) - center_x))])
    else:
        chosen = int(tied[0])

    reference_surface = float(np.quantile(smoothed[central], 0.25))
    depth = max(0.0, float(smoothed[chosen]) - reference_surface)
    depth_ratio = depth / max(1.0, float(height))
    detected = bool(depth_ratio >= 0.015)
    if not detected:
        central_top = float(smoothed[central].min())
        nearest_top = central_indices[np.argmin(np.abs(local_values - central_top))]
        chosen = int(nearest_top)

    return {
        "y": float(tops[chosen]),
        "x": float(xs[chosen]),
        "depth_ratio": float(depth_ratio),
        "detected": detected,
    }


def _constraint_for_row(ordinal: int, cfg: AtlasIndexSuggestionConfig, value: float | None) -> float | None:
    if not _constraints_apply_to_row(ordinal, cfg):
        return None
    return value


def _constraints_apply_to_row(ordinal: int, cfg: AtlasIndexSuggestionConfig) -> bool:
    return ordinal == 0 or cfg.selection_strategy != "spacing_locked"


def _estimate_auto_ap_range(
    section_image: np.ndarray,
    *,
    atlas_annotation: np.ndarray,
    atlas_resolution: list[Any],
    atlas_orientation: str,
    slice_axis: int,
    cfg: AtlasIndexSuggestionConfig,
) -> dict[str, Any]:
    section_mask = _tissue_mask(
        section_image,
        quantile=cfg.auto_ap_range_tissue_quantile,
    )
    section_profile = _normalized_mask_profile(section_mask, output_size=cfg.auto_ap_range_shape_size)
    axis_length = int(atlas_annotation.shape[slice_axis])
    stride = max(1, int(cfg.auto_ap_range_stride_slices))
    scores: list[dict[str, Any]] = []

    for atlas_slice_index in range(0, axis_length, stride):
        atlas_mask = np.asarray(_extract_slice(atlas_annotation, slice_axis, atlas_slice_index)) > 0
        if not np.any(atlas_mask):
            continue
        atlas_profile = _normalized_mask_profile(atlas_mask, output_size=cfg.auto_ap_range_shape_size)
        score = _mask_profile_similarity(section_profile, atlas_profile)
        ap_mm = atlas_index_to_ap_mm(
            atlas_slice_index,
            shape=atlas_annotation.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
            coordinate_system=cfg.ap_coordinate_system,
            ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
        )
        atlas_native_ap_mm = atlas_index_to_ap_mm(
            atlas_slice_index,
            shape=atlas_annotation.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
        )
        scores.append(
            {
                "atlas_slice_index": int(atlas_slice_index),
                "atlas_ap_mm": float(ap_mm),
                "atlas_native_ap_mm": float(atlas_native_ap_mm),
                "shape_score": float(score),
            }
        )

    if not scores:
        raise ValueError("Automatic AP range estimation could not find non-empty atlas planes.")

    scores.sort(key=lambda row: row["shape_score"], reverse=True)
    top = scores[: max(1, int(cfg.auto_ap_range_top_n))]
    padding = max(0.0, float(cfg.auto_ap_range_padding_mm))
    min_top_ap = min(float(row["atlas_ap_mm"]) for row in top)
    max_top_ap = max(float(row["atlas_ap_mm"]) for row in top)
    atlas_ap_values = [
        atlas_index_to_ap_mm(
            index,
            shape=atlas_annotation.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
            coordinate_system=cfg.ap_coordinate_system,
            ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
        )
        for index in (0, axis_length - 1)
    ]
    atlas_min_ap = min(atlas_ap_values)
    atlas_max_ap = max(atlas_ap_values)
    min_ap = max(atlas_min_ap, min_top_ap - padding)
    max_ap = min(atlas_max_ap, max_top_ap + padding)
    if min_ap > max_ap:
        min_ap, max_ap = max_ap, min_ap

    return {
        "mode": "shape_profile",
        "min_ap_mm": float(min_ap),
        "max_ap_mm": float(max_ap),
        "best_ap_mm": float(top[0]["atlas_ap_mm"]),
        "best_native_ap_mm": float(top[0]["atlas_native_ap_mm"]),
        "best_atlas_slice_index": int(top[0]["atlas_slice_index"]),
        "best_shape_score": float(top[0]["shape_score"]),
        "stride_slices": stride,
        "top_n": max(1, int(cfg.auto_ap_range_top_n)),
        "padding_mm": padding,
        "top_candidates": top,
    }


def _normalized_mask_profile(mask: np.ndarray, *, output_size: int) -> dict[str, Any]:
    binary = np.asarray(mask, dtype=bool)
    bbox = _bbox(binary)
    size = max(16, int(output_size))
    canvas = np.zeros((size, size), dtype=np.float32)
    if bbox is None:
        return {
            "mask": canvas,
            "y_profile": np.zeros(size, dtype=np.float32),
            "x_profile": np.zeros(size, dtype=np.float32),
            "aspect": 1.0,
        }

    crop = binary[bbox[0] : bbox[1], bbox[2] : bbox[3]].astype(np.float32)
    crop_height, crop_width = crop.shape
    scale = min(size / max(1, crop_height), size / max(1, crop_width))
    resized_shape = (
        max(1, min(size, int(round(crop_height * scale)))),
        max(1, min(size, int(round(crop_width * scale)))),
    )
    resized = _resize_image(crop, resized_shape, order=1, fill_value=0.0)
    y0 = (size - resized_shape[0]) // 2
    x0 = (size - resized_shape[1]) // 2
    canvas[y0 : y0 + resized_shape[0], x0 : x0 + resized_shape[1]] = resized
    canvas = (canvas >= 0.5).astype(np.float32)
    y_profile = _normalized_projection(canvas.sum(axis=1))
    x_profile = _normalized_projection(canvas.sum(axis=0))
    return {
        "mask": canvas,
        "y_profile": y_profile,
        "x_profile": x_profile,
        "aspect": float(crop_width / max(1, crop_height)),
    }


def _normalized_projection(values: np.ndarray) -> np.ndarray:
    projection = np.asarray(values, dtype=np.float32)
    total = float(projection.sum())
    if total <= 0:
        return np.zeros_like(projection)
    return projection / total


def _mask_profile_similarity(first: dict[str, Any], second: dict[str, Any]) -> float:
    first_mask = np.asarray(first["mask"], dtype=bool)
    second_mask = np.asarray(second["mask"], dtype=bool)
    intersection = float(np.logical_and(first_mask, second_mask).sum())
    union = float(np.logical_or(first_mask, second_mask).sum())
    dice = (2.0 * intersection) / max(1.0, float(first_mask.sum() + second_mask.sum()))
    iou = intersection / max(1.0, union)
    y_similarity = 1.0 - 0.5 * float(np.abs(first["y_profile"] - second["y_profile"]).sum())
    x_similarity = 1.0 - 0.5 * float(np.abs(first["x_profile"] - second["x_profile"]).sum())
    aspect_penalty = _log_ratio_penalty(float(first["aspect"]) / max(1e-6, float(second["aspect"])))
    return float(0.35 * dice + 0.25 * iou + 0.20 * y_similarity + 0.20 * x_similarity - 0.15 * aspect_penalty)


def _rank_candidates_for_row(
    ordinal: int,
    cfg: AtlasIndexSuggestionConfig,
    *,
    expected_index: int,
    search_radius: int,
    axis_length: int,
    atlas_reference: np.ndarray,
    atlas_annotation: np.ndarray,
    atlas_resolution: list[Any],
    atlas_orientation: str,
    slice_axis: int,
    section_image: np.ndarray,
    prepared_section: Any,
    min_ap_mm: float | None,
    max_ap_mm: float | None,
    ap_prior_mm: float | None,
    ap_prior_weight: float,
) -> list[dict[str, Any]]:
    if ordinal == 0 and int(cfg.anchor_search_stride_slices) > 1:
        coarse_indices = _candidate_indices(
            expected_index,
            radius=search_radius,
            axis_length=axis_length,
            step=int(cfg.anchor_search_stride_slices),
        )
        coarse_indices = _filter_indices_by_ap(
            coarse_indices,
            shape=atlas_reference.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
            min_ap_mm=min_ap_mm,
            max_ap_mm=max_ap_mm,
            coordinate_system=cfg.ap_coordinate_system,
            ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
        )
        coarse_ranked = _rank_candidate_indices(
            coarse_indices,
            atlas_reference=atlas_reference,
            atlas_annotation=atlas_annotation,
            atlas_resolution=atlas_resolution,
            atlas_orientation=atlas_orientation,
            slice_axis=slice_axis,
            section_image=section_image,
            prepared_section=prepared_section,
            registration_config=cfg.registration_config,
            boundary_distance_weight=cfg.boundary_distance_weight,
            dorsal_midline_weight=cfg.dorsal_midline_weight,
            ap_prior_mm=ap_prior_mm,
            ap_prior_weight=ap_prior_weight,
            coordinate_system=cfg.ap_coordinate_system,
            ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
        )
        if not coarse_ranked:
            return []
        coarse_ranked.sort(key=lambda item: item["score"], reverse=True)
        refine_radius = (
            max(0, int(cfg.anchor_refine_radius_slices))
            if cfg.anchor_refine_radius_slices is not None
            else max(int(cfg.search_radius_slices), int(cfg.anchor_search_stride_slices))
        )
        refine_center = int(coarse_ranked[0]["atlas_slice_index"])
        refine_indices = _candidate_indices(refine_center, radius=refine_radius, axis_length=axis_length)
        all_indices = sorted({*coarse_indices, *refine_indices})
    else:
        all_indices = _candidate_indices(
            expected_index,
            radius=search_radius,
            axis_length=axis_length,
        )
    all_indices = _filter_indices_by_ap(
        all_indices,
        shape=atlas_reference.shape,
        resolution_um=atlas_resolution,
        orientation=atlas_orientation,
        axis_index=slice_axis,
        min_ap_mm=min_ap_mm,
        max_ap_mm=max_ap_mm,
        coordinate_system=cfg.ap_coordinate_system,
        ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
    )

    return _rank_candidate_indices(
        all_indices,
        atlas_reference=atlas_reference,
        atlas_annotation=atlas_annotation,
        atlas_resolution=atlas_resolution,
        atlas_orientation=atlas_orientation,
        slice_axis=slice_axis,
        section_image=section_image,
        prepared_section=prepared_section,
        registration_config=cfg.registration_config,
        boundary_distance_weight=cfg.boundary_distance_weight,
        dorsal_midline_weight=cfg.dorsal_midline_weight,
        ap_prior_mm=ap_prior_mm,
        ap_prior_weight=ap_prior_weight,
        coordinate_system=cfg.ap_coordinate_system,
        ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
    )


def _rank_candidate_indices(
    candidate_indices: list[int],
    *,
    atlas_reference: np.ndarray,
    atlas_annotation: np.ndarray,
    atlas_resolution: list[Any],
    atlas_orientation: str,
    slice_axis: int,
    section_image: np.ndarray,
    prepared_section: Any,
    registration_config: SliceRegistrationConfig,
    boundary_distance_weight: float,
    dorsal_midline_weight: float,
    ap_prior_mm: float | None,
    ap_prior_weight: float,
    coordinate_system: APCoordinateSystem,
    ap_coordinate_offset_mm: float,
) -> list[dict[str, Any]]:
    ranked = []
    for atlas_slice_index in candidate_indices:
        reference_slice = _extract_slice(atlas_reference, slice_axis, atlas_slice_index)
        annotation_slice = _extract_slice(atlas_annotation, slice_axis, atlas_slice_index)
        atlas_mask = np.asarray(annotation_slice) > 0
        warped_section, registration = _register_prepared_section_to_atlas(
            prepared_section=prepared_section,
            atlas_reference=reference_slice,
            atlas_mask=atlas_mask,
            config=registration_config,
        )
        registration.update(_anatomical_alignment_metrics(registration, atlas_mask))
        overlay = _compose_overlay(
            warped_section,
            reference_slice,
            atlas_mask,
            registration_config,
            section_mask=registration.get("_warped_display_mask"),
        )
        atlas_ap_mm = atlas_index_to_ap_mm(
            atlas_slice_index,
            shape=atlas_reference.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
            coordinate_system=coordinate_system,
            ap_coordinate_offset_mm=ap_coordinate_offset_mm,
        )
        atlas_native_ap_mm = atlas_index_to_ap_mm(
            atlas_slice_index,
            shape=atlas_reference.shape,
            resolution_um=atlas_resolution,
            orientation=atlas_orientation,
            axis_index=slice_axis,
        )
        base_score = _candidate_score(
            registration,
            boundary_distance_weight=boundary_distance_weight,
            dorsal_midline_weight=dorsal_midline_weight,
        )
        ap_prior_penalty = _ap_prior_penalty(
            atlas_ap_mm,
            ap_prior_mm=ap_prior_mm,
            ap_prior_weight=ap_prior_weight,
        )
        score = base_score - ap_prior_penalty
        ranked.append(
            {
                "atlas_slice_index": atlas_slice_index,
                "atlas_ap_mm": atlas_ap_mm,
                "atlas_native_ap_mm": atlas_native_ap_mm,
                "ap_coordinate_system": coordinate_system,
                "ap_coordinate_offset_mm": ap_coordinate_offset_mm,
                "score": score,
                "base_score": base_score,
                "ap_prior_penalty": ap_prior_penalty,
                "registration": registration,
                "reference_slice": reference_slice,
                "annotation_slice": annotation_slice,
                "section_image": section_image,
                "overlay": overlay,
                "warped_section": warped_section,
            }
        )
    return ranked


def _filter_indices_by_ap(
    indices: list[int],
    *,
    shape: tuple[int, ...],
    resolution_um: list[Any],
    orientation: str,
    axis_index: int,
    min_ap_mm: float | None,
    max_ap_mm: float | None,
    coordinate_system: APCoordinateSystem,
    ap_coordinate_offset_mm: float,
) -> list[int]:
    if min_ap_mm is None and max_ap_mm is None:
        return indices

    lower = -math.inf if min_ap_mm is None else float(min_ap_mm)
    upper = math.inf if max_ap_mm is None else float(max_ap_mm)
    if lower > upper:
        lower, upper = upper, lower

    filtered = []
    for index in indices:
        ap_mm = atlas_index_to_ap_mm(
            index,
            shape=shape,
            resolution_um=resolution_um,
            orientation=orientation,
            axis_index=axis_index,
            coordinate_system=coordinate_system,
            ap_coordinate_offset_mm=ap_coordinate_offset_mm,
        )
        if lower <= ap_mm <= upper:
            filtered.append(index)
    return filtered


def _ap_prior_penalty(
    atlas_ap_mm: float,
    *,
    ap_prior_mm: float | None,
    ap_prior_weight: float,
) -> float:
    if ap_prior_mm is None or ap_prior_weight <= 0:
        return 0.0
    return float(ap_prior_weight) * abs(float(atlas_ap_mm) - float(ap_prior_mm))


def _search_radius_for_row(ordinal: int, cfg: AtlasIndexSuggestionConfig) -> int:
    if ordinal == 0 and cfg.anchor_search_radius_slices is not None:
        return max(0, int(cfg.anchor_search_radius_slices))
    return max(0, int(cfg.search_radius_slices))


def _log_ratio_penalty(value: float) -> float:
    if value <= 0 or not math.isfinite(value):
        return 10.0
    return abs(float(math.log(value)))


def _write_candidate_grid(candidates: list[dict[str, Any]], overlay_paths: list[Path], path: Path) -> None:
    images = [Image.open(overlay_path).convert("RGB") for overlay_path in overlay_paths]
    if not images:
        return

    label_height = 58
    width = sum(image.width for image in images)
    height = max(image.height for image in images) + label_height
    grid = Image.new("RGB", (width, height), color=(18, 18, 18))
    draw = ImageDraw.Draw(grid)

    x = 0
    for rank, (candidate, image) in enumerate(zip(candidates, images), start=1):
        selected_label = "SELECTED  " if candidate.get("is_selected_candidate") else ""
        score_rank = int(candidate.get("score_rank", rank))
        score_rank_label = "" if score_rank == rank else f"  score rank {score_rank}"
        ap_label = "Paxinos AP" if candidate.get("ap_coordinate_system") == "paxinos" else "AP"
        label = (
            f"{selected_label}rank {rank}{score_rank_label}  index {int(candidate['atlas_slice_index'])}  "
            f"{ap_label} {float(candidate['atlas_ap_mm']):.3f} mm\n"
            f"score {float(candidate['score']):.3f}  "
            f"dice {float(candidate['registration']['dice']):.3f}  "
            f"iou {float(candidate['registration']['iou']):.3f}"
        )
        draw.text((x + 8, 8), label, fill=(235, 235, 235))
        grid.paste(image, (x, label_height))
        if candidate.get("is_selected_candidate"):
            draw.rectangle(
                (x + 2, label_height + 2, x + image.width - 3, label_height + image.height - 3),
                outline=(255, 221, 87),
                width=6,
            )
        x += image.width

    path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(path)


def _write_atlas_preview_png(
    reference_slice: np.ndarray,
    annotation_slice: np.ndarray,
    path: Path,
    *,
    title: str,
    max_size: int = 720,
) -> None:
    preview = _atlas_preview_rgb(reference_slice, annotation_slice)
    image = Image.fromarray(preview, mode="RGB")
    image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    label_height = 42
    canvas = Image.new("RGB", (image.width, image.height + label_height), color=(18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 10), title, fill=(240, 240, 240))
    canvas.paste(image, (0, label_height))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def _atlas_preview_rgb(reference_slice: np.ndarray, annotation_slice: np.ndarray) -> np.ndarray:
    gray = _preview_uint8(reference_slice)
    rgb = np.stack([gray, gray, gray], axis=-1)
    boundary = _boundary_mask(np.asarray(annotation_slice) > 0)
    rgb[boundary, 0] = 0
    rgb[boundary, 1] = 255
    rgb[boundary, 2] = 0
    return rgb.astype(np.uint8)


def _preview_uint8(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image, dtype=np.float32)
    if not np.isfinite(array).any():
        return np.zeros(array.shape, dtype=np.uint8)
    array = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)
    finite = array[np.isfinite(array)]
    low, high = np.percentile(finite, (1, 99))
    if high <= low:
        if float(array.max()) > float(array.min()):
            low = float(array.min())
            high = float(array.max())
        else:
            return np.zeros(array.shape, dtype=np.uint8)
    scaled = np.clip((array - low) / (high - low), 0.0, 1.0) * 255.0
    return scaled.astype(np.uint8)


def _write_atlas_preview_contact_sheet(preview_paths: list[Path], path: Path, *, tile_width: int = 320, tile_height: int = 320) -> None:
    if not preview_paths:
        return
    tiles = []
    for preview_path in preview_paths:
        image = Image.open(preview_path).convert("RGB")
        tile = Image.new("RGB", (tile_width, tile_height), color=(22, 22, 22))
        fitted = ImageOps.contain(image, (tile_width, tile_height), Image.Resampling.LANCZOS)
        tile.paste(fitted, ((tile_width - fitted.width) // 2, (tile_height - fitted.height) // 2))
        tiles.append(tile)

    cols = min(3, len(tiles))
    rows = int(math.ceil(len(tiles) / cols))
    sheet = Image.new("RGB", (tile_width * cols, tile_height * rows), color=(18, 18, 18))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % cols) * tile_width, (index // cols) * tile_height))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def _atlas_preview_title(
    *,
    section_index: int,
    atlas_slice_index: int,
    atlas_ap_mm: float,
    atlas_native_ap_mm: float,
    ap_coordinate_system: str,
) -> str:
    ap_label = "Paxinos AP" if ap_coordinate_system == "paxinos" else "AP"
    if ap_coordinate_system == "paxinos" and abs(float(atlas_ap_mm) - float(atlas_native_ap_mm)) > 1e-9:
        return (
            f"section {section_index:03d} -> atlas index {atlas_slice_index:04d}  "
            f"{ap_label} {atlas_ap_mm:+.3f} mm  native AP {atlas_native_ap_mm:+.3f} mm"
        )
    return f"section {section_index:03d} -> atlas index {atlas_slice_index:04d}  {ap_label} {atlas_ap_mm:+.3f} mm"


def _ap_label_for_filename(ap_mm: float) -> str:
    prefix = "p" if float(ap_mm) >= 0 else "m"
    return prefix + f"{abs(float(ap_mm)):.3f}".replace(".", "p")


def _expected_index_for_row(
    ordinal: int,
    cfg: AtlasIndexSuggestionConfig,
    *,
    axis_length: int,
    resolution_um: float,
    orientation: str,
    axis_index: int,
) -> int:
    if cfg.start_ap_mm is not None:
        interval_mm = 0.0 if cfg.section_interval_um is None else cfg.section_interval_um / 1000.0
        direction_sign = -1.0 if cfg.direction == "posterior" else 1.0
        ap_mm = cfg.start_ap_mm + direction_sign * ordinal * interval_mm
        return ap_mm_to_atlas_index(
            ap_mm,
            shape=[axis_length],
            resolution_um=[resolution_um],
            orientation=orientation[axis_index],
            axis_index=0,
            coordinate_system=cfg.ap_coordinate_system,
            ap_coordinate_offset_mm=cfg.ap_coordinate_offset_mm,
        )

    if cfg.start_slice_index is None:
        raise ValueError("Provide either start_ap_mm or start_slice_index for atlas-index suggestion.")

    if cfg.section_interval_um is not None:
        step = int(round(cfg.section_interval_um / resolution_um))
        axis_char = orientation[axis_index].lower()
        if cfg.direction == "posterior":
            signed_step = step if axis_char == "a" else -step
        else:
            signed_step = -step if axis_char == "a" else step
    else:
        signed_step = cfg.slice_index_step

    return int(np.clip(cfg.start_slice_index + ordinal * signed_step, 0, axis_length - 1))


def _spacing_step_indices(
    cfg: AtlasIndexSuggestionConfig,
    *,
    resolution_um: float,
    orientation: str,
    axis_index: int,
) -> int:
    if cfg.section_interval_um is None:
        return int(cfg.slice_index_step)

    step = int(round(float(cfg.section_interval_um) / resolution_um))
    axis_char = orientation[axis_index].lower()
    if cfg.direction == "posterior":
        return step if axis_char == "a" else -step
    return -step if axis_char == "a" else step


def _candidate_indices(expected_index: int, *, radius: int, axis_length: int, step: int = 1) -> list[int]:
    start = max(0, expected_index - max(0, int(radius)))
    stop = min(axis_length - 1, expected_index + max(0, int(radius)))
    return list(range(start, stop + 1, max(1, int(step))))


def _select_candidate(ranked: list[dict[str, Any]], forced_index: int | None) -> dict[str, Any]:
    if forced_index is None:
        return ranked[0]
    for candidate in ranked:
        if int(candidate["atlas_slice_index"]) == int(forced_index):
            return candidate
    raise ValueError(f"Forced atlas index {forced_index} was not evaluated.")


def _review_candidates(
    ranked: list[dict[str, Any]],
    *,
    top_n: int,
    forced_index: int | None,
) -> list[dict[str, Any]]:
    limit = max(1, int(top_n))
    review = list(ranked[:limit])
    if forced_index is None or any(int(candidate["atlas_slice_index"]) == int(forced_index) for candidate in review):
        return review

    forced = _select_candidate(ranked, forced_index)
    if len(review) >= limit:
        review = review[: limit - 1]
    review.append(forced)
    return sorted(review, key=lambda candidate: int(candidate.get("score_rank", 0)))


def _selected_rows(rows: list[dict[str, str]], cfg: AtlasIndexSuggestionConfig) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for row in rows:
        if cfg.sample_id and row.get("sample_id") != cfg.sample_id:
            continue
        if cfg.require_include_in_stack and not _parse_bool(row.get("include_in_stack", "true")):
            continue
        filtered.append(row)
    return sorted(filtered, key=lambda row: int(row["section_index"]))


def _section_source_path(row: dict[str, str], cfg: AtlasIndexSuggestionConfig) -> Path:
    if cfg.section_source == "registration":
        return Path(row["crop_path_registration"])
    if cfg.section_source == "rgb":
        return Path(row["crop_path_rgb"])
    if cfg.section_source == "channel":
        if cfg.channel is None:
            raise ValueError("AtlasIndexSuggestionConfig.channel is required when section_source='channel'.")
        channel_paths = json.loads(row["channel_paths"])
        key = f"ch{cfg.channel}"
        if key not in channel_paths:
            raise ValueError(f"Manifest row does not contain a path for {key}.")
        return Path(channel_paths[key])
    raise ValueError("section_source must be one of: 'registration', 'rgb', 'channel'.")


def _load_atlas(atlas_name: str):
    try:
        from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas
    except ImportError as exc:
        raise ImportError("brainglobe-atlasapi is required for atlas-index suggestion.") from exc
    return BrainGlobeAtlas(atlas_name)


def _axis_index_from_orientation(orientation: str, axis_name: AxisName) -> int:
    mapping = {
        "ap": {"a", "p"},
        "si": {"s", "i"},
        "dv": {"d", "v", "s", "i"},
        "rl": {"r", "l"},
        "ml": {"m", "l", "r"},
    }
    allowed = mapping[axis_name]
    for index, char in enumerate(orientation):
        if char.lower() in allowed:
            return index
    raise ValueError(f"Could not find anatomical axis {axis_name!r} in atlas orientation {orientation!r}.")


def _extract_slice(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    return np.take(volume, index, axis=axis)


def _config_for_json(cfg: AtlasIndexSuggestionConfig) -> dict[str, Any]:
    data = asdict(cfg)
    data["registration_config"] = asdict(cfg.registration_config)
    return data


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("section_index\n")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
