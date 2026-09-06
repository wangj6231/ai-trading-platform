from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest

from app.core.algorithm_identity import (
    ALGORITHM_IDENTITY_SCHEMA_VERSION,
    DEFAULT_ALGORITHM_SOURCE_RULES,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    AlgorithmIdentityError,
    AlgorithmSourceManifestRules,
    SourceManifestEntry,
    build_algorithm_identity,
    build_source_manifest,
    canonical_source_manifest,
    discover_algorithm_source_paths,
)
from app.core.config import REPOSITORY_ROOT


FIXTURE_RULES = AlgorithmSourceManifestRules(
    source_roots=(
        "backend/app/engines",
        "backend/app/backtesting",
    ),
    source_files=("backend/app/core/strategy_identity.py",),
)

AUDIT_V4_MISSING_RELEVANT_SOURCES = (
    "backend/app/core/time.py",
    "backend/app/core/financial.py",
    "backend/app/metrics/financial.py",
)


def _write(root: Path, relative: str, content: str, *, newline: str = "\n") -> Path:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.replace("\n", newline).encode("utf-8"))
    return path


def _make_source_tree(root: Path, *, newline: str = "\n") -> Path:
    _write(root, "backend/app/engines/__init__.py", "", newline=newline)
    source = _write(
        root,
        "backend/app/engines/example.py",
        "def outcome():\n    return 'clean'\n",
        newline=newline,
    )
    _write(root, "backend/app/backtesting/__init__.py", "", newline=newline)
    _write(
        root,
        "backend/app/backtesting/runner.py",
        "EXECUTION = 'sequential'\n",
        newline=newline,
    )
    _write(
        root,
        "backend/app/core/strategy_identity.py",
        "IDENTITY = 'server-owned'\n",
        newline=newline,
    )
    return source


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout


def _commit_fixture(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "identity-test@example.invalid")
    _git(root, "config", "user.name", "Identity Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")


def test_clean_git_source_identity_is_deterministic(tmp_path: Path) -> None:
    _make_source_tree(tmp_path)
    _commit_fixture(tmp_path)

    first = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    second = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert first == second
    assert first.algorithm_identity_schema_version == ALGORITHM_IDENTITY_SCHEMA_VERSION
    assert first.source_manifest_schema_version == SOURCE_MANIFEST_SCHEMA_VERSION
    assert first.git_available is True
    assert first.git_commit_sha is not None
    assert first.git_dirty is False


def test_unstaged_relevant_change_alters_identity_and_exact_revert_restores_it(
    tmp_path: Path,
) -> None:
    source = _make_source_tree(tmp_path)
    _commit_fixture(tmp_path)
    clean = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    source.write_text("def outcome():\n    return 'unstaged'\n", encoding="utf-8")
    dirty = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    _git(tmp_path, "checkout", "--", "backend/app/engines/example.py")
    restored = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert dirty.source_content_hash != clean.source_content_hash
    assert dirty.algorithm_build_hash != clean.algorithm_build_hash
    assert dirty.git_commit_sha == clean.git_commit_sha
    assert dirty.git_dirty is True
    assert restored.source_content_hash == clean.source_content_hash
    assert restored.algorithm_build_hash == clean.algorithm_build_hash


def test_staged_relevant_change_uses_working_source_not_head(tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)
    _commit_fixture(tmp_path)
    clean = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    source.write_text("def outcome():\n    return 'staged'\n", encoding="utf-8")
    _git(tmp_path, "add", "backend/app/engines/example.py")
    staged = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    source.write_text("def outcome():\n    return 'working-after-stage'\n", encoding="utf-8")
    working = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert staged.git_commit_sha == clean.git_commit_sha
    assert staged.git_dirty is True
    assert staged.source_content_hash != clean.source_content_hash
    assert staged.algorithm_build_hash != clean.algorithm_build_hash
    assert working.git_commit_sha == staged.git_commit_sha
    assert working.source_content_hash != staged.source_content_hash
    assert working.algorithm_build_hash != staged.algorithm_build_hash


def test_two_dirty_trees_at_same_head_have_distinct_content_identity(
    tmp_path: Path,
) -> None:
    source = _make_source_tree(tmp_path)
    _commit_fixture(tmp_path)

    source.write_text("def outcome():\n    return 'dirty-a'\n", encoding="utf-8")
    first = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    source.write_text("def outcome():\n    return 'dirty-b'\n", encoding="utf-8")
    second = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert first.git_commit_sha == second.git_commit_sha
    assert first.git_dirty is second.git_dirty is True
    assert first.source_content_hash != second.source_content_hash
    assert first.algorithm_build_hash != second.algorithm_build_hash


