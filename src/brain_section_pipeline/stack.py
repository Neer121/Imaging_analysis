"""Build ordered TIFF stacks from BrainGlobe-preparation exports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from tifffile import imread, imwrite


PlacementMode = Literal["center", "original_coords"]
SourceKind = Literal["registration", "rgb", "channel"]


@dataclass(frozen=True)
class StackBuildConfig:
    """Configuration for building a 3D stack from a section manifest."""

    sample_id: str | None = None
    source_kind: SourceKind = "registration"
    channel: int | None = None
    placement_mode: PlacementMode = "center"
    allowed_qc_statuses: tuple[str, ...] | None = None
    require_include_in_stack: bool = True
    fill_value: float = 0.0
    output_dtype: str | None = None
    output_name: str | None = None


@dataclass(frozen=True)
class StackBuildResult:
    """Paths and metadata produced by a stack build."""

    stack_path: Path
    metadata_path: Path
    section_indices: list[int]
    stack_shape: tuple[int, int, int]
    voxel_size_um: dict[str, float | None]


def build_stack_from_manifest(
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    config: StackBuildConfig | None = None,
) -> StackBuildResult:
    """Build an ordered 3D TIFF stack from a BrainGlobe section manifest."""

    manifest = Path(manifest_path)
    rows = _selected_rows(_read_manifest_rows(manifest), config or StackBuildConfig())
    if not rows:
        raise ValueError("No manifest rows were selected for stack construction.")

    cfg = config or StackBuildConfig()
    stack_output_dir = Path(output_dir) if output_dir is not None else manifest.parent / "stacks"
    stack_output_dir.mkdir(parents=True, exist_ok=True)

    sections = [_load_section(row, cfg) for row in rows]
    section_arrays = [section["image"] for section in sections]
    dtype = np.dtype(cfg.output_dtype) if cfg.output_dtype is not None else np.result_type(*section_arrays)
    canvas_shape = _canvas_shape(rows, section_arrays, cfg.placement_mode)
    stack = np.full((len(section_arrays), canvas_shape[0], canvas_shape[1]), cfg.fill_value, dtype=dtype)

    for z_index, (row, section) in enumerate(zip(rows, sections)):
        placed = _place_section(
            section["image"].astype(dtype, copy=False),
            row=row,
            canvas_shape=canvas_shape,
            placement_mode=cfg.placement_mode,
            fill_value=cfg.fill_value,
        )
        stack[z_index] = placed

    stack_name = cfg.output_name or _default_stack_name(rows, cfg)
    stack_path = stack_output_dir / stack_name
    metadata_path = stack_output_dir / f"{Path(stack_name).stem}.json"
    # Plain TIFF axes metadata preserves a singleton Z dimension on round-trip
    # reads, while ImageJ mode squeezes `(1, Y, X)` stacks back to 2D.
    imwrite(stack_path, stack, metadata={"axes": "ZYX"})

    voxel_size_um = _voxel_size_um(rows)
    metadata = {
        "manifest_path": str(manifest),
        "output_stack_path": str(stack_path),
        "sample_id": cfg.sample_id or rows[0].get("sample_id"),
        "source_kind": cfg.source_kind,
        "channel": cfg.channel,
        "placement_mode": cfg.placement_mode,
        "section_indices": [int(row["section_index"]) for row in rows],
        "canvas_shape_yx": list(canvas_shape),
        "stack_shape_zyx": list(stack.shape),
        "voxel_size_um": voxel_size_um,
        "allowed_qc_statuses": list(cfg.allowed_qc_statuses) if cfg.allowed_qc_statuses is not None else None,
        "require_include_in_stack": cfg.require_include_in_stack,
        "rows": [_metadata_row(row) for row in rows],
        "config": asdict(cfg),
    }
    _write_json(metadata_path, metadata)

    return StackBuildResult(
        stack_path=stack_path,
        metadata_path=metadata_path,
        section_indices=metadata["section_indices"],
        stack_shape=tuple(int(value) for value in stack.shape),
        voxel_size_um=voxel_size_um,
    )


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _selected_rows(rows: list[dict[str, str]], cfg: StackBuildConfig) -> list[dict[str, str]]:
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


def _load_section(row: dict[str, str], cfg: StackBuildConfig) -> dict[str, Any]:
    image_path = _source_path(row, cfg)
    image = np.asarray(imread(image_path))
    if image.ndim == 3 and cfg.source_kind == "rgb" and image.shape[-1] in (3, 4):
        image = image[..., :3].max(axis=-1)
    if image.ndim != 2:
        raise ValueError(f"Expected a 2D section image for stack building, got shape {image.shape} from {image_path}.")
    return {"path": image_path, "image": image}


def _source_path(row: dict[str, str], cfg: StackBuildConfig) -> Path:
    if cfg.source_kind == "registration":
        return Path(row["crop_path_registration"])
    if cfg.source_kind == "rgb":
        return Path(row["crop_path_rgb"])
    if cfg.source_kind == "channel":
        if cfg.channel is None:
            raise ValueError("StackBuildConfig.channel is required when source_kind='channel'.")
        channel_paths = json.loads(row["channel_paths"])
        key = f"ch{cfg.channel}"
        if key not in channel_paths:
            raise ValueError(f"Manifest row does not contain a path for {key}.")
        return Path(channel_paths[key])
    raise ValueError("source_kind must be one of: 'registration', 'rgb', 'channel'.")


def _canvas_shape(
    rows: list[dict[str, str]],
    section_arrays: list[np.ndarray],
    placement_mode: PlacementMode,
) -> tuple[int, int]:
    if placement_mode == "center":
        return (
            max(int(array.shape[0]) for array in section_arrays),
            max(int(array.shape[1]) for array in section_arrays),
        )
    if placement_mode == "original_coords":
        return (
            max(int(row["y1"]) for row in rows),
            max(int(row["x1"]) for row in rows),
        )
    raise ValueError("placement_mode must be 'center' or 'original_coords'.")


def _place_section(
    image: np.ndarray,
    *,
    row: dict[str, str],
    canvas_shape: tuple[int, int],
    placement_mode: PlacementMode,
    fill_value: float,
) -> np.ndarray:
    canvas = np.full(canvas_shape, fill_value, dtype=image.dtype)
    if placement_mode == "center":
        top = (canvas_shape[0] - image.shape[0]) // 2
        left = (canvas_shape[1] - image.shape[1]) // 2
    elif placement_mode == "original_coords":
        top = int(row["y0"])
        left = int(row["x0"])
    else:
        raise ValueError("placement_mode must be 'center' or 'original_coords'.")

    bottom = top + image.shape[0]
    right = left + image.shape[1]
    if top < 0 or left < 0 or bottom > canvas_shape[0] or right > canvas_shape[1]:
        raise ValueError("Section placement exceeded the target canvas bounds.")
    canvas[top:bottom, left:right] = image
    return canvas


def _default_stack_name(rows: list[dict[str, str]], cfg: StackBuildConfig) -> str:
    sample_id = cfg.sample_id or rows[0].get("sample_id") or "sample"
    suffix = cfg.source_kind if cfg.source_kind != "channel" else f"channel{cfg.channel}"
    return f"{sample_id}_{suffix}_stack.tif"


def _voxel_size_um(rows: list[dict[str, str]]) -> dict[str, float | None]:
    first = rows[0]
    return {
        "z": _parse_optional_float(first.get("section_interval_um")) or _parse_optional_float(first.get("section_thickness_um")),
        "y": _parse_optional_float(first.get("pixel_size_y_um")),
        "x": _parse_optional_float(first.get("pixel_size_x_um")),
    }


def _metadata_row(row: dict[str, str]) -> dict[str, Any]:
    return {
        "section_index": int(row["section_index"]),
        "source_file": row.get("source_file"),
        "slide_id": row.get("slide_id"),
        "crop_path_registration": row.get("crop_path_registration"),
        "crop_path_rgb": row.get("crop_path_rgb"),
        "z_position_um": _parse_optional_float(row.get("z_position_um")),
        "include_in_stack": _parse_bool(row.get("include_in_stack", "true")),
        "qc_status": row.get("qc_status"),
    }


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return float(text)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
