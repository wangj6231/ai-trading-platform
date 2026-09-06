"""Read-only Windows interpreter telemetry; NEVER controls or terminates a process."""
import ctypes
from ctypes import wintypes
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import measure

out = Path(__file__).resolve().parent / "attempt_2"
launcher = measure.prepared.read_json(out / "worker_process.json")["pid"]
command = (
    f"Get-CimInstance Win32_Process -Filter 'ParentProcessId = {launcher}' | "
    "Where-Object {$_.Name -eq 'python.exe'} | "
    "Select-Object ProcessId,ParentProcessId,ExecutablePath | ConvertTo-Json -Compress"
)
data = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                      capture_output=True, text=True, check=True)
info = json.loads(data.stdout)
if not isinstance(info, dict) or info["ParentProcessId"] != launcher:
    raise RuntimeError("Expected exactly one interpreter belonging to measured launcher")
kernel = ctypes.windll.kernel32
kernel.OpenProcess.restype = wintypes.HANDLE
handle = kernel.OpenProcess(0x100410, False, info["ProcessId"])
if not handle:
    raise ctypes.WinError()
proxy = SimpleNamespace(_handle=handle)
try:
    with (out / "interpreter_resources.jsonl").open("x", encoding="utf-8") as stream:
        measure.emit(stream, {"kind": "observer_started", "at": datetime.now(UTC),
                              "process": info, "note": "Actual interpreter; read-only observer; attached after load."})
        origin = time.perf_counter()
        while True:
            measure.emit(stream, {"kind": "sample", **measure.resource_sample(proxy),
                                  "observer_elapsed_seconds": time.perf_counter() - origin})
            status = kernel.WaitForSingleObject(wintypes.HANDLE(handle), 5000)
            if status == 0:
                measure.emit(stream, {"kind": "observer_ended", **measure.resource_sample(proxy),
                                      "observer_elapsed_seconds": time.perf_counter() - origin})
                break
            if status != 258:
                raise ctypes.WinError()
finally:
    kernel.CloseHandle(wintypes.HANDLE(handle))
