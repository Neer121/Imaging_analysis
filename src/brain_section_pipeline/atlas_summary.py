"""Summarize registered slice intensities by atlas region."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from tifffile import imread


@dataclass(frozen=True)
class AtlasSummaryConfig:
    """Configuration for region-level summaries from registered slices."""

    image_path_field: str = "warped_section_path"
    annotation_path_field: str = "atlas_annotation_path"
    include_background: bool = False
    min_region_pixels: int = 1
    include_structure_metadata: bool = True
    per_section_output_name: str = "atlas_region_summary.csv"
    aggregate_output_name: str = "atlas_region_aggregate.csv"
    metadata_name: str = "atlas_region_summary.json"


@dataclass(frozen=True)
class AtlasSummaryResult:
    """Artifacts produced while summarizing registered slices by atlas region."""

    output_dir: Path
    per_section_summary_path: Path
    aggregate_summary_path: Path
    metadata_path: Path
    section_count: int
    region_row_count: int


def summarize_registered_slices_by_region(
    registration_manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    config: AtlasSummaryConfig | None = None,
) -> AtlasSummaryResult:
    """Summarize registered slice intensities by atlas annotation region."""

    cfg = config or AtlasSummaryConfig()
    manifest = Path(registration_manifest_path)
    rows = _read_manifest_rows(manifest)
    if not rows:
        raise ValueError("The registration manifest is empty.")

    summary_dir = Path(output_dir) if output_dir is not None else manifest.parent / "atlas_summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    atlas_name = _first_nonempty(rows, "atlas_name")
    structure_lookup = _load_structure_lookup(atlas_name) if cfg.include_structure_metadata else {}
    per_section_rows: list[dict[str, Any]] = []
    aggregate: dict[int, dict[str, Any]] = {}

    for row in rows:
        section_index = int(row["section_index"])
        atlas_slice_index = _optional_int(row.get("atlas_slice_index"))
        section_image = _grayscale_image(Path(row[cfg.image_path_field]))
        annotation = np.asarray(imread(row[cfg.annotation_path_field]))
        if section_image.shape != annotation.shape:
            raise ValueError(
                f"Registered image shape {section_image.shape} does not match annotation shape {annotation.shape} "
                f"for section {section_index}."
            )

        valid_mask = np.isfinite(section_image)
        for region_id in sorted(int(value) for value in np.unique(annotation)):
            if region_id == 0 and not cfg.include_background:
                continue
            region_mask = (annotation == region_id) & valid_mask
            pixel_count = int(region_mask.sum())
            if pixel_count < cfg.min_region_pixels:
                continue

            values = np.asarray(section_image[region_mask], dtype=np.float32)
            region_info = structure_lookup.get(region_id, {})
            summary_row = {
                "section_index": section_index,
                "atlas_slice_index": atlas_slice_index,
                "region_id": region_id,
                "region_acronym": region_info.get("acronym"),
                "region_name": region_info.get("name"),
                "region_pixel_count": pixel_count,
                "nonzero_pixel_count": int(np.count_nonzero(values)),
                "intensity_sum": float(values.sum()),
                "intensity_mean": float(values.mean()),
                "intensity_min": float(values.min()),
                "intensity_max": float(values.max()),
            }
            per_section_rows.append(summary_row)
            _accumulate_aggregate(aggregate, summary_row)

    aggregate_rows = _finalize_aggregate_rows(aggregate)
    per_section_path = summary_dir / cfg.per_section_output_name
    aggregate_path = summary_dir / cfg.aggregate_output_name
    metadata_path = summary_dir / cfg.metadata_name

    _write_csv(per_section_path, per_section_rows)
    _write_csv(aggregate_path, aggregate_rows)
    _write_json(
        metadata_path,
        {
            "input_manifest_path": str(manifest),
            "atlas_name": atlas_name,
            "structure_metadata_attached": bool(structure_lookup),
            "section_count": len({int(row["section_index"]) for row in rows}),
            "region_row_count": len(per_section_rows),
            "aggregate_region_count": len(aggregate_rows),
            "config": asdict(cfg),
        },
    )

    return AtlasSummaryResult(
        output_dir=summary_dir,
        per_section_summary_path=per_section_path,
        aggregate_summary_path=aggregate_path,
        metadata_path=metadata_path,
        section_count=len({int(row["section_index"]) for row in rows}),
        region_row_count=len(per_section_rows),
    )


def _accumulate_aggregate(aggregate: dict[int, dict[str, Any]], row: dict[str, Any]) -> None:
    region_id = int(row["region_id"])
    current = aggregate.get(region_id)
    if current is None:
        aggregate[region_id] = {
            "region_id": region_id,
            "region_acronym": row.get("region_acronym"),
            "region_name": row.get("region_name"),
            "section_count": 1,
            "region_pixel_count": int(row["region_pixel_count"]),
            "nonzero_pixel_count": int(row["nonzero_pixel_count"]),
            "intensity_sum": float(row["intensity_sum"]),
            "intensity_min": float(row["intensity_min"]),
            "intensity_max": float(row["intensity_max"]),
        }
        return

    current["section_count"] = int(current["section_count"]) + 1
    current["region_pixel_count"] = int(current["region_pixel_count"]) + int(row["region_pixel_count"])
    current["nonzero_pixel_count"] = int(current["nonzero_pixel_count"]) + int(row["nonzero_pixel_count"])
    current["intensity_sum"] = float(current["intensity_sum"]) + float(row["intensity_sum"])
    current["intensity_min"] = min(float(current["intensity_min"]), float(row["intensity_min"]))
    current["intensity_max"] = max(float(current["intensity_max"]), float(row["intensity_max"]))
    if not current.get("region_acronym") and row.get("region_acronym"):
        current["region_acronym"] = row.get("region_acronym")
    if not current.get("region_name") and row.get("region_name"):
        current["region_name"] = row.get("region_name")


def _finalize_aggregate_rows(aggregate: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region_id in sorted(aggregate):
        row = dict(aggregate[region_id])
        pixel_count = max(1, int(row["region_pixel_count"]))
        row["intensity_mean"] = float(row["intensity_sum"]) / pixel_count
        rows.append(row)
    return rows


def _load_structure_lookup(atlas_name: str | None) -> dict[int, dict[str, str | None]]:
    if atlas_name is None:
        return {}
    try:
        from brainglobe_atlasapi.bg_atlas import BrainGlobeAtlas
    except ImportError:
        return {}

    try:
        atlas = BrainGlobeAtlas(atlas_name)
        lookup_df = getattr(atlas, "lookup_df", None)
    except Exception:
        return {}
    if lookup_df is None:
        return {}

    records: list[dict[str, Any]]
    if hasattr(lookup_df, "to_dict"):
        try:
            records = list(lookup_df.to_dict(orient="records"))
        except Exception:
            return {}
    else:
        return {}

    result: dict[int, dict[str, str | None]] = {}
    for record in records:
        region_id = record.get("id")
        if region_id is None:
            continue
        try:
            key = int(region_id)
        except (TypeError, ValueError):
            continue
        result[key] = {
            "acronym": _optional_text(record.get("acronym")),
            "name": _optional_text(record.get("name")),
        }
    return result


def _grayscale_image(path: Path) -> np.ndarray:
    image = np.asarray(imread(path))
    if image.ndim == 2:
        return image.astype(np.float32)
    if image.ndim == 3 and image.shape[-1] in (3, 4):
        return image[..., :3].max(axis=-1).astype(np.float32)
    if image.ndim == 3 and image.shape[0] <= 8:
        return image.max(axis=0).astype(np.float32)
    raise ValueError(f"Could not convert image with shape {image.shape} to grayscale.")


def _first_nonempty(rows: list[dict[str, str]], key: str) -> str | None:
    for row in rows:
        value = _optional_text(row.get(key))
        if value is not None:
            return value
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    text = _optional_text(value)
    if text is None:
        return None
    return int(text)


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not rows:
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
