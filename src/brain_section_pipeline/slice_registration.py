"""Register slice-wise histology sections to paired atlas planes."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image
from scipy import ndimage
from tifffile import imread, imwrite

ScaleInitialization = Literal["bbox_fit", "area"]
TranslationInitialization = Literal["crop_center", "tissue_centroid"]
TransformModel = Literal["similarity", "affine"]
NonlinearRefinementModel = Literal["none", "boundary_spline"]


@dataclass(frozen=True)
class SliceRegistrationConfig:
    """Configuration for per-section 2D slice-to-atlas registration."""

    tissue_threshold_quantile: float = 0.8
    fill_value: float = 0.0
    overlay_alpha: float = 0.55
    boundary_color: tuple[int, int, int] = (0, 255, 0)
    section_color: tuple[int, int, int] = (255, 96, 96)
    atlas_color: tuple[int, int, int] = (180, 180, 180)
    max_rotation_degrees: float = 0.0
    min_scale_factor: float = 0.8
    max_scale_factor: float = 1.0
    translation_search_fraction: float = 0.25
    transform_model: TransformModel = "similarity"
    initial_rotation_degrees: float | None = 0.0
    scale_initialization: ScaleInitialization = "bbox_fit"
    translation_initialization: TranslationInitialization = "tissue_centroid"
    max_affine_anisotropy: float = 0.10
    max_affine_shear: float = 0.04
    affine_regularization_weight: float = 0.08
    area_loss_weight: float = 0.2
    extent_loss_weight: float = 0.8
    center_loss_weight: float = 0.4
    mask_overlay_to_tissue: bool = True
    overlay_mask_threshold_quantile: float = 0.45
    overlay_mask_dilation_px: int = 6
    boundary_fit_threshold_quantile: float = 0.35
    boundary_fit_dilation_px: int = 0
    boundary_fit_weight: float = 0.35
    boundary_containment_weight: float = 1.2
    nonlinear_refinement_model: NonlinearRefinementModel = "none"
    nonlinear_max_displacement_px: float = 8.0
    nonlinear_control_point_spacing_px: float = 48.0
    nonlinear_iterations: int = 2
    nonlinear_boundary_sample_step: int = 3
    output_name: str = "slice_registration_manifest.csv"
    metadata_name: str = "slice_registration_metadata.json"


@dataclass(frozen=True)
class SliceRegistrationResult:
    """Artifacts produced during per-section slice registration."""

    output_dir: Path
    manifest_path: Path
    metadata_path: Path
    warped_sections_dir: Path
    overlay_dir: Path
    section_indices: list[int]


@dataclass(frozen=True)
class _PreparedSectionRegistrationInput:
    section_crop: np.ndarray
    section_mask_crop: np.ndarray
    section_display_mask_crop: np.ndarray
    section_boundary_mask_crop: np.ndarray


def register_slices_to_atlas(
    pairing_manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    config: SliceRegistrationConfig | None = None,
) -> SliceRegistrationResult:
    """Estimate a 2D transform for each section against its paired atlas plane."""

    cfg = config or SliceRegistrationConfig()
    manifest = Path(pairing_manifest_path)
    rows = _read_manifest_rows(manifest)
    if not rows:
        raise ValueError("The slice-wise atlas manifest is empty.")

    registration_dir = Path(output_dir) if output_dir is not None else manifest.parent / "slice_registration"
    warped_sections_dir = registration_dir / "warped_sections"
    overlay_dir = registration_dir / "overlays"
    affine_overlay_dir = registration_dir / "affine_overlays"
    warped_sections_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    if cfg.nonlinear_refinement_model != "none":
        affine_overlay_dir.mkdir(parents=True, exist_ok=True)

    output_rows: list[dict[str, Any]] = []
    section_indices: list[int] = []

    for row in rows:
        section_index = int(row["section_index"])
        section_image = _grayscale_image(Path(row["section_source_path"]))
        atlas_reference = _grayscale_image(Path(row["atlas_reference_path"]))
        atlas_annotation = np.asarray(imread(row["atlas_annotation_path"]))
        atlas_mask = np.asarray(atlas_annotation) > 0

        warped_section, registration = _register_section_to_atlas(
            section_image=section_image,
            atlas_reference=atlas_reference,
            atlas_mask=atlas_mask,
            config=cfg,
        )
        registration.pop("_warped_mask", None)
        warped_display_mask = registration.pop("_warped_display_mask", None)
        affine_warped_section = registration.pop("_affine_warped_section", None)
        affine_warped_display_mask = registration.pop("_affine_warped_display_mask", None)
        overlay = _compose_overlay(warped_section, atlas_reference, atlas_mask, cfg, section_mask=warped_display_mask)

        warped_path = warped_sections_dir / f"section{section_index:03d}_warped.tif"
        overlay_path = overlay_dir / f"section{section_index:03d}_overlay.png"
        imwrite(warped_path, warped_section.astype(np.float32))
        Image.fromarray(overlay, mode="RGB").save(overlay_path)
        affine_overlay_path = ""
        if affine_warped_section is not None:
            affine_overlay = _compose_overlay(
                affine_warped_section,
                atlas_reference,
                atlas_mask,
                cfg,
                section_mask=affine_warped_display_mask,
            )
            affine_overlay_path_obj = affine_overlay_dir / f"section{section_index:03d}_affine_overlay.png"
            Image.fromarray(affine_overlay, mode="RGB").save(affine_overlay_path_obj)
            affine_overlay_path = str(affine_overlay_path_obj)

        output_rows.append(
            {
                **row,
                "warped_section_path": str(warped_path),
                "registration_overlay_path": str(overlay_path),
                "registration_affine_overlay_path": affine_overlay_path,
                "registration_status": registration["status"],
                "registration_loss": registration["loss"],
                "registration_dice": registration["dice"],
                "registration_iou": registration["iou"],
                "registration_transform_model": registration["transform_model"],
                "registration_scale": registration["scale"],
                "registration_scale_y": registration["scale_y"],
                "registration_scale_x": registration["scale_x"],
                "registration_rotation_degrees": registration["rotation_degrees"],
                "registration_affine_anisotropy": registration["affine_anisotropy"],
                "registration_affine_shear": registration["affine_shear"],
                "registration_affine_regularization_penalty": registration["affine_regularization_penalty"],
                "registration_translation_y": registration["translation_y"],
                "registration_translation_x": registration["translation_x"],
                "registration_warped_area_ratio": registration["warped_area_ratio"],
                "registration_warped_extent_y_ratio": registration["warped_extent_y_ratio"],
                "registration_warped_extent_x_ratio": registration["warped_extent_x_ratio"],
                "registration_warped_center_y_offset": registration["warped_center_y_offset"],
                "registration_warped_center_x_offset": registration["warped_center_x_offset"],
                "registration_boundary_area_ratio": registration["boundary_area_ratio"],
                "registration_boundary_extent_y_ratio": registration["boundary_extent_y_ratio"],
                "registration_boundary_extent_x_ratio": registration["boundary_extent_x_ratio"],
                "registration_boundary_outside_fraction": registration["boundary_outside_fraction"],
                "registration_affine_boundary_distance_norm": registration["affine_boundary_distance_norm"],
                "registration_nonlinear_refinement_model": registration["nonlinear_refinement_model"],
                "registration_nonlinear_iterations_completed": registration["nonlinear_iterations_completed"],
                "registration_nonlinear_max_displacement_px": registration["nonlinear_max_displacement_px"],
                "registration_nonlinear_mean_displacement_px": registration["nonlinear_mean_displacement_px"],
                "registration_matrix": json.dumps(registration["matrix"]),
            }
        )
        section_indices.append(section_index)

    manifest_path = registration_dir / cfg.output_name
    metadata_path = registration_dir / cfg.metadata_name
    _write_manifest(manifest_path, output_rows)
    _write_json(
        metadata_path,
        {
            "input_manifest_path": str(manifest),
            "config": asdict(cfg),
            "section_indices": section_indices,
            "rows": [
                {
                    "section_index": int(row["section_index"]),
                    "registration_status": row["registration_status"],
                    "registration_dice": float(row["registration_dice"]),
                    "registration_iou": float(row["registration_iou"]),
                    "registration_loss": float(row["registration_loss"]),
                    "registration_transform_model": row["registration_transform_model"],
                    "registration_scale": float(row["registration_scale"]),
                    "registration_scale_y": float(row["registration_scale_y"]),
                    "registration_scale_x": float(row["registration_scale_x"]),
                    "registration_rotation_degrees": float(row["registration_rotation_degrees"]),
                    "registration_affine_anisotropy": float(row["registration_affine_anisotropy"]),
                    "registration_affine_shear": float(row["registration_affine_shear"]),
                    "registration_affine_regularization_penalty": float(row["registration_affine_regularization_penalty"]),
                    "registration_warped_area_ratio": float(row["registration_warped_area_ratio"]),
                    "registration_warped_extent_y_ratio": float(row["registration_warped_extent_y_ratio"]),
                    "registration_warped_extent_x_ratio": float(row["registration_warped_extent_x_ratio"]),
                    "registration_warped_center_y_offset": float(row["registration_warped_center_y_offset"]),
                    "registration_warped_center_x_offset": float(row["registration_warped_center_x_offset"]),
                    "registration_boundary_area_ratio": float(row["registration_boundary_area_ratio"]),
                    "registration_boundary_extent_y_ratio": float(row["registration_boundary_extent_y_ratio"]),
                    "registration_boundary_extent_x_ratio": float(row["registration_boundary_extent_x_ratio"]),
                    "registration_boundary_outside_fraction": float(row["registration_boundary_outside_fraction"]),
                    "registration_affine_boundary_distance_norm": float(row["registration_affine_boundary_distance_norm"]),
                    "registration_nonlinear_refinement_model": row["registration_nonlinear_refinement_model"],
                    "registration_nonlinear_iterations_completed": int(row["registration_nonlinear_iterations_completed"]),
                    "registration_nonlinear_max_displacement_px": float(row["registration_nonlinear_max_displacement_px"]),
                    "registration_nonlinear_mean_displacement_px": float(row["registration_nonlinear_mean_displacement_px"]),
                }
                for row in output_rows
            ],
        },
    )

    return SliceRegistrationResult(
        output_dir=registration_dir,
        manifest_path=manifest_path,
        metadata_path=metadata_path,
        warped_sections_dir=warped_sections_dir,
        overlay_dir=overlay_dir,
        section_indices=section_indices,
    )


def _register_section_to_atlas(
    *,
    section_image: np.ndarray,
    atlas_reference: np.ndarray,
    atlas_mask: np.ndarray,
    config: SliceRegistrationConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    prepared = _prepare_section_registration_input(section_image, config)
    return _register_prepared_section_to_atlas(
        prepared_section=prepared,
        atlas_reference=atlas_reference,
        atlas_mask=atlas_mask,
        config=config,
    )


def _prepare_section_registration_input(
    section_image: np.ndarray,
    config: SliceRegistrationConfig,
) -> _PreparedSectionRegistrationInput | None:
    section_mask = _tissue_mask(section_image, quantile=config.tissue_threshold_quantile)
    section_bbox = _bbox(section_mask)
    if section_bbox is None:
        return None

    section_crop = section_image[section_bbox[0] : section_bbox[1], section_bbox[2] : section_bbox[3]].astype(np.float32)
    section_mask_crop = section_mask[section_bbox[0] : section_bbox[1], section_bbox[2] : section_bbox[3]]
    return _PreparedSectionRegistrationInput(
        section_crop=section_crop,
        section_mask_crop=section_mask_crop,
        section_display_mask_crop=_display_tissue_mask(section_crop, config),
        section_boundary_mask_crop=_boundary_fit_mask(section_crop, config),
    )


def _register_prepared_section_to_atlas(
    *,
    prepared_section: _PreparedSectionRegistrationInput | None,
    atlas_reference: np.ndarray,
    atlas_mask: np.ndarray,
    config: SliceRegistrationConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    atlas_bbox = _bbox(atlas_mask)
    atlas_shape = atlas_reference.shape

    if prepared_section is None or atlas_bbox is None:
        warped = np.full(atlas_shape, config.fill_value, dtype=np.float32)
        return warped, _empty_registration()

    section_crop = prepared_section.section_crop
    section_mask_crop = prepared_section.section_mask_crop
    section_display_mask_crop = prepared_section.section_display_mask_crop
    section_boundary_mask_crop = prepared_section.section_boundary_mask_crop
    initial = _initial_similarity_parameters(section_mask_crop, atlas_mask, atlas_bbox, config)
    best_params, best_loss = _estimate_similarity_parameters(
        section_mask_crop=section_mask_crop.astype(np.float32),
        section_boundary_mask_crop=section_boundary_mask_crop.astype(np.float32),
        atlas_mask=atlas_mask.astype(np.float32),
        initial=initial,
        config=config,
    )
    transform_matrix = _similarity_matrix(best_params[0], best_params[1], best_params[2], best_params[3], section_crop.shape)
    affine_metadata = _similarity_transform_metadata(transform_matrix, best_params, transform_model="similarity")
    if config.transform_model == "affine":
        transform_matrix, best_loss, affine_metadata = _estimate_affine_transform(
            section_mask_crop=section_mask_crop.astype(np.float32),
            section_boundary_mask_crop=section_boundary_mask_crop.astype(np.float32),
            atlas_mask=atlas_mask.astype(np.float32),
            similarity_params=best_params,
            similarity_loss=best_loss,
            config=config,
        )
    elif config.transform_model != "similarity":
        raise ValueError("transform_model must be one of: 'similarity', 'affine'.")

    affine_warped_section = _warp_image(section_crop, transform_matrix, atlas_shape, order=1, fill_value=config.fill_value)
    affine_warped_mask = (
        _warp_image(section_mask_crop.astype(np.float32), transform_matrix, atlas_shape, order=1, fill_value=0.0) >= 0.5
    )
    affine_warped_display_mask = (
        _warp_image(section_display_mask_crop.astype(np.float32), transform_matrix, atlas_shape, order=0, fill_value=0.0)
        >= 0.5
    )
    affine_warped_boundary_mask = (
        _warp_image(section_boundary_mask_crop.astype(np.float32), transform_matrix, atlas_shape, order=0, fill_value=0.0)
        >= 0.5
    )
    affine_boundary_metrics = _boundary_fit_metrics(affine_warped_boundary_mask, atlas_mask)
    affine_boundary_distance = _boundary_distance_metric_value(affine_warped_boundary_mask, atlas_mask)

    warped_section = affine_warped_section
    warped_mask = affine_warped_mask
    warped_display_mask = affine_warped_display_mask
    warped_boundary_mask = affine_warped_boundary_mask
    nonlinear_metadata = _empty_nonlinear_refinement_metadata(config)
    if config.nonlinear_refinement_model == "boundary_spline":
        (
            warped_section,
            warped_mask,
            warped_display_mask,
            warped_boundary_mask,
            nonlinear_metadata,
        ) = _apply_boundary_spline_refinement(
            warped_section=affine_warped_section,
            warped_mask=affine_warped_mask,
            warped_display_mask=affine_warped_display_mask,
            warped_boundary_mask=affine_warped_boundary_mask,
            atlas_mask=atlas_mask,
            config=config,
        )
    elif config.nonlinear_refinement_model != "none":
        raise ValueError("nonlinear_refinement_model must be one of: 'none', 'boundary_spline'.")

    dice, iou = _overlap_metrics(warped_mask, atlas_mask)
    shape_metrics = _shape_metrics(warped_mask, atlas_mask)
    boundary_metrics = _boundary_fit_metrics(warped_boundary_mask, atlas_mask)

    return warped_section, {
        "status": "ok",
        "loss": float(best_loss),
        "dice": float(dice),
        "iou": float(iou),
        **affine_metadata,
        "matrix": transform_matrix.tolist(),
        "_warped_mask": warped_mask,
        "_warped_display_mask": warped_display_mask,
        "_warped_boundary_mask": warped_boundary_mask,
        "_affine_warped_section": affine_warped_section if config.nonlinear_refinement_model != "none" else None,
        "_affine_warped_display_mask": affine_warped_display_mask if config.nonlinear_refinement_model != "none" else None,
        "affine_boundary_area_ratio": affine_boundary_metrics["boundary_area_ratio"],
        "affine_boundary_extent_y_ratio": affine_boundary_metrics["boundary_extent_y_ratio"],
        "affine_boundary_extent_x_ratio": affine_boundary_metrics["boundary_extent_x_ratio"],
        "affine_boundary_outside_fraction": affine_boundary_metrics["boundary_outside_fraction"],
        "affine_boundary_distance_norm": affine_boundary_distance,
        **nonlinear_metadata,
        **shape_metrics,
        **boundary_metrics,
    }


def _initial_similarity_parameters(
    section_mask: np.ndarray,
    atlas_mask: np.ndarray,
    atlas_bbox: tuple[int, int, int, int],
    config: SliceRegistrationConfig,
) -> tuple[float, float, float, float]:
    if config.scale_initialization == "area":
        scale = _area_scale(section_mask, atlas_mask)
    elif config.scale_initialization == "bbox_fit":
        section_bbox = _bbox(section_mask)
        scale = _bbox_fit_scale(section_bbox, atlas_bbox) if section_bbox is not None else _area_scale(section_mask, atlas_mask)
    else:
        raise ValueError("scale_initialization must be one of: 'bbox_fit', 'area'.")

    if config.initial_rotation_degrees is None:
        section_orientation = _mask_orientation(section_mask)
        atlas_orientation = _mask_orientation(atlas_mask)
        rotation = float(atlas_orientation - section_orientation)
    else:
        rotation = float(np.deg2rad(config.initial_rotation_degrees))

    atlas_center_y, atlas_center_x = _mask_centroid(atlas_mask)
    translation_y = float(atlas_center_y)
    translation_x = float(atlas_center_x)

    if config.translation_initialization == "tissue_centroid":
        section_center = np.asarray(
            [
                (section_mask.shape[0] - 1) / 2.0,
                (section_mask.shape[1] - 1) / 2.0,
            ],
            dtype=np.float64,
        )
        section_centroid = np.asarray(_mask_centroid(section_mask), dtype=np.float64)
        cos_theta = float(np.cos(rotation))
        sin_theta = float(np.sin(rotation))
        linear = np.asarray(
            [
                [scale * cos_theta, scale * sin_theta],
                [-scale * sin_theta, scale * cos_theta],
            ],
            dtype=np.float64,
        )
        adjusted_translation = np.asarray([atlas_center_y, atlas_center_x], dtype=np.float64) + linear @ (
            section_center - section_centroid
        )
        translation_y = float(adjusted_translation[0])
        translation_x = float(adjusted_translation[1])
    elif config.translation_initialization != "crop_center":
        raise ValueError("translation_initialization must be one of: 'crop_center', 'tissue_centroid'.")

    if not np.isfinite(scale) or scale <= 0:
        scale = _area_scale(section_mask, atlas_mask)
    if not np.isfinite(rotation):
        rotation = 0.0
    if not np.isfinite(translation_y):
        translation_y = float(atlas_bbox[0])
    if not np.isfinite(translation_x):
        translation_x = float(atlas_bbox[2])
    return scale, rotation, translation_y, translation_x


def _area_scale(section_mask: np.ndarray, atlas_mask: np.ndarray) -> float:
    section_area = max(1.0, float(np.asarray(section_mask).sum()))
    atlas_area = max(1.0, float(np.asarray(atlas_mask).sum()))
    return float(np.sqrt(atlas_area / section_area))


def _bbox_fit_scale(
    section_bbox: tuple[int, int, int, int],
    atlas_bbox: tuple[int, int, int, int],
) -> float:
    section_height = max(1.0, float(section_bbox[1] - section_bbox[0]))
    section_width = max(1.0, float(section_bbox[3] - section_bbox[2]))
    atlas_height = max(1.0, float(atlas_bbox[1] - atlas_bbox[0]))
    atlas_width = max(1.0, float(atlas_bbox[3] - atlas_bbox[2]))
    return float(min(atlas_height / section_height, atlas_width / section_width))


def _estimate_similarity_parameters(
    *,
    section_mask_crop: np.ndarray,
    section_boundary_mask_crop: np.ndarray,
    atlas_mask: np.ndarray,
    initial: tuple[float, float, float, float],
    config: SliceRegistrationConfig,
) -> tuple[np.ndarray, float]:
    search_section, search_atlas, scale_y, scale_x = _downsample_pair(section_mask_crop, atlas_mask)
    search_boundary, _, _, _ = _downsample_pair(section_boundary_mask_crop, atlas_mask)
    initial_search = np.asarray(
        [
            initial[0],
            initial[1],
            initial[2] * scale_y,
            initial[3] * scale_x,
        ],
        dtype=np.float64,
    )
    best_params = initial_search.copy()
    best_loss = _registration_loss(
        best_params,
        search_section,
        search_atlas,
        search_atlas.shape,
        config,
        section_boundary_mask=search_boundary,
    )

    min_scale = max(1e-3, initial[0] * config.min_scale_factor)
    max_scale = max(min_scale, initial[0] * config.max_scale_factor)
    min_rotation = initial[1] - np.deg2rad(config.max_rotation_degrees)
    max_rotation = initial[1] + np.deg2rad(config.max_rotation_degrees)
    scale_values = np.linspace(min_scale, max_scale, 3)
    rotation_values = np.linspace(min_rotation, max_rotation, 5)
    translation_y_offsets = np.linspace(
        -search_atlas.shape[0] * config.translation_search_fraction,
        search_atlas.shape[0] * config.translation_search_fraction,
        3,
    )
    translation_x_offsets = np.linspace(
        -search_atlas.shape[1] * config.translation_search_fraction,
        search_atlas.shape[1] * config.translation_search_fraction,
        3,
    )

    for scale in scale_values:
        for rotation in rotation_values:
            params = np.asarray([scale, rotation, initial_search[2], initial_search[3]], dtype=np.float64)
            loss = _registration_loss(
                params,
                search_section,
                search_atlas,
                search_atlas.shape,
                config,
                section_boundary_mask=search_boundary,
            )
            if loss < best_loss:
                best_loss = loss
                best_params = params

    for delta_y in translation_y_offsets:
        for delta_x in translation_x_offsets:
            params = np.asarray(
                [best_params[0], best_params[1], initial_search[2] + delta_y, initial_search[3] + delta_x],
                dtype=np.float64,
            )
            loss = _registration_loss(
                params,
                search_section,
                search_atlas,
                search_atlas.shape,
                config,
                section_boundary_mask=search_boundary,
            )
            if loss < best_loss:
                best_loss = loss
                best_params = params

    refined_scale_offsets = np.linspace(-0.08, 0.08, 3)
    refined_rotation_offsets = np.deg2rad(np.linspace(-4.0, 4.0, 3))
    refined_translation_y_offsets = np.linspace(-max(2.0, search_atlas.shape[0] * 0.04), max(2.0, search_atlas.shape[0] * 0.04), 3)
    refined_translation_x_offsets = np.linspace(-max(2.0, search_atlas.shape[1] * 0.04), max(2.0, search_atlas.shape[1] * 0.04), 3)

    refined_base = best_params.copy()
    for scale_offset in refined_scale_offsets:
        scale = float(np.clip(refined_base[0] * (1.0 + scale_offset), min_scale, max_scale))
        for rotation_offset in refined_rotation_offsets:
            rotation = float(np.clip(refined_base[1] + rotation_offset, min_rotation, max_rotation))
            params = np.asarray(
                [scale, rotation, refined_base[2], refined_base[3]],
                dtype=np.float64,
            )
            loss = _registration_loss(
                params,
                search_section,
                search_atlas,
                search_atlas.shape,
                config,
                section_boundary_mask=search_boundary,
            )
            if loss < best_loss:
                best_loss = loss
                best_params = params

    refined_base = best_params.copy()
    for delta_y in refined_translation_y_offsets:
        for delta_x in refined_translation_x_offsets:
            params = np.asarray(
                [refined_base[0], refined_base[1], refined_base[2] + delta_y, refined_base[3] + delta_x],
                dtype=np.float64,
            )
            loss = _registration_loss(
                params,
                search_section,
                search_atlas,
                search_atlas.shape,
                config,
                section_boundary_mask=search_boundary,
            )
            if loss < best_loss:
                best_loss = loss
                best_params = params

    return np.asarray(
        [
            best_params[0],
            best_params[1],
            best_params[2] / scale_y,
            best_params[3] / scale_x,
        ],
        dtype=np.float64,
    ), float(best_loss)


def _estimate_affine_transform(
    *,
    section_mask_crop: np.ndarray,
    section_boundary_mask_crop: np.ndarray,
    atlas_mask: np.ndarray,
    similarity_params: np.ndarray,
    similarity_loss: float,
    config: SliceRegistrationConfig,
) -> tuple[np.ndarray, float, dict[str, float | str]]:
    search_section, search_atlas, scale_y, scale_x = _downsample_pair(section_mask_crop, atlas_mask)
    search_boundary, _, _, _ = _downsample_pair(section_boundary_mask_crop, atlas_mask)
    search_similarity = np.asarray(
        [
            similarity_params[0],
            similarity_params[1],
            similarity_params[2] * scale_y,
            similarity_params[3] * scale_x,
        ],
        dtype=np.float64,
    )
    base_search_matrix = _similarity_matrix(
        search_similarity[0],
        search_similarity[1],
        search_similarity[2],
        search_similarity[3],
        search_section.shape,
    )

    max_anisotropy = max(0.0, float(config.max_affine_anisotropy))
    max_shear = max(0.0, float(config.max_affine_shear))
    anisotropy_values = np.asarray(
        [-max_anisotropy, -0.5 * max_anisotropy, 0.0, 0.5 * max_anisotropy, max_anisotropy],
        dtype=np.float64,
    )
    shear_values = np.asarray([-max_shear, 0.0, max_shear], dtype=np.float64)
    if max_anisotropy == 0:
        anisotropy_values = np.asarray([0.0], dtype=np.float64)
    if max_shear == 0:
        shear_values = np.asarray([0.0], dtype=np.float64)

    translation_radius_y = max(1.0, float(search_atlas.shape[0]) * 0.025)
    translation_radius_x = max(1.0, float(search_atlas.shape[1]) * 0.025)
    translation_y_offsets = np.asarray([-translation_radius_y, 0.0, translation_radius_y], dtype=np.float64)
    translation_x_offsets = np.asarray([-translation_radius_x, 0.0, translation_radius_x], dtype=np.float64)

    best_search_matrix = base_search_matrix.copy()
    best_loss = float(similarity_loss)
    best_params = (0.0, 0.0, 0.0, 0.0)

    for anisotropy in anisotropy_values:
        for shear in shear_values:
            regularization = _affine_regularization_penalty(float(anisotropy), float(shear), config)
            for delta_y in translation_y_offsets:
                for delta_x in translation_x_offsets:
                    search_matrix = _refined_affine_matrix(
                        base_search_matrix,
                        search_section.shape,
                        anisotropy=float(anisotropy),
                        shear=float(shear),
                        delta_y=float(delta_y),
                        delta_x=float(delta_x),
                    )
                    loss = _registration_loss_for_matrix(
                        search_matrix,
                        search_section,
                        search_atlas,
                        search_atlas.shape,
                        config,
                        section_boundary_mask=search_boundary,
                        transform_regularization=regularization,
                    )
                    if loss < best_loss:
                        best_loss = loss
                        best_search_matrix = search_matrix
                        best_params = (float(anisotropy), float(shear), float(delta_y), float(delta_x))

    full_similarity_matrix = _similarity_matrix(
        similarity_params[0],
        similarity_params[1],
        similarity_params[2],
        similarity_params[3],
        section_mask_crop.shape,
    )
    full_matrix = _refined_affine_matrix(
        full_similarity_matrix,
        section_mask_crop.shape,
        anisotropy=best_params[0],
        shear=best_params[1],
        delta_y=best_params[2] / scale_y,
        delta_x=best_params[3] / scale_x,
    )
    metadata = _affine_metadata_from_matrix(
        full_matrix,
        source_shape=section_mask_crop.shape,
        transform_model="affine",
        anisotropy=best_params[0],
        shear=best_params[1],
        regularization_penalty=_affine_regularization_penalty(best_params[0], best_params[1], config),
    )
    return full_matrix, float(best_loss), metadata


def _refined_affine_matrix(
    base_matrix: np.ndarray,
    source_shape: tuple[int, int],
    *,
    anisotropy: float,
    shear: float,
    delta_y: float,
    delta_x: float,
) -> np.ndarray:
    delta = np.asarray(
        [
            [1.0 + float(anisotropy), float(shear)],
            [float(shear), 1.0 - float(anisotropy)],
        ],
        dtype=np.float64,
    )
    base_linear = np.asarray(base_matrix[:2, :2], dtype=np.float64)
    linear = np.asarray(
        [
            [
                base_linear[0, 0] * delta[0, 0] + base_linear[0, 1] * delta[1, 0],
                base_linear[0, 0] * delta[0, 1] + base_linear[0, 1] * delta[1, 1],
            ],
            [
                base_linear[1, 0] * delta[0, 0] + base_linear[1, 1] * delta[1, 0],
                base_linear[1, 0] * delta[0, 1] + base_linear[1, 1] * delta[1, 1],
            ],
        ],
        dtype=np.float64,
    )
    center = np.asarray([(source_shape[0] - 1) / 2.0, (source_shape[1] - 1) / 2.0], dtype=np.float64)
    base_offset = np.asarray(base_matrix[:2, 2], dtype=np.float64)
    base_translation = np.asarray(
        [
            base_linear[0, 0] * center[0] + base_linear[0, 1] * center[1] + base_offset[0],
            base_linear[1, 0] * center[0] + base_linear[1, 1] * center[1] + base_offset[1],
        ],
        dtype=np.float64,
    )
    translation = base_translation + np.asarray([float(delta_y), float(delta_x)], dtype=np.float64)
    return _affine_matrix(linear, translation[0], translation[1], source_shape)


def _affine_matrix(
    linear: np.ndarray,
    translation_y: float,
    translation_x: float,
    source_shape: tuple[int, int],
) -> np.ndarray:
    center = np.asarray([(source_shape[0] - 1) / 2.0, (source_shape[1] - 1) / 2.0], dtype=np.float64)
    matrix = np.eye(3, dtype=np.float64)
    matrix[:2, :2] = np.asarray(linear, dtype=np.float64)
    matrix[:2, 2] = np.asarray(
        [
            translation_y - matrix[0, 0] * center[0] - matrix[0, 1] * center[1],
            translation_x - matrix[1, 0] * center[0] - matrix[1, 1] * center[1],
        ],
        dtype=np.float64,
    )
    return matrix


def _affine_regularization_penalty(anisotropy: float, shear: float, config: SliceRegistrationConfig) -> float:
    weight = max(0.0, float(config.affine_regularization_weight))
    if weight == 0:
        return 0.0
    max_anisotropy = max(1e-6, float(config.max_affine_anisotropy))
    max_shear = max(1e-6, float(config.max_affine_shear))
    return float(weight * ((abs(float(anisotropy)) / max_anisotropy) ** 2 + (abs(float(shear)) / max_shear) ** 2))


def _similarity_transform_metadata(
    transform_matrix: np.ndarray,
    similarity_params: np.ndarray,
    *,
    transform_model: str,
) -> dict[str, float | str]:
    scale_y, scale_x, rotation_degrees = _matrix_scale_rotation(transform_matrix)
    return {
        "transform_model": transform_model,
        "scale": float(similarity_params[0]),
        "scale_y": scale_y,
        "scale_x": scale_x,
        "rotation_degrees": rotation_degrees,
        "affine_anisotropy": 0.0,
        "affine_shear": 0.0,
        "affine_regularization_penalty": 0.0,
        "translation_y": float(similarity_params[2]),
        "translation_x": float(similarity_params[3]),
    }


def _affine_metadata_from_matrix(
    transform_matrix: np.ndarray,
    *,
    source_shape: tuple[int, int],
    transform_model: str,
    anisotropy: float,
    shear: float,
    regularization_penalty: float,
) -> dict[str, float | str]:
    scale_y, scale_x, rotation_degrees = _matrix_scale_rotation(transform_matrix)
    center = np.asarray([(source_shape[0] - 1) / 2.0, (source_shape[1] - 1) / 2.0], dtype=np.float64)
    translation = np.asarray(transform_matrix[:2, 2], dtype=np.float64) + np.asarray(transform_matrix[:2, :2]) @ center
    return {
        "transform_model": transform_model,
        "scale": float(0.5 * (scale_y + scale_x)),
        "scale_y": float(scale_y),
        "scale_x": float(scale_x),
        "rotation_degrees": float(rotation_degrees),
        "affine_anisotropy": float(anisotropy),
        "affine_shear": float(shear),
        "affine_regularization_penalty": float(regularization_penalty),
        "translation_y": float(translation[0]),
        "translation_x": float(translation[1]),
    }


def _matrix_scale_rotation(transform_matrix: np.ndarray) -> tuple[float, float, float]:
    linear = np.asarray(transform_matrix[:2, :2], dtype=np.float64)
    scale_y = float(np.sqrt(linear[0, 0] * linear[0, 0] + linear[1, 0] * linear[1, 0]))
    scale_x = float(np.sqrt(linear[0, 1] * linear[0, 1] + linear[1, 1] * linear[1, 1]))
    rotation = float(np.rad2deg(np.arctan2(-linear[1, 0], linear[0, 0])))
    return scale_y, scale_x, rotation


def _downsample_pair(
    section_mask: np.ndarray,
    atlas_mask: np.ndarray,
    *,
    max_dim: int = 96,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    atlas_height, atlas_width = atlas_mask.shape
    scale = min(1.0, max_dim / max(atlas_height, atlas_width))
    scale_y = float(scale)
    scale_x = float(scale)
    atlas_shape = (
        max(16, int(round(atlas_height * scale_y))),
        max(16, int(round(atlas_width * scale_x))),
    )
    section_shape = (
        max(8, int(round(section_mask.shape[0] * scale_y))),
        max(8, int(round(section_mask.shape[1] * scale_x))),
    )
    search_section = _resize_image(
        section_mask.astype(np.float32),
        section_shape,
        order=1,
        fill_value=0.0,
    )
    search_atlas = _resize_image(
        atlas_mask.astype(np.float32),
        atlas_shape,
        order=1,
        fill_value=0.0,
    )
    return search_section, search_atlas, scale_y, scale_x


def _registration_loss(
    params: np.ndarray,
    section_mask: np.ndarray,
    atlas_mask: np.ndarray,
    atlas_shape: tuple[int, int],
    config: SliceRegistrationConfig,
    *,
    section_boundary_mask: np.ndarray | None = None,
) -> float:
    scale, rotation, translation_y, translation_x = [float(value) for value in params]
    transform_matrix = _similarity_matrix(scale, rotation, translation_y, translation_x, section_mask.shape)
    return _registration_loss_for_matrix(
        transform_matrix,
        section_mask,
        atlas_mask,
        atlas_shape,
        config,
        section_boundary_mask=section_boundary_mask,
    )


def _registration_loss_for_matrix(
    transform_matrix: np.ndarray,
    section_mask: np.ndarray,
    atlas_mask: np.ndarray,
    atlas_shape: tuple[int, int],
    config: SliceRegistrationConfig,
    *,
    section_boundary_mask: np.ndarray | None = None,
    transform_regularization: float = 0.0,
) -> float:
    warped = _warp_image(section_mask, transform_matrix, atlas_shape, order=1, fill_value=0.0)
    difference = warped - atlas_mask
    mse = float(np.mean(difference * difference))
    overlap = float(np.sum(np.minimum(warped, atlas_mask)))
    normalization = float(np.sum(np.maximum(warped, atlas_mask)) + 1e-6)
    shape_penalty = _shape_loss_penalty(warped, atlas_mask, config)
    boundary_penalty = 0.0
    if section_boundary_mask is not None and (config.boundary_fit_weight > 0 or config.boundary_containment_weight > 0):
        warped_boundary = _warp_image(section_boundary_mask, transform_matrix, atlas_shape, order=1, fill_value=0.0)
        boundary_penalty = _boundary_fit_loss_penalty(warped_boundary, atlas_mask, config)
    return mse + (1.0 - overlap / normalization) + shape_penalty + boundary_penalty + float(transform_regularization)


def _shape_loss_penalty(
    warped_mask: np.ndarray,
    atlas_mask: np.ndarray,
    config: SliceRegistrationConfig,
) -> float:
    if config.area_loss_weight <= 0 and config.extent_loss_weight <= 0 and config.center_loss_weight <= 0:
        return 0.0

    metrics = _shape_metrics(np.asarray(warped_mask) >= 0.5, np.asarray(atlas_mask) >= 0.5)
    area_penalty = abs(float(np.log(metrics["warped_area_ratio"])))
    extent_y_penalty = abs(float(np.log(metrics["warped_extent_y_ratio"])))
    extent_x_penalty = abs(float(np.log(metrics["warped_extent_x_ratio"])))
    extent_penalty = 0.5 * (extent_y_penalty + extent_x_penalty)
    center_penalty = abs(metrics["warped_center_y_offset"]) + abs(metrics["warped_center_x_offset"])
    return float(
        config.area_loss_weight * area_penalty
        + config.extent_loss_weight * extent_penalty
        + config.center_loss_weight * center_penalty
    )


def _boundary_fit_loss_penalty(
    warped_boundary_mask: np.ndarray,
    atlas_mask: np.ndarray,
    config: SliceRegistrationConfig,
) -> float:
    warped = np.asarray(warped_boundary_mask, dtype=np.float32)
    atlas = np.asarray(atlas_mask, dtype=np.float32)
    warped_binary = warped >= 0.5
    atlas_binary = atlas >= 0.5
    metrics = _boundary_fit_metrics(warped_binary, atlas_binary)

    overlap = float(np.sum(np.minimum(warped, atlas)))
    normalization = float(np.sum(np.maximum(warped, atlas)) + 1e-6)
    boundary_mismatch = 1.0 - overlap / normalization
    excess_extent = max(0.0, float(metrics["boundary_extent_y_ratio"]) - 1.0) + max(
        0.0,
        float(metrics["boundary_extent_x_ratio"]) - 1.0,
    )
    excess_area = max(0.0, float(metrics["boundary_area_ratio"]) - 1.0)
    containment = float(metrics["boundary_outside_fraction"]) + 0.5 * excess_extent + 0.5 * excess_area
    return float(config.boundary_fit_weight * boundary_mismatch + config.boundary_containment_weight * containment)


def _apply_boundary_spline_refinement(
    *,
    warped_section: np.ndarray,
    warped_mask: np.ndarray,
    warped_display_mask: np.ndarray,
    warped_boundary_mask: np.ndarray,
    atlas_mask: np.ndarray,
    config: SliceRegistrationConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    max_total_displacement = max(0.0, float(config.nonlinear_max_displacement_px))
    iterations = max(0, int(config.nonlinear_iterations))
    if max_total_displacement <= 0.0 or iterations <= 0:
        return (
            warped_section,
            warped_mask,
            warped_display_mask,
            warped_boundary_mask,
            _empty_nonlinear_refinement_metadata(config),
        )

    refined_section = np.asarray(warped_section, dtype=np.float32)
    refined_mask = np.asarray(warped_mask, dtype=bool)
    refined_display_mask = np.asarray(warped_display_mask, dtype=bool)
    refined_boundary_mask = np.asarray(warped_boundary_mask, dtype=bool)
    cumulative_dy = np.zeros(refined_section.shape, dtype=np.float32)
    cumulative_dx = np.zeros(refined_section.shape, dtype=np.float32)
    per_iteration_limit = max_total_displacement / max(1, iterations)
    completed = 0

    for _ in range(iterations):
        dy, dx = _boundary_displacement_field(
            refined_boundary_mask,
            atlas_mask,
            max_displacement_px=per_iteration_limit,
            control_point_spacing_px=config.nonlinear_control_point_spacing_px,
            sample_step=config.nonlinear_boundary_sample_step,
        )
        magnitude = np.sqrt(dy * dy + dx * dx)
        if not np.isfinite(magnitude).any() or float(magnitude.max(initial=0.0)) <= 1e-6:
            break

        refined_section = _warp_atlas_space_with_displacement(
            refined_section,
            dy,
            dx,
            order=1,
            fill_value=config.fill_value,
        )
        refined_mask = (
            _warp_atlas_space_with_displacement(refined_mask.astype(np.float32), dy, dx, order=0, fill_value=0.0) >= 0.5
        )
        refined_display_mask = (
            _warp_atlas_space_with_displacement(
                refined_display_mask.astype(np.float32),
                dy,
                dx,
                order=0,
                fill_value=0.0,
            )
            >= 0.5
        )
        refined_boundary_mask = (
            _warp_atlas_space_with_displacement(
                refined_boundary_mask.astype(np.float32),
                dy,
                dx,
                order=0,
                fill_value=0.0,
            )
            >= 0.5
        )
        cumulative_dy += dy
        cumulative_dx += dx
        completed += 1

    displacement = np.sqrt(cumulative_dy * cumulative_dy + cumulative_dx * cumulative_dx)
    active = displacement > 1e-6
    mean_displacement = float(displacement[active].mean()) if np.any(active) else 0.0
    max_displacement = float(displacement.max(initial=0.0))
    return (
        refined_section,
        refined_mask,
        refined_display_mask,
        refined_boundary_mask,
        {
            "nonlinear_refinement_model": config.nonlinear_refinement_model,
            "nonlinear_iterations_completed": int(completed),
            "nonlinear_max_displacement_px": max_displacement,
            "nonlinear_mean_displacement_px": mean_displacement,
        },
    )


def _boundary_displacement_field(
    section_boundary_mask: np.ndarray,
    atlas_mask: np.ndarray,
    *,
    max_displacement_px: float,
    control_point_spacing_px: float,
    sample_step: int,
) -> tuple[np.ndarray, np.ndarray]:
    section_boundary = _boundary_mask(np.asarray(section_boundary_mask, dtype=bool))
    atlas_boundary = _boundary_mask(np.asarray(atlas_mask, dtype=bool))
    if not np.any(section_boundary) or not np.any(atlas_boundary):
        shape = np.asarray(atlas_mask).shape
        return np.zeros(shape, dtype=np.float32), np.zeros(shape, dtype=np.float32)

    sample_mask = section_boundary.copy()
    step = max(1, int(sample_step))
    if step > 1:
        yy, xx = _target_grid(section_boundary.shape[0], section_boundary.shape[1])
        sample_mask &= (np.rint(yy).astype(np.intp) % step == 0) & (np.rint(xx).astype(np.intp) % step == 0)
        if not np.any(sample_mask):
            sample_mask = section_boundary

    _, nearest_indices = ndimage.distance_transform_edt(np.logical_not(atlas_boundary), return_indices=True)
    source_y, source_x = np.nonzero(sample_mask)
    target_y = nearest_indices[0, source_y, source_x].astype(np.float32)
    target_x = nearest_indices[1, source_y, source_x].astype(np.float32)
    dy_values = target_y - source_y.astype(np.float32)
    dx_values = target_x - source_x.astype(np.float32)
    dy_values, dx_values = _clip_displacement_vectors(dy_values, dx_values, max_displacement_px=max_displacement_px)

    shape = section_boundary.shape
    sparse_dy = np.zeros(shape, dtype=np.float32)
    sparse_dx = np.zeros(shape, dtype=np.float32)
    weights = np.zeros(shape, dtype=np.float32)
    sparse_dy[source_y, source_x] = dy_values
    sparse_dx[source_y, source_x] = dx_values
    weights[source_y, source_x] = 1.0

    sigma = max(1.0, float(control_point_spacing_px) / 2.0)
    smooth_weights = ndimage.gaussian_filter(weights, sigma=sigma, mode="nearest")
    smooth_dy = ndimage.gaussian_filter(sparse_dy, sigma=sigma, mode="nearest")
    smooth_dx = ndimage.gaussian_filter(sparse_dx, sigma=sigma, mode="nearest")
    valid = smooth_weights > 1e-6
    dy = np.zeros(shape, dtype=np.float32)
    dx = np.zeros(shape, dtype=np.float32)
    dy[valid] = smooth_dy[valid] / smooth_weights[valid]
    dx[valid] = smooth_dx[valid] / smooth_weights[valid]
    dy, dx = _clip_displacement_vectors(dy, dx, max_displacement_px=max_displacement_px)
    return dy.astype(np.float32), dx.astype(np.float32)


def _clip_displacement_vectors(
    dy: np.ndarray,
    dx: np.ndarray,
    *,
    max_displacement_px: float,
) -> tuple[np.ndarray, np.ndarray]:
    limit = max(0.0, float(max_displacement_px))
    dy_array = np.asarray(dy, dtype=np.float32)
    dx_array = np.asarray(dx, dtype=np.float32)
    if limit <= 0.0:
        return np.zeros_like(dy_array), np.zeros_like(dx_array)
    magnitude = np.sqrt(dy_array * dy_array + dx_array * dx_array)
    scale = np.ones_like(magnitude, dtype=np.float32)
    large = magnitude > limit
    scale[large] = limit / np.maximum(magnitude[large], 1e-6)
    return dy_array * scale, dx_array * scale


def _warp_atlas_space_with_displacement(
    image: np.ndarray,
    dy: np.ndarray,
    dx: np.ndarray,
    *,
    order: int,
    fill_value: float,
) -> np.ndarray:
    yy, xx = _target_grid(dy.shape[0], dy.shape[1])
    source_y = yy - np.asarray(dy, dtype=np.float32)
    source_x = xx - np.asarray(dx, dtype=np.float32)
    return _sample_image(np.asarray(image, dtype=np.float32), source_y, source_x, order=order, fill_value=fill_value)


def _similarity_matrix(
    scale: float,
    rotation_radians: float,
    translation_y: float,
    translation_x: float,
    source_shape: tuple[int, int],
) -> np.ndarray:
    center_y = (source_shape[0] - 1) / 2.0
    center_x = (source_shape[1] - 1) / 2.0
    cos_theta = float(np.cos(rotation_radians))
    sin_theta = float(np.sin(rotation_radians))
    linear = np.asarray(
        [
            [scale * cos_theta, scale * sin_theta],
            [-scale * sin_theta, scale * cos_theta],
        ],
        dtype=np.float64,
    )
    offset = np.asarray([translation_y, translation_x], dtype=np.float64) - linear @ np.asarray(
        [center_y, center_x],
        dtype=np.float64,
    )
    matrix = np.eye(3, dtype=np.float64)
    matrix[:2, :2] = linear
    matrix[:2, 2] = offset
    return matrix


def _warp_image(
    image: np.ndarray,
    transform_matrix: np.ndarray,
    output_shape: tuple[int, int],
    *,
    order: int,
    fill_value: float,
) -> np.ndarray:
    array = np.asarray(image, dtype=np.float32)
    if array.size == 0:
        return np.full(output_shape, fill_value, dtype=np.float32)
    inverse_linear, inverse_offset = _invert_affine_2d(transform_matrix)
    yy, xx = _target_grid(output_shape[0], output_shape[1])
    centered_y = yy - inverse_offset[0]
    centered_x = xx - inverse_offset[1]
    source_y = inverse_linear[0, 0] * centered_y + inverse_linear[0, 1] * centered_x
    source_x = inverse_linear[1, 0] * centered_y + inverse_linear[1, 1] * centered_x
    return _sample_image(array, source_y, source_x, order=order, fill_value=fill_value)


def _resize_image(
    image: np.ndarray,
    output_shape: tuple[int, int],
    *,
    order: int,
    fill_value: float,
) -> np.ndarray:
    source = np.asarray(image, dtype=np.float32)
    if source.shape == output_shape:
        return source.copy()
    if output_shape[0] <= 0 or output_shape[1] <= 0:
        raise ValueError(f"Invalid output shape {output_shape!r}.")

    if source.shape[0] == 1:
        source_y = np.zeros(output_shape, dtype=np.float32)
    else:
        source_y_values = np.linspace(0, source.shape[0] - 1, output_shape[0], dtype=np.float32)
        source_y = np.repeat(source_y_values[:, None], output_shape[1], axis=1)

    if source.shape[1] == 1:
        source_x = np.zeros(output_shape, dtype=np.float32)
    else:
        source_x_values = np.linspace(0, source.shape[1] - 1, output_shape[1], dtype=np.float32)
        source_x = np.repeat(source_x_values[None, :], output_shape[0], axis=0)

    return _sample_image(source, source_y, source_x, order=order, fill_value=fill_value)


def _sample_image(
    image: np.ndarray,
    source_y: np.ndarray,
    source_x: np.ndarray,
    *,
    order: int,
    fill_value: float,
) -> np.ndarray:
    source = np.asarray(image, dtype=np.float32)
    if source.ndim != 2:
        raise ValueError(f"_sample_image expects a 2D image, got shape {source.shape}.")

    valid = (
        np.isfinite(source_y)
        & np.isfinite(source_x)
        & (source_y >= 0.0)
        & (source_y <= source.shape[0] - 1)
        & (source_x >= 0.0)
        & (source_x <= source.shape[1] - 1)
    )
    output = np.full(source_y.shape, fill_value, dtype=np.float32)
    if not np.any(valid):
        return output

    if order == 0:
        nearest_y = np.rint(source_y[valid]).astype(np.intp)
        nearest_x = np.rint(source_x[valid]).astype(np.intp)
        output[valid] = source[nearest_y, nearest_x]
        return output

    y = source_y[valid]
    x = source_x[valid]
    y0 = np.floor(y).astype(np.intp)
    x0 = np.floor(x).astype(np.intp)
    y1 = np.clip(y0 + 1, 0, source.shape[0] - 1)
    x1 = np.clip(x0 + 1, 0, source.shape[1] - 1)

    wy = y - y0
    wx = x - x0

    top_left = source[y0, x0]
    top_right = source[y0, x1]
    bottom_left = source[y1, x0]
    bottom_right = source[y1, x1]

    top = top_left * (1.0 - wx) + top_right * wx
    bottom = bottom_left * (1.0 - wx) + bottom_right * wx
    output[valid] = top * (1.0 - wy) + bottom * wy
    return output


def _invert_affine_2d(transform_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    linear = np.asarray(transform_matrix[:2, :2], dtype=np.float64)
    offset = np.asarray(transform_matrix[:2, 2], dtype=np.float64)
    determinant = float(linear[0, 0] * linear[1, 1] - linear[0, 1] * linear[1, 0])
    if abs(determinant) < 1e-12:
        raise ValueError("The affine transform is singular and cannot be inverted.")

    inverse_linear = np.asarray(
        [
            [linear[1, 1] / determinant, -linear[0, 1] / determinant],
            [-linear[1, 0] / determinant, linear[0, 0] / determinant],
        ],
        dtype=np.float32,
    )
    inverse_offset = np.asarray(offset, dtype=np.float32)
    return inverse_linear, inverse_offset


@lru_cache(maxsize=16)
def _target_grid(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    return np.meshgrid(
        np.arange(height, dtype=np.float32),
        np.arange(width, dtype=np.float32),
        indexing="ij",
    )


def _compose_overlay(
    warped_section: np.ndarray,
    atlas_reference: np.ndarray,
    atlas_mask: np.ndarray,
    cfg: SliceRegistrationConfig,
    *,
    section_mask: np.ndarray | None = None,
) -> np.ndarray:
    atlas_gray = _normalize_uint8(atlas_reference)
    section_gray = _normalize_uint8(warped_section)
    boundary_mask = _boundary_mask(atlas_mask)
    display_mask = None
    if cfg.mask_overlay_to_tissue:
        if section_mask is None:
            display_mask = _display_tissue_mask(warped_section, cfg)
        else:
            display_mask = np.asarray(section_mask, dtype=bool)

    atlas_rgb = np.stack([atlas_gray * (channel / 255.0) for channel in cfg.atlas_color], axis=-1)
    section_rgb = np.stack([section_gray * (channel / 255.0) for channel in cfg.section_color], axis=-1)
    blended = ((1.0 - cfg.overlay_alpha) * atlas_rgb + cfg.overlay_alpha * section_rgb).clip(0, 255)
    if display_mask is None:
        overlay = blended.astype(np.uint8)
    else:
        overlay = ((1.0 - cfg.overlay_alpha) * atlas_rgb).copy()
        overlay[display_mask] = blended[display_mask]
        overlay = overlay.clip(0, 255).astype(np.uint8)
    for channel, color in enumerate(cfg.boundary_color):
        overlay[..., channel] = np.where(boundary_mask, color, overlay[..., channel])
    return overlay


def _grayscale_image(path: Path) -> np.ndarray:
    image = np.asarray(imread(path))
    if image.ndim == 2:
        return image.astype(np.float32)
    if image.ndim == 3 and image.shape[-1] in (3, 4):
        return image[..., :3].max(axis=-1).astype(np.float32)
    if image.ndim == 3 and image.shape[0] <= 8:
        return image.max(axis=0).astype(np.float32)
    raise ValueError(f"Could not convert image with shape {image.shape} to grayscale.")


def _tissue_mask(image: np.ndarray, *, quantile: float) -> np.ndarray:
    finite = np.asarray(image, dtype=np.float32)
    if not np.isfinite(finite).any():
        return np.zeros_like(finite, dtype=bool)
    values = finite[np.isfinite(finite)]
    threshold = float(np.quantile(values, quantile))
    if np.all(values == values[0]):
        threshold = float(values[0])
    mask = finite > threshold
    mask = ndimage.binary_closing(mask, structure=_disk_footprint(3))
    mask = _remove_small_objects(mask, min_size=64)
    return np.asarray(mask, dtype=bool)


def _display_tissue_mask(image: np.ndarray, config: SliceRegistrationConfig) -> np.ndarray:
    """Build a permissive display mask that trims crop background without hiding dim tissue."""

    mask = _tissue_mask(image, quantile=config.overlay_mask_threshold_quantile)
    dilation_px = max(0, int(config.overlay_mask_dilation_px))
    if dilation_px > 0 and np.any(mask):
        mask = ndimage.binary_dilation(mask, structure=_disk_footprint(dilation_px))
        mask = ndimage.binary_closing(mask, structure=_disk_footprint(max(1, dilation_px // 2)))
    return np.asarray(mask, dtype=bool)


def _boundary_fit_mask(image: np.ndarray, config: SliceRegistrationConfig) -> np.ndarray:
    """Build a lower-threshold mask used to keep the visible slice boundary contained."""

    mask = _tissue_mask(image, quantile=config.boundary_fit_threshold_quantile)
    dilation_px = max(0, int(config.boundary_fit_dilation_px))
    if dilation_px > 0 and np.any(mask):
        mask = ndimage.binary_dilation(mask, structure=_disk_footprint(dilation_px))
    return np.asarray(mask, dtype=bool)


def _mask_orientation(mask: np.ndarray) -> float:
    coords = np.argwhere(mask)
    if coords.shape[0] < 3:
        return 0.0
    y = coords[:, 0].astype(np.float64)
    x = coords[:, 1].astype(np.float64)
    y_centered = y - y.mean()
    x_centered = x - x.mean()
    mu20 = float(np.sum(x_centered * x_centered))
    mu02 = float(np.sum(y_centered * y_centered))
    mu11 = float(np.sum(x_centered * y_centered))
    return 0.5 * float(np.arctan2(2.0 * mu11, mu20 - mu02))


def _mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    coords = np.argwhere(mask)
    if coords.size == 0:
        return 0.0, 0.0
    centroid = coords.mean(axis=0)
    return float(centroid[0]), float(centroid[1])


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1
    return int(y0), int(y1), int(x0), int(x1)


def _boundary_mask(mask: np.ndarray) -> np.ndarray:
    footprint = _disk_footprint(1)
    dilated = ndimage.binary_dilation(mask, structure=footprint)
    eroded = ndimage.binary_erosion(mask, structure=footprint)
    return np.logical_and(dilated, np.logical_not(eroded))


def _normalize_uint8(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image, dtype=np.float32)
    if not np.isfinite(array).any():
        return np.zeros(array.shape, dtype=np.uint8)
    array = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)
    low, high = np.percentile(array, (1, 99))
    if high <= low:
        scaled = np.zeros_like(array)
    else:
        scaled = np.clip((array - low) / (high - low), 0.0, 1.0) * 255.0
    return scaled.astype(np.uint8)


def _overlap_metrics(first: np.ndarray, second: np.ndarray) -> tuple[float, float]:
    intersection = float(np.logical_and(first, second).sum())
    first_area = float(first.sum())
    second_area = float(second.sum())
    union = float(np.logical_or(first, second).sum())
    dice = (2.0 * intersection) / max(1e-6, first_area + second_area)
    iou = intersection / max(1e-6, union)
    return dice, iou


def _shape_metrics(first: np.ndarray, second: np.ndarray) -> dict[str, float]:
    first_mask = np.asarray(first, dtype=bool)
    second_mask = np.asarray(second, dtype=bool)
    first_area = max(1.0, float(first_mask.sum()))
    second_area = max(1.0, float(second_mask.sum()))
    first_bbox = _bbox(first_mask)
    second_bbox = _bbox(second_mask)
    if first_bbox is None or second_bbox is None:
        return {
            "warped_area_ratio": first_area / second_area,
            "warped_extent_y_ratio": 1.0,
            "warped_extent_x_ratio": 1.0,
            "warped_center_y_offset": 0.0,
            "warped_center_x_offset": 0.0,
        }

    first_height = max(1.0, float(first_bbox[1] - first_bbox[0]))
    first_width = max(1.0, float(first_bbox[3] - first_bbox[2]))
    second_height = max(1.0, float(second_bbox[1] - second_bbox[0]))
    second_width = max(1.0, float(second_bbox[3] - second_bbox[2]))
    first_center_y = 0.5 * float(first_bbox[0] + first_bbox[1] - 1)
    first_center_x = 0.5 * float(first_bbox[2] + first_bbox[3] - 1)
    second_center_y = 0.5 * float(second_bbox[0] + second_bbox[1] - 1)
    second_center_x = 0.5 * float(second_bbox[2] + second_bbox[3] - 1)
    return {
        "warped_area_ratio": first_area / second_area,
        "warped_extent_y_ratio": first_height / second_height,
        "warped_extent_x_ratio": first_width / second_width,
        "warped_center_y_offset": (first_center_y - second_center_y) / second_height,
        "warped_center_x_offset": (first_center_x - second_center_x) / second_width,
    }


def _boundary_fit_metrics(boundary_mask: np.ndarray, atlas_mask: np.ndarray) -> dict[str, float]:
    metrics = _shape_metrics(boundary_mask, atlas_mask)
    boundary = np.asarray(boundary_mask, dtype=bool)
    atlas = np.asarray(atlas_mask, dtype=bool)
    boundary_area = max(1.0, float(boundary.sum()))
    outside = np.logical_and(boundary, np.logical_not(atlas))
    return {
        "boundary_area_ratio": metrics["warped_area_ratio"],
        "boundary_extent_y_ratio": metrics["warped_extent_y_ratio"],
        "boundary_extent_x_ratio": metrics["warped_extent_x_ratio"],
        "boundary_outside_fraction": float(outside.sum()) / boundary_area,
    }


def _boundary_distance_metric_value(boundary_mask: np.ndarray, atlas_mask: np.ndarray) -> float:
    boundary = _boundary_mask(np.asarray(boundary_mask, dtype=bool))
    atlas_boundary = _boundary_mask(np.asarray(atlas_mask, dtype=bool))
    if not np.any(boundary) or not np.any(atlas_boundary):
        return 1.0
    distance_to_atlas = ndimage.distance_transform_edt(np.logical_not(atlas_boundary))
    atlas_bbox = _bbox(np.asarray(atlas_mask, dtype=bool))
    if atlas_bbox is None:
        normalizer = float(max(atlas_mask.shape))
    else:
        atlas_height = max(1.0, float(atlas_bbox[1] - atlas_bbox[0]))
        atlas_width = max(1.0, float(atlas_bbox[3] - atlas_bbox[2]))
        normalizer = float(np.hypot(atlas_height, atlas_width))
    return min(1.0, float(np.mean(distance_to_atlas[boundary])) / max(1.0, normalizer))


def _empty_nonlinear_refinement_metadata(config: SliceRegistrationConfig) -> dict[str, Any]:
    return {
        "nonlinear_refinement_model": config.nonlinear_refinement_model,
        "nonlinear_iterations_completed": 0,
        "nonlinear_max_displacement_px": 0.0,
        "nonlinear_mean_displacement_px": 0.0,
    }


def _empty_registration() -> dict[str, Any]:
    return {
        "status": "empty_mask",
        "loss": 1.0,
        "dice": 0.0,
        "iou": 0.0,
        "transform_model": "none",
        "scale": 1.0,
        "scale_y": 1.0,
        "scale_x": 1.0,
        "rotation_degrees": 0.0,
        "affine_anisotropy": 0.0,
        "affine_shear": 0.0,
        "affine_regularization_penalty": 0.0,
        "translation_y": 0.0,
        "translation_x": 0.0,
        "matrix": np.eye(3, dtype=float).tolist(),
        "warped_area_ratio": 0.0,
        "warped_extent_y_ratio": 0.0,
        "warped_extent_x_ratio": 0.0,
        "warped_center_y_offset": 0.0,
        "warped_center_x_offset": 0.0,
        "boundary_area_ratio": 0.0,
        "boundary_extent_y_ratio": 0.0,
        "boundary_extent_x_ratio": 0.0,
        "boundary_outside_fraction": 0.0,
        "boundary_distance_norm": 1.0,
        "dorsal_midline_distance": 1.0,
        "dorsal_midline_y_offset": 0.0,
        "dorsal_midline_x_offset": 0.0,
        "affine_boundary_area_ratio": 0.0,
        "affine_boundary_extent_y_ratio": 0.0,
        "affine_boundary_extent_x_ratio": 0.0,
        "affine_boundary_outside_fraction": 0.0,
        "affine_boundary_distance_norm": 1.0,
        "nonlinear_refinement_model": "none",
        "nonlinear_iterations_completed": 0,
        "nonlinear_max_displacement_px": 0.0,
        "nonlinear_mean_displacement_px": 0.0,
    }


def _disk_footprint(radius: int) -> np.ndarray:
    if radius <= 0:
        return np.ones((1, 1), dtype=bool)
    yy, xx = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return (yy * yy + xx * xx) <= radius * radius


def _remove_small_objects(mask: np.ndarray, *, min_size: int) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return np.asarray(mask, dtype=bool)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= int(min_size)
    keep[0] = False
    return keep[labels]


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("section_index,warped_section_path,registration_overlay_path\n")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
