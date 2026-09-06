"""Recover a measurement-harness UTC fault within the ORIGINAL 600-second cap.

The unchanged measure.worker delegates to exactly the same frozen runner/engine.
Keep the failed first attempt; do not pool its timing observations with this one.
"""
import argparse
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import sys
import time

import measure

BASE = Path(__file__).resolve().parent
OUT = BASE / "attempt_2"
prep = measure.prepared


def supervise():
    OUT.mkdir(exist_ok=False)
    original = prep.read_json(BASE / "measurement_started.json")
    original_start = datetime.fromisoformat(original["at"])
    origin = time.perf_counter() - (datetime.now(UTC) - original_start).total_seconds()
    if time.perf_counter() >= origin + 585:
        raise RuntimeError("Original measurement budget exhausted; no restart permitted")
    prep.write_new(OUT / "measurement_started.json", {
        **original, "attempt_started_at": datetime.now(UTC),
        "note": "Same frozen path; original shared cap NOT reset; attempt 1 retained separately.",
    })
    with (OUT / "worker_console.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__)), "worker", "--origin", str(origin)],
            cwd=measure.ROOT / "backend", stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        prep.write_new(OUT / "worker_process.json", {"pid": process.pid, "at": datetime.now(UTC)})
        forced = False
        while process.poll() is None:
            if time.perf_counter() >= origin + 599:
                forced = True
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=1)
                break
            time.sleep(0.05)
        process.wait(timeout=1)
    prep.write_new(OUT / "measurement_ended.json", {
        "at": datetime.now(UTC), "child_exit_code": process.returncode,
        "forced_termination": forced, "stopped_cleanly": not forced and process.returncode == 0,
        "elapsed_from_original_start_seconds": time.perf_counter() - origin,
        "within_original_hard_cap": time.perf_counter() - origin <= 600,
    })
    print(prep.encoded(prep.read_json(OUT / "measurement_ended.json")).decode(), flush=True)
    if process.returncode != 0:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("supervise", "worker"))
    parser.add_argument("--origin", type=float)
    args = parser.parse_args()
    if args.stage == "supervise":
        supervise()
    else:
        measure.WORK = OUT
        measure.worker(args.origin, args.origin + 585)