def test_irrelevant_dirty_files_and_deployment_config_do_not_change_identity(
    tmp_path: Path,
) -> None:
    _make_source_tree(tmp_path)
    _write(tmp_path, "README.md", "clean\n")
    _commit_fixture(tmp_path)
    clean = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    _write(tmp_path, "README.md", "dirty docs\n")
    _write(tmp_path, "docs/note.md", "irrelevant\n")
    _write(tmp_path, "backend/tests/test_note.py", "IRRELEVANT = True\n")
    _write(tmp_path, "frontend/src/note.ts", "export const irrelevant = true;\n")
    _write(tmp_path, "runtime.log", "mutable output\n")
    _write(tmp_path, ".env", "DATABASE_URL=postgresql://secret\nOPENAI_API_KEY=x\n")
    dirty = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert dirty.git_dirty is True
    assert dirty.source_content_hash == clean.source_content_hash
    assert dirty.algorithm_build_hash == clean.algorithm_build_hash


def test_relevant_untracked_source_changes_identity_and_removal_restores_it(
    tmp_path: Path,
) -> None:
    _make_source_tree(tmp_path)
    _commit_fixture(tmp_path)
    clean = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    added = _write(
        tmp_path,
        "backend/app/engines/new_runtime_module.py",
        "ENABLED = True\n",
    )
    changed = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    added.unlink()
    restored = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert changed.source_file_count == clean.source_file_count + 1
    assert changed.algorithm_build_hash != clean.algorithm_build_hash
    assert restored.source_content_hash == clean.source_content_hash
    assert restored.algorithm_build_hash == clean.algorithm_build_hash


def test_untracked_imported_dependency_outside_seed_root_participates(
    tmp_path: Path,
) -> None:
    source = _make_source_tree(tmp_path)
    _write(tmp_path, "backend/app/__init__.py", "")
    _commit_fixture(tmp_path)
    clean = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    source.write_text(
        "from app.shared.helper import VALUE\n\ndef outcome():\n    return VALUE\n",
        encoding="utf-8",
    )
    _write(tmp_path, "backend/app/shared/__init__.py", "")
    helper = _write(tmp_path, "backend/app/shared/helper.py", "VALUE = 'a'\n")
    first = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    helper.write_text("VALUE = 'b'\n", encoding="utf-8")
    second = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert first.git_dirty is second.git_dirty is True
    assert first.source_content_hash != clean.source_content_hash
    assert second.source_content_hash != first.source_content_hash
    assert second.algorithm_build_hash != first.algorithm_build_hash


def test_relevant_deletion_and_rename_change_manifest_identity(tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)
    original = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    renamed = source.with_name("renamed.py")
    source.rename(renamed)
    after_rename = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    renamed.unlink()
    after_delete = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert after_rename.source_file_count == original.source_file_count
    assert after_rename.source_content_hash != original.source_content_hash
    assert after_delete.source_file_count == original.source_file_count - 1
    assert after_delete.source_content_hash != after_rename.source_content_hash


def test_identical_source_is_path_independent_and_line_ending_stable(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "checkout-a"
    second_root = tmp_path / "different" / "checkout-b"
    first_root.mkdir()
    second_root.mkdir(parents=True)
    _make_source_tree(first_root, newline="\n")
    _make_source_tree(second_root, newline="\r\n")

    first = build_algorithm_identity(first_root, FIXTURE_RULES)
    second = build_algorithm_identity(second_root, FIXTURE_RULES)

    assert first.source_content_hash == second.source_content_hash
    assert first.algorithm_build_hash == second.algorithm_build_hash


def test_mtime_only_change_does_not_change_content_identity(tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)
    baseline = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    stat = source.stat()
    os.utime(source, (stat.st_atime + 10, stat.st_mtime + 10))
    changed_metadata_only = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert changed_metadata_only.source_content_hash == baseline.source_content_hash
    assert changed_metadata_only.algorithm_build_hash == baseline.algorithm_build_hash


def test_permission_only_change_does_not_change_content_identity(tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)
    baseline = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    original_mode = stat.S_IMODE(source.stat().st_mode)

    try:
        source.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        changed_metadata_only = build_algorithm_identity(tmp_path, FIXTURE_RULES)
    finally:
        source.chmod(original_mode)

    assert changed_metadata_only.source_content_hash == baseline.source_content_hash
    assert changed_metadata_only.algorithm_build_hash == baseline.algorithm_build_hash


def test_utf8_bom_does_not_create_a_false_source_change(tmp_path: Path) -> None:
    first_root = tmp_path / "without-bom"
    second_root = tmp_path / "with-bom"
    first_root.mkdir()
    second_root.mkdir()
    first_source = _make_source_tree(first_root)
    second_source = _make_source_tree(second_root)
    second_source.write_bytes(b"\xef\xbb\xbf" + first_source.read_bytes())

    first = build_algorithm_identity(first_root, FIXTURE_RULES)
    second = build_algorithm_identity(second_root, FIXTURE_RULES)

    assert first.source_content_hash == second.source_content_hash
    assert first.algorithm_build_hash == second.algorithm_build_hash


def test_manifest_serialization_is_independent_of_discovery_order() -> None:
    entries = (
        SourceManifestEntry("backend/app/engines/z.py", "a" * 64),
        SourceManifestEntry("backend/app/engines/a.py", "b" * 64),
    )

    assert canonical_source_manifest(entries) == canonical_source_manifest(reversed(entries))


def test_no_git_metadata_still_produces_strong_content_identity(tmp_path: Path) -> None:
    _make_source_tree(tmp_path)

    identity = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert identity.git_available is False
    assert identity.git_commit_sha is None
    assert identity.git_dirty is None
    assert len(identity.source_content_hash) == 64
    assert len(identity.algorithm_build_hash) == 64
    assert identity.algorithm_build_hash != "0" * 64


def test_git_command_failure_does_not_weaken_source_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_source_tree(tmp_path)
    _commit_fixture(tmp_path)
    expected = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr("app.core.algorithm_identity.subprocess.run", unavailable)
    without_git = build_algorithm_identity(tmp_path, FIXTURE_RULES)

    assert without_git.git_available is False
    assert without_git.source_content_hash == expected.source_content_hash
    assert without_git.algorithm_build_hash == expected.algorithm_build_hash


def test_source_read_failure_fails_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _make_source_tree(tmp_path)
    original = Path.read_bytes

    def fail_one(path: Path) -> bytes:
        if path == source:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail_one)

    with pytest.raises(AlgorithmIdentityError, match="failed to read required"):
        build_algorithm_identity(tmp_path, FIXTURE_RULES)


