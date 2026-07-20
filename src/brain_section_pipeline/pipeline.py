"""End-to-end ND2 processing pipeline."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw
from tifffile import imwrite

from .crop import CropBox, detect_section_crops, save_crops
from .io import read_nd2_image
from .merge import DEFAULT_CHANNEL_COLORS, merge_channels


@dataclass
class PipelineConfig:
    """Configurable parameters for ND2 section cropping."""

    channel_colors: Sequence[Sequence[float]] = field(default_factory=lambda: DEFAULT_CHANNEL_COLORS)
    merge_channels: Sequence[int] | None = None
    percentiles: tuple[float, float] = (0.5, 99.8)
    mask_channel: int | None = 0
    min_area: int = 1_000_000
    margin: int = 250
    opening_radius: int = 2
    closing_iterations: int = 160
    threshold_method: str = "otsu"
    threshold_quantile: float = 0.90
    sort_mode: str = "row"
    row_tolerance: float | None = None
    final_box_padding: int = 32
    scene_index: int = 0
    position_index: int | None = None
    time_index: int = 0
    z_index: int | None = None
    z_projection: str = "max"
    output_extension: str = "tif"
    crop_output_mode: str = "rgb_direct"
    rgb_direct_channels: Sequence[int | None] = (2, 1, 0)
    save_raw_channel_crops: bool = False
    preview_max_dim: int | None = None


@dataclass(frozen=True)
class ProcessingResult:
    """Paths and crop boxes produced for one ND2 file."""

    input_path: Path
    output_dir: Path
    merged_path: Path
    overlay_path: Path
    manifest_path: Path
    metadata_path: Path
    crop_paths: list[Path]
    raw_crop_paths: list[Path]
    boxes: list[CropBox]


def process_nd2_file(
    path: str | Path,
    output_dir: str | Path,
    config: PipelineConfig | None = None,
    *,
    crop_output_dir: str | Path | None = None,
    crop_start_index: int = 1,
    crop_stem: str | None = None,
    crop_filename_template: str = "{stem}_section{index:03d}.{extension}",
) -> ProcessingResult:
    """Read one ND2 file, merge channels, detect sections, and save crops."""

    cfg = config or PipelineConfig()
    input_path = Path(path)
    file_output_dir = Path(output_dir) / input_path.stem
    file_output_dir.mkdir(parents=True, exist_ok=True)

    nd2_image = read_nd2_image(
        input_path,
        scene_index=cfg.scene_index,
        position_index=cfg.position_index,
        time_index=cfg.time_index,
        z_index=cfg.z_index,
        z_projection=cfg.z_projection,
    )
    preview_source = _preview_source_image(nd2_image.data, cfg.preview_max_dim)
    rgb = merge_channels(
        preview_source,
        channel_colors=cfg.channel_colors,
        percentiles=cfg.percentiles,
        channels=cfg.merge_channels,
    )
    detection = detect_section_crops(
        nd2_image.data if cfg.mask_channel is not None else rgb,
        mask_channel=cfg.mask_channel,
        min_area=cfg.min_area,
        margin=cfg.margin,
        opening_radius=cfg.opening_radius,
        closing_iterations=cfg.closing_iterations,
        threshold_method=cfg.threshold_method,  # type: ignore[arg-type]
        threshold_quantile=cfg.threshold_quantile,
        sort_mode=cfg.sort_mode,  # type: ignore[arg-type]
        row_tolerance=cfg.row_tolerance,
        final_box_padding=cfg.final_box_padding,
    )

    merged_path = file_output_dir / f"{input_path.stem}_merged.tif"
    overlay_path = file_output_dir / f"{input_path.stem}_crops_overlay.png"
    metadata_path = file_output_dir / f"{input_path.stem}_metadata.json"
    manifest_path = file_output_dir / f"{input_path.stem}_crop_manifest.csv"
    crop_dir = Path(crop_output_dir) if crop_output_dir is not None else file_output_dir

    imwrite(merged_path, rgb)
    _save_overlay(rgb, detection.boxes, overlay_path, source_shape=detection.mask.shape)
    if cfg.crop_output_mode == "rgb_direct":
        crop_paths = _save_rgb_direct_crops(
            nd2_image.data,
            detection.boxes,
            crop_dir,
            stem=crop_stem or input_path.stem,
            extension=cfg.output_extension,
            start_index=crop_start_index,
            filename_template=crop_filename_template,
            rgb_channels=cfg.rgb_direct_channels,
        )
    else:
        crop_source = _crop_output_image(nd2_image.data, rgb, cfg)
        crop_paths = save_crops(
            crop_source,
            detection.boxes,
            crop_dir,
            stem=crop_stem or input_path.stem,
            extension=cfg.output_extension,
            start_index=crop_start_index,
            filename_template=crop_filename_template,
        )

    raw_crop_paths: list[Path] = []
    if cfg.save_raw_channel_crops:
        raw_dir = file_output_dir / "raw_channel_crops"
        raw_crop_paths = save_crops(
            nd2_image.data,
            detection.boxes,
            raw_dir,
            stem=input_path.stem,
            extension=cfg.output_extension,
        )

    _write_manifest(manifest_path, input_path, crop_paths, detection.boxes, start_index=crop_start_index)
    _write_json(
        metadata_path,
        {
            "input_path": str(input_path),
            "config": asdict(cfg),
            "nd2": nd2_image.metadata,
            "sizes": nd2_image.sizes,
            "threshold": detection.threshold,
            "section_count": len(detection.boxes),
        },
    )

    return ProcessingResult(
        input_path=input_path,
        output_dir=file_output_dir,
        merged_path=merged_path,
        overlay_path=overlay_path,
        manifest_path=manifest_path,
        metadata_path=metadata_path,
        crop_paths=crop_paths,
        raw_crop_paths=raw_crop_paths,
        boxes=detection.boxes,
    )


def process_selected_files(
    paths: Sequence[str | Path],
    output_dir: str | Path,
    config: PipelineConfig | None = None,
    *,
    continuous_crop_numbering: bool = True,
) -> list[ProcessingResult]:
    """Run the pipeline for selected ND2 files."""

    results: list[ProcessingResult] = []
    next_index = 1
    for path in paths:
        if continuous_crop_numbering:
            result = process_nd2_file(
                path,
                output_dir,
                config=config,
                crop_output_dir=output_dir,
                crop_start_index=next_index,
                crop_stem="section",
                crop_filename_template="{stem}{index:03d}.{extension}",
            )
        else:
            result = process_nd2_file(path, output_dir, config=config)
        results.append(result)
        next_index += len(result.crop_paths)
    return results


def _crop_output_image(raw_channels: np.ndarray, rgb_preview: np.ndarray, cfg: PipelineConfig) -> np.ndarray:
    if cfg.crop_output_mode == "rgb_direct":
        return _raw_channels_to_rgb(raw_channels, cfg.rgb_direct_channels)
    if cfg.crop_output_mode == "raw_stack":
        return raw_channels
    if cfg.crop_output_mode == "merged_rgb":
        return rgb_preview
    raise ValueError("crop_output_mode must be one of: 'rgb_direct', 'raw_stack', 'merged_rgb'.")


def _raw_channels_to_rgb(
    image: np.ndarray,
    rgb_channels: Sequence[int | None] = (2, 1, 0),
) -> np.ndarray:
    if len(rgb_channels) != 3:
        raise ValueError("rgb_direct_channels must contain exactly 3 channel indices for R, G, and B.")

    array = np.asarray(image)
    if array.ndim != 3 or array.shape[0] > 8:
        raise ValueError("rgb_direct crop output requires channel-first image data.")

    rgb = np.zeros(array.shape[1:] + (3,), dtype=array.dtype)
    for rgb_index, channel_index in enumerate(rgb_channels):
        if channel_index is None:
            continue
        if channel_index < 0 or channel_index >= array.shape[0]:
            raise ValueError(f"rgb_direct channel index {channel_index} is outside the available channel range.")
        rgb[..., rgb_index] = array[channel_index]
    return rgb


def _save_rgb_direct_crops(
    raw_channels: np.ndarray,
    boxes: list[CropBox],
    output_dir: str | Path,
    *,
    stem: str,
    extension: str,
    start_index: int,
    filename_template: str,
    rgb_channels: Sequence[int | None],
) -> list[Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, box in enumerate(boxes, start=start_index):
        y_slice, x_slice = box.as_slices()
        crop = np.asarray(raw_channels)[..., y_slice, x_slice]
        rgb_crop = _raw_channels_to_rgb(crop, rgb_channels)
        filename = filename_template.format(stem=stem, index=index, extension=extension)
        path = out_dir / filename
        imwrite(path, rgb_crop)
        paths.append(path)
    return paths


def _preview_source_image(image: np.ndarray, preview_max_dim: int | None) -> np.ndarray:
    if preview_max_dim is None or preview_max_dim <= 0:
        return image

    array = np.asarray(image)
    if array.ndim == 2:
        height, width = array.shape
    elif array.ndim == 3 and array.shape[0] <= 8:
        height, width = array.shape[1:]
    elif array.ndim == 3 and array.shape[-1] <= 8:
        height, width = array.shape[:2]
    else:
        return image

    max_dim = max(height, width)
    if max_dim <= preview_max_dim:
        return image

    step = int(np.ceil(max_dim / float(preview_max_dim)))
    if array.ndim == 2:
        return array[::step, ::step]
    if array.shape[0] <= 8:
        return array[:, ::step, ::step]
    return array[::step, ::step, :]


def _save_overlay(
    rgb: np.ndarray,
    boxes: list[CropBox],
    output_path: Path,
    *,
    source_shape: tuple[int, int] | None = None,
) -> None:
    image = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(image)
    if source_shape is None:
        scale_y = 1.0
        scale_x = 1.0
    else:
        scale_y = rgb.shape[0] / max(1.0, float(source_shape[0]))
        scale_x = rgb.shape[1] / max(1.0, float(source_shape[1]))
    for index, box in enumerate(boxes, start=1):
        x0 = int(round(box.x0 * scale_x))
        x1 = int(round(box.x1 * scale_x))
        y0 = int(round(box.y0 * scale_y))
        y1 = int(round(box.y1 * scale_y))
        line_width = max(1, int(round(4 * max(scale_x, scale_y))))
        draw.rectangle((x0, y0, x1, y1), outline=(255, 64, 64), width=line_width)
        draw.text((x0 + 8, y0 + 8), str(index), fill=(255, 255, 0))
    image.save(output_path)


def _write_manifest(
    path: Path,
    input_path: Path,
    crop_paths: list[Path],
    boxes: list[CropBox],
    *,
    start_index: int = 1,
) -> None:
    rows = []
    for index, (crop_path, box) in enumerate(zip(crop_paths, boxes), start=start_index):
        rows.append(
            {
                "input_path": str(input_path),
                "crop_path": str(crop_path),
                **box.to_dict(index=index),
            }
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("input_path,crop_path,section_index,label,y0,y1,x0,x1,height,width,area,centroid_y,centroid_x\n")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
