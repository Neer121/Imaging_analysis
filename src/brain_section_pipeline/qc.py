"""Quality-control helpers for slice-wise atlas overlays."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from skimage import exposure, morphology, transform
from tifffile import imread


@dataclass(frozen=True)
class SliceAtlasQcConfig:
    """Configuration for coarse slice-to-atlas QC overlays."""

    fill_value: float = 0.0
    overlay_alpha: float = 0.55
    boundary_color: tuple[int, int, int] = (0, 255, 0)
    section_color: tuple[int, int, int] = (255, 64, 64)
    atlas_color: tuple[int, int, int] = (180, 180, 180)
    tissue_threshold_quantile: float = 0.80
    output_name: str = "slice_atlas_qc.json"


@dataclass(frozen=True)
class SliceAtlasQcResult:
    """Artifacts produced during slice-wise atlas QC generation."""

    output_dir: Path
    metadata_path: Path
    overlay_paths: list[Path]


def generate_slice_atlas_qc(
    pairing_manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    config: SliceAtlasQcConfig | None = None,
) -> SliceAtlasQcResult:
    """Generate coarse per-section atlas overlays for sparse slice workflows."""

    cfg = config or SliceAtlasQcConfig()
    manifest = Path(pairing_manifest_path)
    rows = _read_manifest_rows(manifest)
    if not rows:
        raise ValueError("The slice-wise atlas manifest is empty.")

    qc_dir = Path(output_dir) if output_dir is not None else manifest.parent / "qc_overlays"
    qc_dir.mkdir(parents=True, exist_ok=True)
    overlay_paths: list[Path] = []
    metadata_rows: list[dict[str, Any]] = []

    for row in rows:
        section_index = int(row["section_index"])
        section_image = _grayscale_image(Path(row["section_source_path"]))
        atlas_reference = _grayscale_image(Path(row["atlas_reference_path"]))
        atlas_annotation = np.asarray(imread(row["atlas_annotation_path"]))

        aligned_section, transform_info = _coarse_fit_section_to_atlas(section_image, atlas_annotation, cfg)
        overlay = _compose_overlay(aligned_section, atlas_reference, atlas_annotation, cfg)
        overlay_path = qc_dir / f"section{section_index:03d}_overlay.png"
        Image.fromarray(overlay, mode="RGB").save(overlay_path)
        overlay_paths.append(overlay_path)

        metadata_rows.append(
            {
                "section_index": section_index,
                "overlay_path": str(overlay_path),
                "atlas_slice_index": int(row["atlas_slice_index"]),
                **transform_info,
            }
        )

    metadata_path = qc_dir / cfg.output_name
    _write_json(metadata_path, {"config": asdict(cfg), "rows": metadata_rows})
    return SliceAtlasQcResult(output_dir=qc_dir, metadata_path=metadata_path, overlay_paths=overlay_paths)


def _coarse_fit_section_to_atlas(
    section_image: np.ndarray,
    atlas_annotation: np.ndarray,
    cfg: SliceAtlasQcConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    atlas_shape = atlas_annotation.shape
    section_mask = _tissue_mask(section_image, quantile=cfg.tissue_threshold_quantile)
    atlas_mask = np.asarray(atlas_annotation) > 0

    section_bbox = _bbox(section_mask)
    atlas_bbox = _bbox(atlas_mask)
    if section_bbox is None or atlas_bbox is None:
        canvas = np.full(atlas_shape, cfg.fill_value, dtype=np.float32)
        return canvas, {"scale_y": 1.0, "scale_x": 1.0, "top": 0, "left": 0}

    section_crop = section_image[section_bbox[0] : section_bbox[1], section_bbox[2] : section_bbox[3]]
    target_height = max(1, atlas_bbox[1] - atlas_bbox[0])
    target_width = max(1, atlas_bbox[3] - atlas_bbox[2])
    resized = transform.resize(
        section_crop,
        (target_height, target_width),
        order=1,
        preserve_range=True,
        anti_aliasing=True,
    ).astype(np.float32)

    canvas = np.full(atlas_shape, cfg.fill_value, dtype=np.float32)
    top = atlas_bbox[0]
    left = atlas_bbox[2]
    bottom = min(canvas.shape[0], top + resized.shape[0])
    right = min(canvas.shape[1], left + resized.shape[1])
    canvas[top:bottom, left:right] = resized[: bottom - top, : right - left]

    transform_info = {
        "scale_y": float(target_height / max(1, section_crop.shape[0])),
        "scale_x": float(target_width / max(1, section_crop.shape[1])),
        "top": int(top),
        "left": int(left),
    }
    return canvas, transform_info


def _compose_overlay(
    aligned_section: np.ndarray,
    atlas_reference: np.ndarray,
    atlas_annotation: np.ndarray,
    cfg: SliceAtlasQcConfig,
) -> np.ndarray:
    atlas_gray = _normalize_uint8(atlas_reference)
    section_gray = _normalize_uint8(aligned_section)
    boundary_mask = _boundary_mask(np.asarray(atlas_annotation) > 0)

    atlas_rgb = np.stack(
        [atlas_gray * (channel / 255.0) for channel in cfg.atlas_color],
        axis=-1,
    )
    section_rgb = np.stack(
        [section_gray * (channel / 255.0) for channel in cfg.section_color],
        axis=-1,
    )
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
    mask = morphology.binary_closing(mask, morphology.disk(3))
    mask = morphology.remove_small_objects(mask, min_size=64)
    return mask


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1
    return int(y0), int(y1), int(x0), int(x1)


def _boundary_mask(mask: np.ndarray) -> np.ndarray:
    dilated = morphology.binary_dilation(mask, morphology.disk(1))
    eroded = morphology.binary_erosion(mask, morphology.disk(1))
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
        scaled = exposure.rescale_intensity(array, in_range=(low, high), out_range=(0, 255))
    return scaled.astype(np.uint8)


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
