"""Prepare and optionally run brainreg from exported stack metadata."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np
from tifffile import imread, imwrite

from .stack import StackBuildConfig, build_stack_from_manifest


BrainGeometry = Literal["full", "hemisphere_l", "hemisphere_r"]
PreProcessing = Literal["default", "skip"]


@dataclass(frozen=True)
class BrainRegConfig:
    """Configuration for preparing a brainreg command and inputs."""

    atlas_name: str | None = None
    orientation: str | None = None
    additional_channels: tuple[int, ...] = ()
    sort_input_file: bool = False
    n_free_cpus: int | None = None
    backend: str | None = None
    debug: bool = False
    save_original_orientation: bool = False
    brain_geometry: BrainGeometry = "full"
    pre_processing: PreProcessing = "default"
    output_name: str = "brainreg_output"
    prepared_input_name: str = "brainreg_input"
    command_name: str = "run_brainreg.ps1"
    metadata_name: str = "brainreg_preparation.json"


@dataclass(frozen=True)
class BrainRegPreparationResult:
    """Artifacts produced while preparing a brainreg run."""

    prepared_dir: Path
    registration_input_dir: Path
    additional_input_dirs: list[Path]
    brainreg_output_dir: Path
    command: list[str]
    command_script_path: Path
    metadata_path: Path
    stack_metadata_path: Path
    manifest_path: Path


def prepare_brainreg_run(
    stack_metadata_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    manifest_path: str | Path | None = None,
    config: BrainRegConfig | None = None,
) -> BrainRegPreparationResult:
    """Prepare brainreg-compatible inputs and a ready-to-run command."""

    cfg = config or BrainRegConfig()
    stack_metadata = _read_json(Path(stack_metadata_path))
    manifest = Path(manifest_path) if manifest_path is not None else Path(stack_metadata["manifest_path"])
    rows = _read_manifest_rows(manifest)
    if not rows:
        raise ValueError("The section manifest is empty.")

    first_row = rows[0]
    atlas_name = cfg.atlas_name or _optional_text(first_row.get("atlas_name"))
    if atlas_name is None:
        raise ValueError("Atlas name is required. Provide it in BrainRegConfig or the section manifest.")

    orientation = cfg.orientation or _optional_text(first_row.get("orientation"))
    if orientation is None:
        raise ValueError("Orientation is required. Provide it in BrainRegConfig or the section manifest.")

    voxel_size = stack_metadata.get("voxel_size_um") or {}
    voxel_triplet = _voxel_triplet(voxel_size)

    stack_path = Path(stack_metadata["output_stack_path"])
    prepared_dir = Path(output_dir) if output_dir is not None else stack_path.parent / cfg.prepared_input_name
    registration_input_dir = prepared_dir / "registration"
    additional_root = prepared_dir / "additional"
    brainreg_output_dir = prepared_dir / cfg.output_name
    registration_input_dir.mkdir(parents=True, exist_ok=True)
    additional_root.mkdir(parents=True, exist_ok=True)
    brainreg_output_dir.mkdir(parents=True, exist_ok=True)

    registration_stack = np.asarray(imread(stack_path))
    _write_volume_as_slice_directory(registration_stack, registration_input_dir)

    stack_cfg = _stack_config_from_metadata(stack_metadata)
    additional_input_dirs: list[Path] = []
    for channel in cfg.additional_channels:
        additional_stack = build_stack_from_manifest(
            manifest,
            output_dir=prepared_dir,
            config=StackBuildConfig(
                sample_id=stack_cfg.sample_id,
                source_kind="channel",
                channel=channel,
                placement_mode=stack_cfg.placement_mode,
                allowed_qc_statuses=stack_cfg.allowed_qc_statuses,
                require_include_in_stack=stack_cfg.require_include_in_stack,
                fill_value=stack_cfg.fill_value,
                output_dtype=stack_cfg.output_dtype,
                output_name=f"{stack_path.stem}_channel{channel}.tif",
            ),
        )
        additional_dir = additional_root / f"ch{channel}"
        _reset_directory(additional_dir)
        additional_stack_array = np.asarray(imread(additional_stack.stack_path))
        _write_volume_as_slice_directory(additional_stack_array, additional_dir)
        additional_input_dirs.append(additional_dir)

    command = _build_brainreg_command(
        registration_input_dir=registration_input_dir,
        output_dir=brainreg_output_dir,
        voxel_triplet=voxel_triplet,
        orientation=orientation,
        atlas_name=atlas_name,
        additional_input_dirs=additional_input_dirs,
        config=cfg,
    )

    command_script_path = prepared_dir / cfg.command_name
    metadata_path = prepared_dir / cfg.metadata_name
    _write_command_script(command_script_path, command)
    _write_json(
        metadata_path,
        {
            "stack_metadata_path": str(Path(stack_metadata_path)),
            "manifest_path": str(manifest),
            "prepared_dir": str(prepared_dir),
            "registration_input_dir": str(registration_input_dir),
            "additional_input_dirs": [str(path) for path in additional_input_dirs],
            "brainreg_output_dir": str(brainreg_output_dir),
            "command_script_path": str(command_script_path),
            "atlas_name": atlas_name,
            "orientation": orientation,
            "voxel_size_um": {"z": voxel_triplet[0], "y": voxel_triplet[1], "x": voxel_triplet[2]},
            "command": command,
            "config": asdict(cfg),
        },
    )

    return BrainRegPreparationResult(
        prepared_dir=prepared_dir,
        registration_input_dir=registration_input_dir,
        additional_input_dirs=additional_input_dirs,
        brainreg_output_dir=brainreg_output_dir,
        command=command,
        command_script_path=command_script_path,
        metadata_path=metadata_path,
        stack_metadata_path=Path(stack_metadata_path),
        manifest_path=manifest,
    )


def run_prepared_brainreg(
    preparation: BrainRegPreparationResult | str | Path,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute a prepared brainreg command."""

    result = _load_preparation(preparation)
    return subprocess.run(result.command, check=check, text=True, capture_output=True)


