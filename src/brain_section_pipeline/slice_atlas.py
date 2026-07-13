"""Prepare slice-wise atlas inputs for sparse BrainGlobe workflows."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from tifffile import imread, imwrite


SectionSource = Literal["registration", "rgb", "channel"]
AxisName = Literal["ap", "si", "dv", "rl", "ml"]


@dataclass(frozen=True)
class SliceAtlasConfig:
    """Configuration for pairing sections with BrainGlobe atlas planes."""

    atlas_name: str = "whs_sd_rat_39um"
    anatomical_axis: AxisName = "ap"
    section_source: SectionSource = "registration"
    channel: int | None = None
    start_slice_index: int = 0
    slice_index_step: int = 1
    sample_id: str | None = None
    allowed_qc_statuses: tuple[str, ...] | None = None
    require_include_in_stack: bool = True
    output_name: str = "slice_atlas_manifest.csv"
    metadata_name: str = "slice_atlas_metadata.json"


@dataclass(frozen=True)
class SliceAtlasResult:
    """Artifacts produced while preparing slice-wise atlas inputs."""

    output_dir: Path
    manifest_path: Path
    metadata_path: Path
    atlas_reference_dir: Path
    atlas_annotation_dir: Path
    section_source_dir: Path
    section_indices: list[int]


def prepare_slice_atlas_inputs(
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    config: SliceAtlasConfig | None = None,
) -> SliceAtlasResult:
    """Export atlas planes per section for sparse slice-wise workflows."""

    cfg = config or SliceAtlasConfig()
    manifest = Path(manifest_path)
    rows = _selected_rows(_read_manifest_rows(manifest), cfg)
    if not rows:
        raise ValueError("No section rows were selected for slice-wise atlas preparation.")

    atlas = _load_atlas(cfg.atlas_name)
    atlas_reference = np.asarray(atlas.reference)
    atlas_annotation = np.asarray(atlas.annotation)
    atlas_orientation = str(getattr(atlas, "orientation", "")).lower()
    atlas_resolution = list(getattr(atlas, "resolution", []))
    slice_axis = _axis_index_from_orientation(atlas_orientation, cfg.anatomical_axis)

    target_dir = Path(output_dir) if output_dir is not None else manifest.parent / "slice_atlas"
    atlas_reference_dir = target_dir / "atlas_reference"
    atlas_annotation_dir = target_dir / "atlas_annotation"
    section_source_dir = target_dir / "sections"
    atlas_reference_dir.mkdir(parents=True, exist_ok=True)
    atlas_annotation_dir.mkdir(parents=True, exist_ok=True)
    section_source_dir.mkdir(parents=True, exist_ok=True)

    pairing_rows: list[dict[str, Any]] = []
    selected_indices: list[int] = []
    for ordinal, row in enumerate(rows):
        section_index = int(row["section_index"])
        atlas_slice_index = _slice_index_for_row(row, ordinal, cfg, atlas_reference.shape[slice_axis])
        reference_slice = _extract_slice(atlas_reference, slice_axis, atlas_slice_index)
        annotation_slice = _extract_slice(atlas_annotation, slice_axis, atlas_slice_index)
        section_path = _section_source_path(row, cfg)

        reference_path = atlas_reference_dir / f"section{section_index:03d}_atlas_reference.tif"
        annotation_path = atlas_annotation_dir / f"section{section_index:03d}_atlas_annotation.tif"
        section_copy_path = section_source_dir / f"section{section_index:03d}_section.tif"
        imwrite(reference_path, reference_slice)
        imwrite(annotation_path, annotation_slice)
        _copy_section_image(section_path, section_copy_path)

        pairing_rows.append(
            {
                **row,
                "atlas_name": cfg.atlas_name,
                "atlas_orientation": atlas_orientation,
                "atlas_axis_name": cfg.anatomical_axis,
                "atlas_axis_index": slice_axis,
                "atlas_slice_index": atlas_slice_index,
                "atlas_reference_path": str(reference_path),
                "atlas_annotation_path": str(annotation_path),
                "section_source_kind": cfg.section_source,
                "section_source_path": str(section_copy_path),
            }
        )
        selected_indices.append(section_index)

    pairing_manifest_path = target_dir / cfg.output_name
    metadata_path = target_dir / cfg.metadata_name
    _write_manifest(pairing_manifest_path, pairing_rows)
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
            "section_indices": selected_indices,
            "config": asdict(cfg),
        },
    )

    return SliceAtlasResult(
        output_dir=target_dir,
        manifest_path=pairing_manifest_path,
        metadata_path=metadata_path,
        atlas_reference_dir=atlas_reference_dir,
        atlas_annotation_dir=atlas_annotation_dir,
        section_source_dir=section_source_dir,
        section_indices=selected_indices,
    )


def _selected_rows(rows: list[dict[str, str]], cfg: SliceAtlasConfig) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    allowed_statuses = {value.strip().lower() for value in cfg.allowed_qc_statuses} if cfg.allowed_qc_statuses else None
    for row in rows:
        if cfg.sample_id and row.get("sample_id") != cfg.sample_id:
            continue
        if cfg.require_include_in_stack and not _parse_bool(row.get("include_in_stack", "true")):
            continue
        if allowed_statuses is not None:
            status = (row.get("qc_status") or "").strip().lower()
            if status not in allowed_statuses:
                continue
        filtered.append(row)
    return sorted(filtered, key=lambda row: int(row["section_index"]))


def _load_atlas(atlas_name: str):
    try:
        from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas
    except ImportError as exc:
        raise ImportError(
            "brainglobe-atlasapi is required for slice-wise atlas preparation."
        ) from exc
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


def _slice_index_for_row(
    row: dict[str, str],
    ordinal: int,
    cfg: SliceAtlasConfig,
    axis_length: int,
) -> int:
    explicit_value = row.get("atlas_slice_index")
    if explicit_value is not None and explicit_value.strip():
        index = int(explicit_value)
    else:
        index = cfg.start_slice_index + ordinal * cfg.slice_index_step
    if index < 0 or index >= axis_length:
        raise ValueError(f"Atlas slice index {index} is outside the available range 0..{axis_length - 1}.")
    return index


def _extract_slice(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    return np.take(volume, index, axis=axis)


def _section_source_path(row: dict[str, str], cfg: SliceAtlasConfig) -> Path:
    if cfg.section_source == "registration":
        return Path(row["crop_path_registration"])
    if cfg.section_source == "rgb":
        return Path(row["crop_path_rgb"])
    if cfg.section_source == "channel":
        if cfg.channel is None:
            raise ValueError("SliceAtlasConfig.channel is required when section_source='channel'.")
        channel_paths = json.loads(row["channel_paths"])
        key = f"ch{cfg.channel}"
        if key not in channel_paths:
            raise ValueError(f"Manifest row does not contain a path for {key}.")
        return Path(channel_paths[key])
    raise ValueError("section_source must be one of: 'registration', 'rgb', 'channel'.")


def _copy_section_image(source_path: Path, target_path: Path) -> None:
    image = np.asarray(imread(source_path))
    imwrite(target_path, image)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not rows:
            handle.write("section_index,atlas_slice_index,atlas_reference_path,atlas_annotation_path,section_source_path\n")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