def test_source_rules_reject_path_traversal(tmp_path: Path) -> None:
    _make_source_tree(tmp_path)
    unsafe = AlgorithmSourceManifestRules(source_roots=("../outside",))

    with pytest.raises(AlgorithmIdentityError, match="invalid repository-relative"):
        build_algorithm_identity(tmp_path, unsafe)


def test_missing_required_internal_dependency_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "backend/app/__init__.py", "")
    _write(tmp_path, "backend/app/engines/__init__.py", "")
    _write(
        tmp_path,
        "backend/app/engines/strategy.py",
        "import app.shared.missing\n",
    )
    rules = AlgorithmSourceManifestRules(source_roots=("backend/app/engines",))

    with pytest.raises(AlgorithmIdentityError, match="dependency is unavailable"):
        build_algorithm_identity(tmp_path, rules)


def test_default_manifest_covers_each_outcome_affecting_subsystem() -> None:
    discovered = {
        path.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
        for path in discover_algorithm_source_paths(REPOSITORY_ROOT)
    }
    expected = {
        "backend/app/engines/strategy_engine.py",
        "backend/app/engines/structure/liquidity.py",
        "backend/app/engines/smc/fvg.py",
        "backend/app/engines/smc/order_blocks.py",
        "backend/app/engines/smc/displacement.py",
        "backend/app/engines/risk/calculations.py",
        "backend/app/engines/signal/score.py",
        "backend/app/engines/signal/lifecycle.py",
        "backend/app/backtesting/execution.py",
        "backend/app/backtesting/runner.py",
        "backend/app/backtesting/identity.py",
        "backend/app/market_data/resampling.py",
        "backend/app/market_data/timeframes.py",
        "backend/app/core/time.py",
        "backend/app/core/financial.py",
        "backend/app/metrics/financial.py",
        "backend/app/core/algorithm_identity.py",
        "backend/app/core/strategy_config.py",
        "backend/app/core/strategy_identity.py",
        "backend/app/services/snapshot_builder.py",
        "backend/app/services/strategy_evaluation.py",
        "backend/app/__init__.py",
        "backend/app/core/__init__.py",
        "backend/app/metrics/__init__.py",
    }

    assert expected <= discovered
    assert all("__pycache__" not in path for path in discovered)
    assert all(path.endswith(".py") for path in discovered)


def test_default_manifest_exposes_only_canonical_repository_relative_paths() -> None:
    manifest = build_source_manifest(REPOSITORY_ROOT)

    assert manifest
    assert all(not Path(entry.relative_path).is_absolute() for entry in manifest)
    assert all("\\" not in entry.relative_path for entry in manifest)
    assert tuple(entry.relative_path for entry in manifest) == tuple(
        sorted(entry.relative_path for entry in manifest)
    )


