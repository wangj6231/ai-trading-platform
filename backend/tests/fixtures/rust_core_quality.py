"""Record actual native/runtime checks; never substitute old green counts."""
from hashlib import sha256
import json
import os
import subprocess
import sys

from tests.fixtures.rust_core_evidence import ARTIFACTS, ROOT


def run() -> None:
    env = dict(os.environ)
    toolchain = ROOT / ".cache/rust_core_toolchain"
    env.update(RUSTUP_HOME=str(toolchain / "rustup"), CARGO_HOME=str(toolchain / "cargo"),
               PYO3_PYTHON=sys.executable)
    env["PATH"] = str(toolchain / "cargo/bin") + os.pathsep + "C:\\Python312" + os.pathsep + env["PATH"]
    cargo = str(toolchain / "cargo/bin/cargo.exe")
    manifest = str(ROOT / "rust/utc_alignment/Cargo.toml")
    commands = [
        [str(toolchain / "cargo/bin/rustc.exe"), "--version"],
        [cargo, "--version"],
        [cargo, "fmt", "--manifest-path", manifest, "--check"],
        [cargo, "clippy", "--locked", "--manifest-path", manifest, "--all-targets", "--", "-D", "warnings"],
        [cargo, "test", "--locked", "--manifest-path", manifest],
        [sys.executable, "-m", "ruff", "check", "app", "tests"],
        [sys.executable, "-m", "mypy", "app"],
        [sys.executable, "-m", "compileall", "-q", "app", "tests"],
        ["git", "diff", "--check"],
    ]
    results = []
    for command in commands:
        result = subprocess.run(command, cwd=ROOT / "backend", env=env, capture_output=True, text=True,
                                encoding="utf8", errors="replace", timeout=300)
        results.append({"command": command, "exit_code": result.returncode,
                        "stdout": result.stdout, "stderr": result.stderr})
    # Installed wheel smoke with Rust/Cargo completely absent from PATH and env.
    runtime_env = dict(os.environ)
    runtime_env["PATH"] = "C:\\Python312;C:\\Windows\\System32"
    runtime_env.pop("CARGO_HOME", None)
    runtime_env.pop("RUSTUP_HOME", None)
    smoke = subprocess.run([sys.executable, "-I", "-c",
        "import _utc_alignment_core as core; print(core.align_v1(b'{\"contract_version\":\"1\",\"timeframe\":\"1m\",\"timestamps_us\":[]}').decode())"],
        cwd=ROOT / "backend", env=runtime_env, capture_output=True, text=True, timeout=30)
    wheel = ARTIFACTS / "wheels/utc_alignment_core-0.1.0-cp312-abi3-win_amd64.whl"
    result = {"checks": results, "runtime_without_rust_exit_code": smoke.returncode,
        "runtime_without_rust_stdout": smoke.stdout, "runtime_without_rust_stderr": smoke.stderr,
        "wheel_sha256": sha256(wheel.read_bytes()).hexdigest()}
    (ARTIFACTS / "quality.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf8")
    if any(r["exit_code"] for r in results) or smoke.returncode:
        raise ValueError("quality gate failed")
    print(json.dumps({"checks_passed": len(results), "runtime_without_rust": "PASS", "wheel_sha256": result["wheel_sha256"]}))


if __name__ == "__main__":
    run()
