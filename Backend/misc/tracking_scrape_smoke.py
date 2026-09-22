"""
Manual smoke test for the tracking scraper (app/modules/tracking).

Runs the real scraper against real eligible orders and prints per-order results
and diagnostics — the fastest way to see what parcelsapp is returning.

    # inside the backend container:
    docker exec -e PYTHONPATH=/app -w /app usav_backend_dev \
        python misc/tracking_scrape_smoke.py [N]

    # or check a specific tracking number without touching the DB:
    docker exec -e PYTHONPATH=/app -w /app usav_backend_dev \
        python misc/tracking_scrape_smoke.py --tn 9400100000000000000000
"""
import asyncio
import sys

from app.core.database import async_session_factory
from app.modules.tracking import runner
from app.modules.tracking.scraper import TrackingScraper


async def _check_numbers(numbers: list[str]) -> None:
    async with TrackingScraper() as scraper:
        for tn in numbers:
            res = await scraper.scrape(tn)
            print(f"  {tn:26s} {str(res.status):12s} {res.detail}")


async def _run_job(limit: int) -> None:
    async with async_session_factory() as db:
        items = await runner._load_eligible_items(db)
    print(f"eligible tracking numbers: {len(items)} (testing {min(limit, len(items))})")
    if not items:
        return

    job = runner.TrackingJobState(job_id="smoke", items=items[:limit], auto_probe=False)
    runner._CURRENT_JOB = job
    task = asyncio.create_task(runner._process(job))
    while not task.done():
        await asyncio.sleep(3)
        cur = job.current.tracking_number if job.current else "-"
        print(f"  {job.status} {job.processed}/{job.total} current={cur} counts={job.counts}")
    await task

    print(f"\nfinal: {job.status}  counts={job.counts}  last_error={job.last_error}")
    for it in job.items:
        print(f"  {it.tracking_number:26s} {str(it.result):12s} {it.detail}")


async def main() -> None:
    args = sys.argv[1:]
    if "--tn" in args:
        await _check_numbers(args[args.index("--tn") + 1:])
    else:
        await _run_job(int(args[0]) if args else 4)


asyncio.run(main())
