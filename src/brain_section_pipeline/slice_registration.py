"""Register slice-wise histology sections to paired atlas planes."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage
from tifffile import imread, imwrite


@dataclass(frozen=True)
class SliceRegistrationConfig:
    """Configuration for per-section 2D slice-to-atlas registration."""

    tissue_threshold_quantile: float = 0.8
    fill_value: float = 0.0
    overlay_alpha: float = 0.55
    boundary_color: tuple[int, int, int] = (0, 255, 0)
    section_color: tuple[int, int, int] = (255, 96, 96)
    atlas_color: tuple[int, int, int] = (180, 180, 180)
    max_rotation_degrees: float = 35.0
    min_scale_factor: float = 0.6
    max_scale_factor: float = 1.6
    translation_search_fraction: float = 0.25
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
    warped_sections_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)

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
        overlay = _compose_overlay(warped_section, atlas_reference, atlas_mask, cfg)

        warped_path = warped_sections_dir / f"section{section_index:03d}_warped.tif"
        overlay_path = overlay_dir / f"section{section_index:03d}_overlay.png"
        imwrite(warped_path, warped_section.astype(np.float32))
        Image.fromarray(overlay, mode="RGB").save(overlay_path)

        output_rows.append(
            {
                **row,
                "warped_section_path": str(warped_path),
                "registration_overlay_path": str(overlay_path),
                "registration_status": registration["status"],
                "registration_loss": registration["loss"],
                "registration_dice": registration["dice"],
                "registration_iou": registration["iou"],
                "registration_scale": registration["scale"],
                "registration_rotation_degrees": registration["rotation_degrees"],
                "registration_translation_y": registration["translation_y"],
                "registration_translation_x": registration["translation_x"],
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
                    "registration_scale": float(row["registration_scale"]),
                    "registration_rotation_degrees": float(row["registration_rotation_degrees"]),
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
    section_mask = _tissue_mask(section_image, quantile=config.tissue_threshold_quantile)
    section_bbox = _bbox(section_mask)
    atlas_bbox = _bbox(atlas_mask)
    atlas_shape = atlas_reference.shape

    if section_bbox is None or atlas_bbox is None:
        warped = np.full(atlas_shape, config.fill_value, dtype=np.float32)
        return warped, _empty_registration()

    section_crop = section_image[section_bbox[0] : section_bbox[1], section_bbox[2] : section_bbox[3]].astype(np.float32)
    section_mask_crop = section_mask[section_bbox[0] : section_bbox[1], section_bbox[2] : section_bbox[3]]
    initial = _initial_similarity_parameters(section_mask_crop, atlas_mask, atlas_bbox)
    best_params, best_loss = _estimate_similarity_parameters(
        section_mask_crop=section_mask_crop.astype(np.float32),
        atlas_mask=atlas_mask.astype(np.float32),
        initial=initial,
        config=config,
    )
    transform_matrix = _similarity_matrix(best_params[0], best_params[1], best_params[2], best_params[3], section_crop.shape)
    warped_section = _warp_image(section_crop, transform_matrix, atlas_shape, order=1, fill_value=config.fill_value)
    warped_mask = _warp_image(section_mask_crop.astype(np.float32), transform_matrix, atlas_shape, order=1, fill_value=0.0) >= 0.5
    dice, iou = _overlap_metrics(warped_mask, atlas_mask)

    return warped_section, {
        "status": "ok",
        "loss": float(best_loss),
        "dice": float(dice),
        "iou": float(iou),
        "scale": float(best_params[0]),
        "rotation_degrees": float(np.rad2deg(best_params[1])),
        "translation_y": float(best_params[2]),
        "translation_x": float(best_params[3]),
        "matrix": transform_matrix.tolist(),
    }


def _initial_similarity_parameters(
    section_mask: np.ndarray,
    atlas_mask: np.ndarray,
    atlas_bbox: tuple[int, int, int, int],
) -> tuple[float, float, float, float]:
    section_area = max(1.0, float(section_mask.sum()))
    atlas_area = max(1.0, float(atlas_mask.sum()))
    area_scale = float(np.sqrt(atlas_area / section_area))

    section_orientation = _mask_orientation(section_mask)
    atlas_orientation = _mask_orientation(atlas_mask)
    rotation = float(atlas_orientation - section_orientation)

    atlas_center_y, atlas_center_x = _mask_centroid(atlas_mask)
    translation_y = float(atlas_center_y)
    translation_x = float(atlas_center_x)

    if not np.isfinite(rotation):
        rotation = 0.0
    if not np.isfinite(translation_y):
        translation_y = float(atlas_bbox[0])
    if not np.isfinite(translation_x):
        translation_x = float(atlas_bbox[2])
    return area_scale, rotation, translation_y, translation_x


def _estimate_similarity_parameters(
    *,
    section_mask_crop: np.ndarray,
    atlas_mask: np.ndarray,
    initial: tuple[float, float, float, float],
    config: SliceRegistrationConfig,
) -> tuple[np.ndarray, float]:
    search_section, search_atlas, scale_y, scale_x = _downsample_pair(section_mask_crop, atlas_mask)
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
    best_loss = _registration_loss(best_params, search_section, search_atlas, search_atlas.shape)

    scale_values = initial[0] * np.linspace(config.min_scale_factor, config.max_scale_factor, 3)
    rotation_offsets = np.deg2rad(np.linspace(-config.max_rotation_degrees, config.max_rotation_degrees, 5))
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
        for rotation in initial[1] + rotation_offsets:
            params = np.asarray([scale, rotation, initial_search[2], initial_search[3]], dtype=np.float64)
            loss = _registration_loss(params, search_section, search_atlas, search_atlas.shape)
            if loss < best_loss:
                best_loss = loss
                best_params = params

    for delta_y in translation_y_offsets:
        for delta_x in translation_x_offsets:
            params = np.asarray(
                [best_params[0], best_params[1], initial_search[2] + delta_y, initial_search[3] + delta_x],
                dtype=np.float64,
            )
            loss = _registration_loss(params, search_section, search_atlas, search_atlas.shape)
            if loss < best_loss:
                best_loss = loss
                best_params = params

    refined_scale_offsets = np.linspace(-0.08, 0.08, 3)
    refined_rotation_offsets = np.deg2rad(np.linspace(-4.0, 4.0, 3))
    refined_translation_y_offsets = np.linspace(-max(2.0, search_atlas.shape[0] * 0.04), max(2.0, search_atlas.shape[0] * 0.04), 3)
    refined_translation_x_offsets = np.linspace(-max(2.0, search_atlas.shape[1] * 0.04), max(2.0, search_atlas.shape[1] * 0.04), 3)

    refined_base = best_params.copy()
    for scale_offset in refined_scale_offsets:
        scale = max(1e-3, refined_base[0] * (1.0 + scale_offset))
        for rotation_offset in refined_rotation_offsets:
            params = np.asarray(
                [scale, refined_base[1] + rotation_offset, refined_base[2], refined_base[3]],
                dtype=np.float64,
            )
            loss = _registration_loss(params, search_section, search_atlas, search_atlas.shape)
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
            loss = _registration_loss(params, search_section, search_atlas, search_atlas.shape)
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
) -> float:
    scale, rotation, translation_y, translation_x = [float(value) for value in params]
    transform_matrix = _similarity_matrix(scale, rotation, translation_y, translation_x, section_mask.shape)
    warped = _warp_image(section_mask, transform_matrix, atlas_shape, order=1, fill_value=0.0)
    difference = warped - atlas_mask
    mse = float(np.mean(difference * difference))
    overlap = float(np.sum(np.minimum(warped, atlas_mask)))
    normalization = float(np.sum(np.maximum(warped, atlas_mask)) + 1e-6)
    return mse + (1.0 - overlap / normalization)


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
) -> np.ndarray:
    atlas_gray = _normalize_uint8(atlas_reference)
    section_gray = _normalize_uint8(warped_section)
    boundary_mask = _boundary_mask(atlas_mask)

    atlas_rgb = np.stack([atlas_gray * (channel / 255.0) for channel in cfg.atlas_color], axis=-1)
    section_rgb = np.stack([section_gray * (channel / 255.0) for channel in cfg.section_color], axis=-1)
    overlay = ((1.0 - cfg.overlay_alpha) * atlas_rgb + cfg.overlay_alpha * section_rgb).clip(0, 255).astype(np.uint8)
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


def _empty_registration() -> dict[str, Any]:
    return {
        "status": "empty_mask",
        "loss": 1.0,
        "dice": 0.0,
        "iou": 0.0,
        "scale": 1.0,
        "rotation_degrees": 0.0,
        "translation_y": 0.0,
        "translation_x": 0.0,
        "matrix": np.eye(3, dtype=float).tolist(),
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
