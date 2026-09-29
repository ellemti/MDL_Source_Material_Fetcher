"""
pipeline.py

Orchestrates the MDL -> resolve -> (optional) package flow,
independent of any UI framework so it's directly testable and
reusable. Analyzing multiple models is I/O-bound (mostly file
existence checks and small text reads), so a thread pool resolves
them concurrently for a real speedup on multi-model batches without
the complexity of multiprocessing.

A parse/resolve error in one model does NOT abort the batch -- it's
recorded on that model's ModelReport (via `error`) and the rest of
the run continues. Only a genuinely unexpected exception should
propagate out of run_pipeline.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .mdl_parser import MDLParseError, parse_mdl
from .packager import write_package, zip_package
from .resolver import ResolveResult, resolve_model

MAX_WORKERS = 8


@dataclass
class ModelReport:
    path: Path
    version: Optional[int]
    material_count: int
    found_count: int
    missing_count: int
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class PipelineResult:
    combined_found: dict[Path, str] = field(default_factory=dict)
    combined_missing: list[str] = field(default_factory=list)
    model_reports: list[ModelReport] = field(default_factory=list)
    zip_path: Optional[Path] = None
    written_count: int = 0


def _analyze_one(mdl_path: Path, roots: list[Path]) -> tuple[ModelReport, Optional[ResolveResult]]:
    try:
        mdl = parse_mdl(mdl_path)
    except MDLParseError as e:
        return (
            ModelReport(
                path=mdl_path, version=None, material_count=0,
                found_count=0, missing_count=0, error=str(e),
            ),
            None,
        )

    result = resolve_model(mdl, roots)
    report = ModelReport(
        path=mdl_path,
        version=mdl.version,
        material_count=len(mdl.materials),
        found_count=len(result.found),
        missing_count=len(result.missing),
        warnings=list(mdl.warnings) + list(result.warnings),
        missing=list(result.missing),
    )
    return report, result


def run_pipeline(
    mdl_paths: list[Path],
    roots: list[Path],
    do_package: bool,
    output_dir: Optional[Path],
    progress_cb: Optional[Callable[[str], None]] = None,
    model_done_cb: Optional[Callable[[int, ModelReport], None]] = None,
) -> PipelineResult:
    """Resolves every model in mdl_paths (concurrently), then -- if
    do_package is True -- copies everything found into output_dir and
    zips it. progress_cb, if given, receives short human-readable
    status strings. model_done_cb, if given, is called once per model
    as it finishes (index, ModelReport) -- index matches the model's
    position in mdl_paths regardless of completion order, so a caller
    can safely use it to update a per-model UI row.
    """
    result = PipelineResult()
    max_workers = min(MAX_WORKERS, max(1, len(mdl_paths)))

    reports_by_index: dict[int, ModelReport] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_analyze_one, path, roots): i for i, path in enumerate(mdl_paths)}
        for future in as_completed(futures):
            i = futures[future]
            report, resolve_result = future.result()
            reports_by_index[i] = report

            if resolve_result is not None:
                result.combined_found.update(resolve_result.found)
                result.combined_missing.extend(resolve_result.missing)

            if progress_cb:
                progress_cb(f"Analyzed {report.path.name}")
            if model_done_cb:
                model_done_cb(i, report)

    result.model_reports = [reports_by_index[i] for i in range(len(mdl_paths))]

    if do_package and output_dir:
        if progress_cb:
            progress_cb("Copying files ...")
        written = write_package(result.combined_found, output_dir)
        if progress_cb:
            progress_cb("Creating ZIP ...")
        zip_path = (
            output_dir.with_suffix(".zip")
            if output_dir.suffix
            else output_dir.parent / (output_dir.name + ".zip")
        )
        zip_package(output_dir, zip_path, written)
        result.zip_path = zip_path
        result.written_count = len(written)

    return result
