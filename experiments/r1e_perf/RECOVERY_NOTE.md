# Measurement harness fault and bounded recovery

Attempt 1 started at 2026-09-06T04:43:17.058951Z. Its strategy, config and Q1
dataset were unchanged. The initial Python supervisor sampled the Windows venv
launcher rather than the interpreter child; its `resources.jsonl` must NOT be
used as strategy CPU/memory evidence.

The supplemental PowerShell observer found the actual interpreter but incorrectly
round-tripped an auto-decoded DateTime through `.ToString()` and local-offset
DateTimeOffset parsing. It interpreted the UTC deadline incorrectly and killed
the worker early at 04:45:35Z. Attempt 1 is **FORCED_EARLY_STOP / HARNESS_ERROR**,
not a cooperative cap stop or a completed research run. All original logs and
scripts are retained; no attempt-1 artifacts are overwritten.
The faulty PowerShell source is archived byte-for-byte as
`observe-worker.failed.ps1.txt` so it is not a runnable `.ps1` entry point.

The user was informed. Recovery uses `retry_same_path.py`, which invokes the
same `measure.worker` and unchanged `run_backtest` / concrete engine with exactly
the same canonical inputs. This is not a second strategy configuration. The
retry started at 04:47:24.110255Z with the **original** start/deadline retained:
cooperative stop at original +585s, hard cap at original +600s. It does not get
another ten-minute budget. The two attempts' throughput is never pooled.

`observe_interpreter.py` uses a verified direct child PID and Win32 process
handles for CPU/memory. It is read-only and cannot terminate any process. The
corrected supervisor's deadline arithmetic uses timezone-aware ISO parsing;
its emergency termination targets only its own worker process tree.

Report usable attempt-2 measurements separately, disclose the shorter observation
window and the first attempt's failure. No decision, candidate, trade, lifecycle,
score or financial content is exported/interpreted. No official R1-E replay,
reproducibility result or optimization is started.