def _load_preparation(preparation: BrainRegPreparationResult | str | Path) -> BrainRegPreparationResult:
    if isinstance(preparation, BrainRegPreparationResult):
        return preparation

    metadata = _read_json(Path(preparation))
    return BrainRegPreparationResult(
        prepared_dir=Path(metadata["prepared_dir"]),
        registration_input_dir=Path(metadata["registration_input_dir"]),
        additional_input_dirs=[Path(path) for path in metadata["additional_input_dirs"]],
        brainreg_output_dir=Path(metadata["brainreg_output_dir"]),
        command=list(metadata["command"]),
        command_script_path=Path(metadata["command_script_path"]),
        metadata_path=Path(preparation),
        stack_metadata_path=Path(metadata["stack_metadata_path"]),
        manifest_path=Path(metadata["manifest_path"]),
    )


def _build_brainreg_command(
    *,
    registration_input_dir: Path,
    output_dir: Path,
    voxel_triplet: tuple[float, float, float],
    orientation: str,
    atlas_name: str,
    additional_input_dirs: Sequence[Path],
    config: BrainRegConfig,
) -> list[str]:
    command = [
        "brainreg",
        str(registration_input_dir),
        str(output_dir),
        "-v",
        _format_float(voxel_triplet[0]),
        _format_float(voxel_triplet[1]),
        _format_float(voxel_triplet[2]),
        "--orientation",
        orientation,
        "--atlas",
        atlas_name,
    ]
    if additional_input_dirs:
        command.append("-a")
        command.extend(str(path) for path in additional_input_dirs)
    if config.sort_input_file:
        command.extend(["--sort-input-file", "true"])
    if config.n_free_cpus is not None:
        command.extend(["--n-free-cpus", str(config.n_free_cpus)])
    if config.backend is not None:
        command.extend(["--backend", config.backend])
    if config.debug:
        command.append("--debug")
    if config.save_original_orientation:
        command.append("--save-original-orientation")
    if config.brain_geometry != "full":
        command.extend(["--brain_geometry", config.brain_geometry])
    if config.pre_processing != "default":
        command.extend(["--pre-processing", config.pre_processing])
    return command


def _stack_config_from_metadata(stack_metadata: dict[str, Any]) -> StackBuildConfig:
    config = stack_metadata.get("config", {})
    return StackBuildConfig(
        sample_id=config.get("sample_id"),
        source_kind=config.get("source_kind", "registration"),
        channel=config.get("channel"),
        placement_mode=config.get("placement_mode", "center"),
        allowed_qc_statuses=tuple(config["allowed_qc_statuses"]) if config.get("allowed_qc_statuses") else None,
        require_include_in_stack=bool(config.get("require_include_in_stack", True)),
        fill_value=float(config.get("fill_value", 0.0)),
        output_dtype=config.get("output_dtype"),
        output_name=config.get("output_name"),
    )


def _write_volume_as_slice_directory(volume: np.ndarray, output_dir: Path) -> None:
    if volume.ndim != 3:
        raise ValueError(f"Expected a 3D stack with shape (Z, Y, X), got {volume.shape}.")
    _reset_directory(output_dir)
    for index in range(volume.shape[0]):
        slice_path = output_dir / f"slice_{index + 1:04d}.tif"
        imwrite(slice_path, volume[index])


def _voxel_triplet(voxel_size: dict[str, Any]) -> tuple[float, float, float]:
    z = _required_float(voxel_size.get("z"), "z voxel size")
    y = _required_float(voxel_size.get("y"), "y voxel size")
    x = _required_float(voxel_size.get("x"), "x voxel size")
    return (z, y, x)


def _read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _required_float(value: Any, label: str) -> float:
    if value is None or value == "":
        raise ValueError(f"{label} is missing and is required for brainreg.")
    return float(value)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _format_float(value: float) -> str:
    return format(float(value), "g")


def _quote_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_command_script(path: Path, command: Sequence[str]) -> None:
    script = "& " + " ".join(_quote_powershell(part) for part in command) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(script)


def _reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
