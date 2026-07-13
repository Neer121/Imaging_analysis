"""Preparation helpers for BrainGlobe atlas registration workflows."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from tifffile import imread, imwrite

from .pipeline import PipelineConfig, ProcessingResult, process_nd2_file


@dataclass(frozen=True)
class BrainGlobeExportConfig:
    """Configuration for exporting isolated sections for BrainGlobe workflows."""

    sample_id: str = "sample"
    atlas_name: str = "whs_sd_rat_39um"
    orientation: str | None = None
    registration_channel: int = 0
    signal_channels: Sequence[int] | None = None
    section_thickness_um: float | None = None
    section_interval_um: float | None = None
    start_z_um: float = 0.0
    pixel_size_x_um: float | None = None
    pixel_size_y_um: float | None = None
    include_in_stack: bool = True
    default_qc_status: str = "pending"
    default_qc_notes: str = ""
    capture_atlas_metadata: bool = True


@dataclass(frozen=True)
class BrainGlobeExportResult:
    """Paths produced by a BrainGlobe-preparation export run."""

    sample_dir: Path
    manifest_path: Path
    metadata_path: Path
    sections_rgb_dir: Path
    sections_registration_dir: Path
    sections_channels_dir: Path
    qc_dir: Path
    processing_results: list[ProcessingResult]


def export_sections_for_brainglobe(
    paths: Sequence[str | Path],
    output_dir: str | Path,
    *,
    pipeline_config: PipelineConfig | None = None,
    export_config: BrainGlobeExportConfig | None = None,
) -> BrainGlobeExportResult:
    """Run section isolation and export a BrainGlobe-ready sample layout."""

    if not paths:
        raise ValueError("At least one ND2 path is required for BrainGlobe export.")

    export_cfg = export_config or BrainGlobeExportConfig()
    sample_dir = Path(output_dir) / export_cfg.sample_id
    sections_rgb_dir = sample_dir / "sections_rgb"
    sections_registration_dir = sample_dir / "sections_registration"
    sections_channels_dir = sample_dir / "sections_channels"
    qc_dir = sample_dir / "qc" / "slide_crop_overlays"
    slide_outputs_dir = sample_dir / "slide_outputs"
    manifest_path = sample_dir / "section_manifest.csv"
    metadata_path = sample_dir / "sample_metadata.json"

    for directory in (
        sections_rgb_dir,
        sections_registration_dir,
        sections_channels_dir,
        qc_dir,
        slide_outputs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    pipeline_cfg = replace(pipeline_config or PipelineConfig(), save_raw_channel_crops=True)
    processing_results: list[ProcessingResult] = []
    manifest_rows: list[dict[str, Any]] = []
    next_index = 1

    for slide_number, path in enumerate(paths, start=1):
        result = process_nd2_file(
            path,
            slide_outputs_dir,
            config=pipeline_cfg,
            crop_output_dir=sections_rgb_dir,
            crop_start_index=next_index,
            crop_stem="section",
            crop_filename_template="{stem}{index:03d}.{extension}",
        )
        processing_results.append(result)
        overlay_target = qc_dir / result.overlay_path.name
        if overlay_target.resolve() != result.overlay_path.resolve():
            shutil.copy2(result.overlay_path, overlay_target)

        manifest_rows.extend(
            _build_manifest_rows(
                result,
                global_start_index=next_index,
                slide_number=slide_number,
                sections_channels_dir=sections_channels_dir,
                sections_registration_dir=sections_registration_dir,
                export_config=export_cfg,
            )
        )
        next_index += len(result.crop_paths)

    _write_manifest(manifest_path, manifest_rows)
    _write_json(
        metadata_path,
        {
            "sample_id": export_cfg.sample_id,
            "atlas_name": export_cfg.atlas_name,
            "atlas_metadata": _capture_atlas_metadata(export_cfg.atlas_name) if export_cfg.capture_atlas_metadata else None,
            "orientation": export_cfg.orientation,
            "pipeline_config": asdict(pipeline_cfg),
            "export_config": asdict(export_cfg),
            "source_paths": [str(Path(path)) for path in paths],
            "slide_outputs": [str(result.output_dir) for result in processing_results],
        },
    )

    return BrainGlobeExportResult(
        sample_dir=sample_dir,
        manifest_path=manifest_path,
        metadata_path=metadata_path,
        sections_rgb_dir=sections_rgb_dir,
        sections_registration_dir=sections_registration_dir,
        sections_channels_dir=sections_channels_dir,
        qc_dir=qc_dir,
        processing_results=processing_results,
    )


def _build_manifest_rows(
    result: ProcessingResult,
    *,
    global_start_index: int,
    slide_number: int,
    sections_channels_dir: Path,
    sections_registration_dir: Path,
    export_config: BrainGlobeExportConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for offset, (box, rgb_path, raw_path) in enumerate(zip(result.boxes, result.crop_paths, result.raw_crop_paths)):
        section_index = global_start_index + offset
        raw_crop = imread(raw_path)
        channel_count = int(raw_crop.shape[0]) if raw_crop.ndim == 3 else 1
        registration_channel = export_config.registration_channel
        if registration_channel < 0 or registration_channel >= channel_count:
            raise ValueError(
                f"registration_channel={registration_channel} is outside the available range 0..{channel_count - 1}."
            )

        exported_channels = _resolve_signal_channels(export_config.signal_channels, channel_count)
        channel_paths = _write_channel_exports(
            raw_crop,
            section_index=section_index,
            sections_channels_dir=sections_channels_dir,
            channels=exported_channels,
        )
        registration_path = sections_registration_dir / f"section{section_index:03d}.tif"
        imwrite(registration_path, raw_crop[registration_channel] if raw_crop.ndim == 3 else raw_crop)

        pixel_size = _pixel_size_um(result, export_config)
        z_position_um = _z_position_um(section_index, export_config)
        rows.append(
            {
                "sample_id": export_config.sample_id,
                "atlas_name": export_config.atlas_name,
                "orientation": export_config.orientation,
                "source_file": str(result.input_path),
                "slide_number": slide_number,
                "slide_id": result.input_path.stem,
                "section_index": section_index,
                "slide_section_label": box.label,
                "crop_path_rgb": str(rgb_path),
                "crop_path_registration": str(registration_path),
                "raw_crop_path": str(raw_path),
                "channel_count": channel_count,
                "channel_paths": json.dumps(channel_paths),
                "registration_channel": registration_channel,
                "pixel_size_x_um": pixel_size["x"],
                "pixel_size_y_um": pixel_size["y"],
                "section_thickness_um": export_config.section_thickness_um,
                "section_interval_um": export_config.section_interval_um,
                "z_position_um": z_position_um,
                "include_in_stack": export_config.include_in_stack,
                "qc_status": export_config.default_qc_status,
                "qc_notes": export_config.default_qc_notes,
                **box.to_dict(),
            }
        )
    return rows


def _resolve_signal_channels(signal_channels: Sequence[int] | None, channel_count: int) -> list[int]:
    if signal_channels is None:
        return list(range(channel_count))

    resolved = sorted(set(int(channel) for channel in signal_channels))
    invalid = [channel for channel in resolved if channel < 0 or channel >= channel_count]
    if invalid:
        raise ValueError(f"signal_channels contains out-of-range channels: {invalid}")
    return resolved


def _write_channel_exports(
    raw_crop: Any,
    *,
    section_index: int,
    sections_channels_dir: Path,
    channels: Sequence[int],
) -> dict[str, str]:
    array = raw_crop
    if getattr(array, "ndim", 0) != 3:
        raise ValueError("Expected raw channel crops to be saved as channel-first 3D arrays.")

    exported: dict[str, str] = {}
    for channel in channels:
        channel_dir = sections_channels_dir / f"ch{channel}"
        channel_dir.mkdir(parents=True, exist_ok=True)
        channel_path = channel_dir / f"section{section_index:03d}.tif"
        imwrite(channel_path, array[channel])
        exported[f"ch{channel}"] = str(channel_path)
    return exported


def _pixel_size_um(result: ProcessingResult, export_config: BrainGlobeExportConfig) -> dict[str, float | None]:
    voxel = result_metadata_value(result, "voxel_size_um") or {}
    return {
        "x": export_config.pixel_size_x_um if export_config.pixel_size_x_um is not None else voxel.get("x"),
        "y": export_config.pixel_size_y_um if export_config.pixel_size_y_um is not None else voxel.get("y"),
    }


def _z_position_um(section_index: int, export_config: BrainGlobeExportConfig) -> float | None:
    if export_config.section_interval_um is None:
        return None
    return export_config.start_z_um + (section_index - 1) * export_config.section_interval_um


def result_metadata_value(result: ProcessingResult, key: str) -> Any:
    if not result.metadata_path.exists():
        return None
    with result.metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    nd2_metadata = metadata.get("nd2", {})
    return nd2_metadata.get(key)


def _capture_atlas_metadata(atlas_name: str) -> dict[str, Any] | None:
    try:
        from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas
    except ImportError:
        return None

    try:
        atlas = BrainGlobeAtlas(atlas_name)
    except Exception:
        return None

    return {
        "name": atlas_name,
        "resolution_um": list(getattr(atlas, "resolution", [])),
        "shape": list(getattr(atlas, "shape", [])),
        "orientation": getattr(atlas, "orientation", None),
    }


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write(
                "sample_id,atlas_name,orientation,source_file,slide_number,slide_id,section_index,"
                "slide_section_label,crop_path_rgb,crop_path_registration,raw_crop_path,channel_count,"
                "channel_paths,registration_channel,pixel_size_x_um,pixel_size_y_um,section_thickness_um,"
                "section_interval_um,z_position_um,include_in_stack,qc_status,qc_notes,label,y0,y1,x0,x1,"
                "height,width,area,centroid_y,centroid_x\n"
            )
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
