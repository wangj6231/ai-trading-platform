"""Seal this diagnosis directory with byte hashes, preserving all prior runs."""
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "r1e"))
import prepare_dataset as prep

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
Q1 = ROOT / "experiments/baseline" / prep.read_json(
    ROOT / "experiments/r1e/prepared.json")["run_identity_hash"]


def main():
    if not (WORK / "PROFILE_REPORT.md").exists():
        raise RuntimeError("PROFILE_REPORT.md must exist before sealing")
    # Revalidate the exact source identity and the prior sealed R1-E-PERF inputs.
    prep.guard()
    previous = prep.read_json(ROOT / "experiments/r1e_perf/artifact_manifest.json")
    for name, digest in previous["artifacts_sha256"].items():
        if prep.file_hash(ROOT / name) != digest:
            raise RuntimeError(f"STOP: prior performance artifact changed: {name}")
    identity = prep.read_json(ROOT / "experiments/r1e/prepared.json")
    q1_hash = prep.file_hash(Q1 / "canonical_candles.json")
    paths = set(path for path in WORK.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
                and path.name != "artifact_manifest.json")
    items = {path.relative_to(ROOT).as_posix(): prep.file_hash(path)
             for path in sorted(paths)}
    manifest = {
        "schema_version": "R1E_PROFILE_ARTIFACTS_V1", "sealed_at": datetime.now(UTC),
        "scope": "PERFORMANCE_DIAGNOSIS_ONLY_NO_RESEARCH_RESULTS",
        "q1_run_identity_hash": identity["run_identity_hash"],
        "q1_canonical_candles_sha256": q1_hash,
        "previous_r1e_perf_manifest_sha256": prep.file_hash(
            ROOT / "experiments/r1e_perf/artifact_manifest.json"),
        "artifact_count": len(items), "artifacts_sha256": items,
        "r1_preservation": prep.verify_r1(),
    }
    prep.write_new(WORK / "artifact_manifest.json", manifest)
    for name, digest in items.items():
        if prep.file_hash(ROOT / name) != digest:
            raise RuntimeError(f"STOP: profile artifact changed during seal: {name}")
    print(prep.encoded({"artifact_count": len(items),
                        "manifest_sha256": prep.file_hash(WORK / "artifact_manifest.json"),
                        "r1": prep.verify_r1(),
                        "previous_r1e_perf_unchanged": True}).decode(), flush=True)


if __name__ == "__main__":
    main()
