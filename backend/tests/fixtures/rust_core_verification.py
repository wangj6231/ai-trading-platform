"""Verify actual test execution, protected facts and bounded bootstrap artifacts."""
from contextlib import redirect_stdout
from dataclasses import asdict
from hashlib import sha256
import io
import json
import os
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import create_engine, text

from app.core.algorithm_identity import build_algorithm_identity
from tests.fixtures.rust_core_evidence import ARTIFACTS, ROOT, record

EXPECTED_CHANGED = {
    ".env.example", ".github/workflows/ci.yml", ".gitignore",
    "backend/Dockerfile", "backend/pyproject.toml", "backend/app/core/config.py",
    "backend/app/market_data/service.py", "backend/app/services/market_data.py",
}
TASK_FILES = [
    *sorted(EXPECTED_CHANGED), ".dockerignore", "README.md",
    "backend/app/market_data/rust_alignment.py",
    "rust/utc_alignment/Cargo.toml", "rust/utc_alignment/Cargo.lock",
    "rust/utc_alignment/pyproject.toml", "rust/utc_alignment/src/lib.rs",
    "backend/tests/unit/test_rust_alignment.py",
    "backend/tests/unit/test_rust_alignment_service.py",
    "backend/tests/fixtures/rust_core_evidence.py",
    "backend/tests/fixtures/rust_alignment_corpus.py",
    "backend/tests/fixtures/rust_alignment_benchmark.py",
    "backend/tests/fixtures/rust_dependency_scan.py",
    "backend/tests/fixtures/rust_core_quality.py",
    "backend/tests/fixtures/rust_core_verification.py",
    "RUST_CORE_ARCHITECTURE.md", "RUST_COMPUTE_CONTRACT_V1.md",
    "RUST_MEMORY_SAFETY_POLICY.md", "RUST_PYTHON_PARITY_REPORT.md",
    "RUST_CORE_BENCHMARK.md", "RUST_CORE_BOOTSTRAP_V1_REPORT.md",
]


class Collection:
    def __init__(self) -> None:
        self.marked: list[str] = []
        self.count = 0

    def pytest_collection_finish(self, session) -> None:
        self.count = len(session.items)
        self.marked = [item.nodeid for item in session.items if item.get_closest_marker("postgresql")]


def verify() -> None:
    collection = Collection()
    with redirect_stdout(io.StringIO()):
        code = pytest.main(["--collect-only", "-q"], plugins=[collection])
    if code:
        raise ValueError("collection failed")
    cases = ET.parse(ARTIFACTS / "full_backend.xml").findall(".//testcase")
    successful = {(item.attrib["classname"], item.attrib["name"]) for item in cases
        if item.find("failure") is None and item.find("error") is None and item.find("skipped") is None}
    failures = sum(item.find("failure") is not None or item.find("error") is not None for item in cases)
    skipped = sum(item.find("skipped") is not None for item in cases)
    if failures or skipped or len(cases) != collection.count:
        raise ValueError("full suite must match collection with zero failures/skips")
    for identifier in collection.marked:
        module, *names = identifier.split("::")
        classname = module.removesuffix(".py").replace("/", ".")
        if len(names) > 1:
            classname += "." + ".".join(names[:-1])
        if (classname, names[-1]) not in successful:
            raise ValueError("marked PostgreSQL case did not actually pass")
    baseline = json.loads((ARTIFACTS / "protected_before.json").read_text(encoding="utf8"))
    record("after")
    current = json.loads((ARTIFACTS / "protected_after.json").read_text(encoding="utf8"))
    changed = {relative for relative, digest in baseline["files"].items()
               if current["files"].get(relative) != digest}
    added = set(current["files"]) - set(baseline["files"])
    if changed != EXPECTED_CHANGED or added != {"backend/app/market_data/rust_alignment.py"}:
        raise ValueError("unexpected protected source change")
    for key in ("strategy_version", "config_hash"):
        if baseline["identity"][key] != current["identity"][key]:
            raise ValueError("frozen strategy configuration drift")
    if baseline["financial_oracle_hash"] != current["financial_oracle_hash"]:
        raise ValueError("sealed financial golden changed")
    coverage = json.loads((ARTIFACTS / "coverage.json").read_text(encoding="utf8"))
    if coverage["totals"]["percent_covered"] < 90:
        raise ValueError("coverage below existing gate")
    # Process-scoped test DSN only; no production DATABASE_URL access or mutation.
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SHOW server_version")).scalar_one()
    finally:
        engine.dispose()
    if not version.startswith("16."):
        raise ValueError("PostgreSQL 16 required")
    result = {
        "backend_passed": len(cases), "failed": failures, "skipped": skipped,
        "postgresql_marked_passed": len(collection.marked),
        "all_postgresql_cases_matched": True, "postgresql_version": version,
        "coverage_percent": coverage["totals"]["percent_covered"],
        "changed_protected_paths": sorted(changed), "added_protected_paths": sorted(added),
        "strategy_version_unchanged": True, "config_hash_unchanged": True,
        "financial_oracle_unchanged": True,
        "financial_oracle_sha256": current["financial_oracle_hash"],
        "before_identity": baseline["identity"], "after_identity": current["identity"],
        "current_algorithm_identity": asdict(build_algorithm_identity()),
        "linux_build_executed": False,
    }
    (ARTIFACTS / "verification.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf8")
    hashes = {relative: sha256((ROOT / relative).read_bytes()).hexdigest() for relative in TASK_FILES}
    (ARTIFACTS / "authored_task_files.json").write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf8")
    manifest = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
                for path in ARTIFACTS.rglob("*") if path.is_file() and path.name != "artifact_manifest.json"}
    (ARTIFACTS / "artifact_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    verify()