@pytest.mark.parametrize("relative_path", AUDIT_V4_MISSING_RELEVANT_SOURCES)
def test_simulated_audit_v4_dependency_change_alters_source_and_build_hash(
    relative_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = build_algorithm_identity(REPOSITORY_ROOT)
    target = (REPOSITORY_ROOT / relative_path).resolve()
    original_read_bytes = Path.read_bytes
    reads = 0

    def read_with_simulated_change(path: Path) -> bytes:
        nonlocal reads
        content = original_read_bytes(path)
        if path.resolve() == target:
            reads += 1
            return content + b"\n# simulated-audit-v4-source-change\n"
        return content

    monkeypatch.setattr(Path, "read_bytes", read_with_simulated_change)
    changed = build_algorithm_identity(REPOSITORY_ROOT)

    assert reads > 0
    assert changed.source_content_hash != baseline.source_content_hash
    assert changed.algorithm_build_hash != baseline.algorithm_build_hash


def test_imported_internal_helper_outside_seed_roots_is_included_and_hashed(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "backend/app/__init__.py", "")
    _write(tmp_path, "backend/app/engines/__init__.py", "")
    _write(
        tmp_path,
        "backend/app/engines/strategy.py",
        "from app.shared import classify\n",
    )
    _write(tmp_path, "backend/app/shared/__init__.py", "from .outcome import classify\n")
    helper = _write(
        tmp_path,
        "backend/app/shared/outcome.py",
        "def classify():\n    return 'a'\n",
    )
    rules = AlgorithmSourceManifestRules(source_roots=("backend/app/engines",))

    baseline = build_algorithm_identity(tmp_path, rules)
    discovered = {
        path.relative_to(tmp_path.resolve()).as_posix()
        for path in discover_algorithm_source_paths(tmp_path, rules)
    }
    helper.write_text("def classify():\n    return 'b'\n", encoding="utf-8")
    changed = build_algorithm_identity(tmp_path, rules)

    assert "backend/app/shared/outcome.py" in discovered
    assert changed.source_content_hash != baseline.source_content_hash
    assert changed.algorithm_build_hash != baseline.algorithm_build_hash


def test_package_relative_import_dependency_is_included_and_hashed(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "backend/app/__init__.py", "")
    _write(tmp_path, "backend/app/engines/__init__.py", "")
    _write(
        tmp_path,
        "backend/app/engines/strategy.py",
        "from ..shared.outcome import classify\n",
    )
    _write(tmp_path, "backend/app/shared/__init__.py", "")
    helper = _write(tmp_path, "backend/app/shared/outcome.py", "VALUE = 'a'\n")
    rules = AlgorithmSourceManifestRules(source_roots=("backend/app/engines",))

    baseline = build_algorithm_identity(tmp_path, rules)
    helper.write_text("VALUE = 'b'\n", encoding="utf-8")
    changed = build_algorithm_identity(tmp_path, rules)

    assert changed.source_content_hash != baseline.source_content_hash
    assert changed.algorithm_build_hash != baseline.algorithm_build_hash


def test_unreferenced_internal_helper_outside_seed_roots_remains_excluded(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "backend/app/__init__.py", "")
    _write(tmp_path, "backend/app/engines/__init__.py", "")
    _write(tmp_path, "backend/app/engines/strategy.py", "OUTCOME = 'a'\n")
    helper = _write(tmp_path, "backend/app/shared/unused.py", "VALUE = 'a'\n")
    rules = AlgorithmSourceManifestRules(source_roots=("backend/app/engines",))

    baseline = build_algorithm_identity(tmp_path, rules)
    helper.write_text("VALUE = 'b'\n", encoding="utf-8")
    changed = build_algorithm_identity(tmp_path, rules)

    assert changed.source_content_hash == baseline.source_content_hash
    assert changed.algorithm_build_hash == baseline.algorithm_build_hash


@pytest.mark.parametrize(
    "relative_path",
    (
        "backend/app/engines/strategy_engine.py",
        "backend/app/engines/structure/liquidity.py",
        "backend/app/engines/risk/calculations.py",
        "backend/app/backtesting/execution.py",
        "backend/app/backtesting/runner.py",
        "backend/app/engines/signal/lifecycle.py",
    ),
)
def test_representative_subsystem_source_change_alters_hash(
    tmp_path: Path,
    relative_path: str,
) -> None:
    for root in DEFAULT_ALGORITHM_SOURCE_RULES.source_roots:
        _write(tmp_path, f"{root}/__init__.py", "")
    for required in DEFAULT_ALGORITHM_SOURCE_RULES.source_files:
        _write(tmp_path, required, "SOURCE = 'required'\n")
    source = _write(tmp_path, relative_path, "OUTCOME = 'a'\n")
    original = build_algorithm_identity(tmp_path)

    source.write_text("OUTCOME = 'b'\n", encoding="utf-8")
    changed = build_algorithm_identity(tmp_path)

    assert changed.source_content_hash != original.source_content_hash
    assert changed.algorithm_build_hash != original.algorithm_build_hash
