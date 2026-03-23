#!/usr/bin/env python
"""Run the full image pull pipeline in one command with consolidated logging.

Pipeline stages:
1) generate_image_tasks.py
2) build_image_url_candidates.py
3) fetch_amazon_image_urls.py (optional fallback)
4) merge candidate JSON files
5) download_image_candidates.py
6) flatten_and_dedupe.py
7) sync_thumbnails_to_db.py

This script is intended to run from the Backend project root or from /app in the
backend container where scripts live at /app/scripts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass
class StageResult:
    name: str
    elapsed_seconds: float


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _log(message: str, *, log_file: Path) -> None:
    line = f"[{_timestamp()}] {message}"
    print(line, flush=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _run_stage(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    log_file: Path,
) -> StageResult:
    _log(f"STAGE START: {name}", log_file=log_file)
    _log(f"COMMAND: {' '.join(command)}", log_file=log_file)

    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        line_text = line.rstrip("\n")
        print(line_text, flush=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line_text + "\n")

    exit_code = process.wait()
    elapsed = time.perf_counter() - started

    if exit_code != 0:
        _log(
            f"STAGE FAILED: {name} | exit_code={exit_code} | elapsed={elapsed:.2f}s",
            log_file=log_file,
        )
        raise RuntimeError(f"Stage failed: {name}")

    _log(f"STAGE DONE: {name} | elapsed={elapsed:.2f}s", log_file=log_file)
    return StageResult(name=name, elapsed_seconds=elapsed)


def _merge_candidate_files(
    *,
    base_candidates_path: Path,
    amazon_candidates_path: Path,
    merged_output_path: Path,
    include_amazon_file: bool,
    log_file: Path,
) -> StageResult:
    stage_name = "merge_image_url_candidates"
    _log(f"STAGE START: {stage_name}", log_file=log_file)

    started = time.perf_counter()

    base_rows = json.loads(base_candidates_path.read_text(encoding="utf-8"))
    amazon_rows: list[dict]
    if include_amazon_file and amazon_candidates_path.exists():
        amazon_rows = json.loads(amazon_candidates_path.read_text(encoding="utf-8"))
    else:
        amazon_rows = []

    grouped: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(
        lambda: {"image_urls": set(), "sources": set()}
    )

    for row in list(base_rows) + list(amazon_rows):
        sku = str(row.get("sku") or "").strip()
        platform = str(row.get("platform") or "").strip().upper()
        external_id = str(row.get("external_id") or "").strip()
        if not sku or not platform or not external_id:
            continue

        key = (sku, platform, external_id)

        for url in row.get("image_urls") or []:
            url_str = str(url).strip()
            if url_str:
                grouped[key]["image_urls"].add(url_str)

        for source in row.get("sources") or []:
            source_str = str(source).strip()
            if source_str:
                grouped[key]["sources"].add(source_str)

    merged_rows: list[dict] = []
    for (sku, platform, external_id), payload in sorted(grouped.items()):
        merged_rows.append(
            {
                "sku": sku,
                "platform": platform,
                "external_id": external_id,
                "image_urls": sorted(payload["image_urls"]),
                "sources": sorted(payload["sources"]),
            }
        )

    _ensure_parent(merged_output_path)
    merged_output_path.write_text(json.dumps(merged_rows, indent=2), encoding="utf-8")

    elapsed = time.perf_counter() - started
    _log(
        (
            f"STAGE DONE: {stage_name} | elapsed={elapsed:.2f}s | "
            f"base_rows={len(base_rows)} amazon_rows={len(amazon_rows)} "
            f"merged_rows={len(merged_rows)}"
        ),
        log_file=log_file,
    )
    return StageResult(name=stage_name, elapsed_seconds=elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full image pull pipeline in one command")

    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root where scripts/ directory exists (default: current directory)",
    )
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python executable used to run child scripts",
    )

    parser.add_argument("--images-root", default="/mnt/product_images", help="Image root path")

    parser.add_argument("--tasks-output", default="scripts/image_tasks.json")
    parser.add_argument("--base-candidates-output", default="scripts/image_url_candidates_base.json")
    parser.add_argument("--amazon-candidates-output", default="scripts/image_url_candidates_amazon.json")
    parser.add_argument("--merged-candidates-output", default="scripts/image_url_candidates.json")
    parser.add_argument("--download-failed-output", default="scripts/image_failed_urls.jsonl")
    parser.add_argument("--download-retry-output", default="scripts/image_retry_input.json")
    parser.add_argument("--log-dir", default="scripts/logs")

    parser.add_argument("--platforms", default=None, help="Optional platforms filter for task generation")
    parser.add_argument("--include-inactive", action="store_true", help="Include inactive variants in task generation")
    parser.add_argument("--task-limit", type=int, default=None, help="Optional limit for generated tasks")

    parser.add_argument("--include-platform-metadata", action="store_true", default=True)
    parser.add_argument("--no-include-platform-metadata", action="store_false", dest="include_platform_metadata")
    parser.add_argument("--fetch-ecwid", action="store_true", default=True)
    parser.add_argument("--no-fetch-ecwid", action="store_false", dest="fetch_ecwid")
    parser.add_argument("--fetch-ebay", action="store_true", default=True)
    parser.add_argument("--no-fetch-ebay", action="store_false", dest="fetch_ebay")
    parser.add_argument("--build-delay-ms", type=int, default=100)
    parser.add_argument("--build-progress-every", type=int, default=25)

    parser.add_argument("--run-amazon-fallback", action="store_true", default=True)
    parser.add_argument("--no-run-amazon-fallback", action="store_false", dest="run_amazon_fallback")
    parser.add_argument("--amazon-timeout", type=int, default=20)
    parser.add_argument("--amazon-max-per-asin", type=int, default=20)
    parser.add_argument("--amazon-delay-min-ms", type=int, default=250)
    parser.add_argument("--amazon-delay-max-ms", type=int, default=850)
    parser.add_argument("--amazon-limit", type=int, default=None)

    parser.add_argument("--download-timeout", type=int, default=30)
    parser.add_argument("--download-max-per-task", type=int, default=20)
    parser.add_argument("--download-retries", type=int, default=2)
    parser.add_argument("--download-backoff-seconds", type=float, default=0.5)

    parser.add_argument("--dedupe-threshold", type=int, default=5)
    parser.add_argument("--dry-run-dedupe", action="store_true")
    parser.add_argument("--dry-run-thumbnail-sync", action="store_true")

    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    scripts_dir = project_root / "scripts"
    if not scripts_dir.exists():
        raise SystemExit(f"scripts directory not found under project root: {project_root}")

    log_dir = project_root / args.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"image_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    stage_results: list[StageResult] = []

    try:
        _log(f"PIPELINE START | project_root={project_root}", log_file=log_file)

        generate_cmd = [
            args.python_bin,
            str(scripts_dir / "generate_image_tasks.py"),
            "--output",
            args.tasks_output,
            "--format",
            "json",
        ]
        if args.platforms:
            generate_cmd.extend(["--platforms", args.platforms])
        if args.include_inactive:
            generate_cmd.append("--include-inactive")
        if args.task_limit is not None:
            generate_cmd.extend(["--limit", str(args.task_limit)])
        stage_results.append(
            _run_stage(name="generate_image_tasks", command=generate_cmd, cwd=project_root, log_file=log_file)
        )

        build_cmd = [
            args.python_bin,
            str(scripts_dir / "build_image_url_candidates.py"),
            "--input",
            args.tasks_output,
            "--output",
            args.base_candidates_output,
            "--delay-ms",
            str(args.build_delay_ms),
            "--progress-every",
            str(args.build_progress_every),
        ]
        if args.include_platform_metadata:
            build_cmd.append("--include-platform-metadata")
        if args.fetch_ecwid:
            build_cmd.append("--fetch-ecwid")
        if args.fetch_ebay:
            build_cmd.append("--fetch-ebay")
        stage_results.append(
            _run_stage(name="build_image_url_candidates", command=build_cmd, cwd=project_root, log_file=log_file)
        )

        if args.run_amazon_fallback:
            amazon_cmd = [
                args.python_bin,
                str(scripts_dir / "fetch_amazon_image_urls.py"),
                "--input",
                args.tasks_output,
                "--output",
                args.amazon_candidates_output,
                "--timeout",
                str(args.amazon_timeout),
                "--max-per-asin",
                str(args.amazon_max_per_asin),
                "--delay-min-ms",
                str(args.amazon_delay_min_ms),
                "--delay-max-ms",
                str(args.amazon_delay_max_ms),
            ]
            if args.amazon_limit is not None:
                amazon_cmd.extend(["--limit", str(args.amazon_limit)])
            stage_results.append(
                _run_stage(name="fetch_amazon_image_urls", command=amazon_cmd, cwd=project_root, log_file=log_file)
            )

        stage_results.append(
            _merge_candidate_files(
                base_candidates_path=project_root / args.base_candidates_output,
                amazon_candidates_path=project_root / args.amazon_candidates_output,
                merged_output_path=project_root / args.merged_candidates_output,
                include_amazon_file=args.run_amazon_fallback,
                log_file=log_file,
            )
        )

        download_cmd = [
            args.python_bin,
            str(scripts_dir / "download_image_candidates.py"),
            "--input",
            args.merged_candidates_output,
            "--images-root",
            args.images_root,
            "--timeout",
            str(args.download_timeout),
            "--max-per-task",
            str(args.download_max_per_task),
            "--retries",
            str(args.download_retries),
            "--backoff-seconds",
            str(args.download_backoff_seconds),
            "--failed-output",
            args.download_failed_output,
            "--retry-input-output",
            args.download_retry_output,
        ]
        stage_results.append(
            _run_stage(name="download_image_candidates", command=download_cmd, cwd=project_root, log_file=log_file)
        )

        dedupe_cmd = [
            args.python_bin,
            str(scripts_dir / "flatten_and_dedupe.py"),
            "--images-root",
            args.images_root,
            "--threshold",
            str(args.dedupe_threshold),
        ]
        if args.dry_run_dedupe:
            dedupe_cmd.append("--dry-run")
        stage_results.append(
            _run_stage(name="flatten_and_dedupe", command=dedupe_cmd, cwd=project_root, log_file=log_file)
        )

        sync_cmd = [
            args.python_bin,
            str(scripts_dir / "sync_thumbnails_to_db.py"),
            "--images-root",
            args.images_root,
        ]
        if args.dry_run_thumbnail_sync:
            sync_cmd.append("--dry-run")
        stage_results.append(
            _run_stage(name="sync_thumbnails_to_db", command=sync_cmd, cwd=project_root, log_file=log_file)
        )

        total_elapsed = sum(s.elapsed_seconds for s in stage_results)
        _log("PIPELINE DONE", log_file=log_file)
        _log(f"TOTAL ELAPSED: {total_elapsed:.2f}s", log_file=log_file)
        for stage in stage_results:
            _log(f"STAGE SUMMARY: {stage.name} -> {stage.elapsed_seconds:.2f}s", log_file=log_file)
        _log(f"LOG FILE: {log_file}", log_file=log_file)

    except Exception as exc:
        _log(f"PIPELINE FAILED: {exc}", log_file=log_file)
        _log(f"LOG FILE: {log_file}", log_file=log_file)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
