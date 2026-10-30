"""Same prepared historical inputs across implementations; no strategy outputs."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import platform
from statistics import median
from threading import Event, Thread
from time import perf_counter, process_time
import tracemalloc

import psutil

from app.market_data.rust_alignment import MarketAlignmentValidator
from app.schemas.types import Timeframe
from tests.fixtures.rust_core_evidence import ARTIFACTS


@dataclass(frozen=True)
class Row:
    timestamp: datetime


def run() -> None:
    process = psutil.Process()
    results = []
    for size in (1, 128, 1000, 4096, 35_000):
        rows = tuple(Row(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * i)) for i in range(size))
        input_hash = sha256("\n".join(row.timestamp.isoformat() for row in rows).encode()).hexdigest()
        for mode in ("python", "shadow", "rust"):
            validator = MarketAlignmentValidator(mode)
            validator(rows, Timeframe.FIFTEEN_MINUTES)
            samples = [process.memory_info().rss]
            done = Event()
            def sample() -> None:
                while not done.wait(.005):
                    samples.append(process.memory_info().rss)
            thread = Thread(target=sample, daemon=True)
            thread.start()
            durations = []
            cpu_start = process_time()
            try:
                for _ in range(5):
                    start = perf_counter()
                    validator(rows, Timeframe.FIFTEEN_MINUTES)
                    durations.append(perf_counter() - start)
            finally:
                done.set()
                thread.join()
            cpu = process_time() - cpu_start
            tracemalloc.start()
            validator(rows, Timeframe.FIFTEEN_MINUTES)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            wall = median(durations)
            results.append({"rows": size, "mode": mode, "input_hash": input_hash,
                "wall_seconds_median": wall, "wall_samples_seconds": durations,
                "cpu_seconds_five_runs": cpu, "rss_start_bytes": samples[0],
                "rss_sampled_peak_bytes": max(samples), "python_traced_peak_temporary_bytes": peak,
                "items_per_second": size / wall})
    result = {"runtime": platform.python_version(), "platform": platform.platform(),
        "cpu_logical": psutil.cpu_count(), "cases": results,
        "policy": "same inputs; warmup then five timed runs; allocation measured separately; no native-only cutover",
        "rss_limitations": "5ms sampling can miss short peaks; memory allocator reuse/order affect RSS; tracemalloc excludes native allocations"}
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "benchmark.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf8")
    print(json.dumps({"profiles": len(results), "research_results_interpreted": False}))


if __name__ == "__main__":
    run()
