from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Iterable

from app.core.config import REPOSITORY_ROOT


SOURCE_MANIFEST_SCHEMA_VERSION = "2"
ALGORITHM_IDENTITY_SCHEMA_VERSION = "3"


class AlgorithmIdentityError(RuntimeError):
    """Raised when a complete trusted source identity cannot be constructed."""


@dataclass(frozen=True)
class AlgorithmSourceManifestRules:
    """Seed source plus local package roots used for dependency closure."""

    source_roots: tuple[str, ...]
    source_files: tuple[str, ...] = ()
    dependency_package_roots: tuple[str, ...] = ("backend/app",)


DEFAULT_ALGORITHM_SOURCE_RULES = AlgorithmSourceManifestRules(
    source_roots=(
        "backend/app/engines",
        "backend/app/backtesting",
        "backend/app/schemas",
        "backend/app/market_data",
    ),
    source_files=(
        "backend/app/core/algorithm_identity.py",
        "backend/app/core/strategy_config.py",
        "backend/app/core/strategy_identity.py",
        "backend/app/services/snapshot_builder.py",
        "backend/app/services/strategy_evaluation.py",
    ),
)


@dataclass(frozen=True)
class SourceManifestEntry:
    relative_path: str
    content_hash: str


@dataclass(frozen=True)
class GitProvenance:
    """Informational repository provenance; never trusted as source identity."""

    git_available: bool
    git_commit_sha: str | None
    git_dirty: bool | None


@dataclass(frozen=True)
class AlgorithmBuildIdentity:
    algorithm_identity_schema_version: str
    source_manifest_schema_version: str
    source_content_hash: str
    algorithm_build_hash: str
    source_file_count: int
    git_available: bool
    git_commit_sha: str | None
    git_dirty: bool | None


def discover_algorithm_source_paths(
    repository_root: Path,
    rules: AlgorithmSourceManifestRules = DEFAULT_ALGORITHM_SOURCE_RULES,
) -> tuple[Path, ...]:
    """Discover seed source and its complete statically imported local closure."""

    root = _resolved_repository_root(repository_root)
    discovered: dict[str, Path] = {}
    for relative_root in rules.source_roots:
        source_root = _contained_path(root, relative_root)
        if not source_root.is_dir():
            raise AlgorithmIdentityError(
                f"required algorithm source root is unavailable: {relative_root}"
            )
        if source_root.is_symlink():
            raise AlgorithmIdentityError(
                f"algorithm source roots cannot be symlinks: {relative_root}"
            )
        try:
            candidates = source_root.rglob("*.py")
            for candidate in candidates:
                _add_source_path(root, candidate, discovered)
        except OSError as exc:
            raise AlgorithmIdentityError(
                f"failed to enumerate algorithm source root: {relative_root}"
            ) from exc

    for relative_file in rules.source_files:
        source_file = _contained_path(root, relative_file)
        if not source_file.is_file():
            raise AlgorithmIdentityError(
                f"required algorithm source file is unavailable: {relative_file}"
            )
        _add_source_path(root, source_file, discovered)

    if not discovered:
        raise AlgorithmIdentityError("algorithm source manifest cannot be empty")
    _expand_internal_dependency_closure(
        root,
        discovered,
        rules.dependency_package_roots,
    )
    return tuple(discovered[path] for path in sorted(discovered))


def build_source_manifest(
    repository_root: Path = REPOSITORY_ROOT,
    rules: AlgorithmSourceManifestRules = DEFAULT_ALGORITHM_SOURCE_RULES,
) -> tuple[SourceManifestEntry, ...]:
    root = _resolved_repository_root(repository_root)
    entries = []
    for path in discover_algorithm_source_paths(root, rules):
        relative_path = path.relative_to(root).as_posix()
        content = _read_normalized_source(path, relative_path)
        entries.append(
            SourceManifestEntry(
                relative_path=relative_path,
                content_hash=sha256(content).hexdigest(),
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.relative_path))


def canonical_source_manifest(entries: Iterable[SourceManifestEntry]) -> bytes:
    ordered = sorted(entries, key=lambda entry: entry.relative_path)
    paths = [entry.relative_path for entry in ordered]
    if len(paths) != len(set(paths)):
        raise AlgorithmIdentityError("algorithm source manifest contains duplicate paths")
    payload = {
        "entries": [
            {
                "content_sha256": entry.content_hash,
                "relative_path": entry.relative_path,
            }
            for entry in ordered
        ],
        "source_manifest_schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
    }
    return _canonical_json_bytes(payload)


def source_content_hash(
    repository_root: Path = REPOSITORY_ROOT,
    rules: AlgorithmSourceManifestRules = DEFAULT_ALGORITHM_SOURCE_RULES,
) -> str:
    return sha256(
        canonical_source_manifest(build_source_manifest(repository_root, rules))
    ).hexdigest()


def canonical_algorithm_identity_payload(source_hash: str) -> bytes:
    if len(source_hash) != 64 or any(
        character not in "0123456789abcdef" for character in source_hash
    ):
        raise AlgorithmIdentityError("source content hash must be lowercase SHA-256")
    return _canonical_json_bytes(
        {
            "algorithm_identity_schema_version": ALGORITHM_IDENTITY_SCHEMA_VERSION,
            "source_content_hash": source_hash,
        }
    )


def build_algorithm_identity(
    repository_root: Path = REPOSITORY_ROOT,
    rules: AlgorithmSourceManifestRules = DEFAULT_ALGORITHM_SOURCE_RULES,
) -> AlgorithmBuildIdentity:
    """Identify actual runtime source and attach untrusted-for-hash Git provenance."""

    manifest = build_source_manifest(repository_root, rules)
    source_hash = sha256(canonical_source_manifest(manifest)).hexdigest()
    build_hash = sha256(canonical_algorithm_identity_payload(source_hash)).hexdigest()
    provenance = _git_provenance(repository_root)
    return AlgorithmBuildIdentity(
        algorithm_identity_schema_version=ALGORITHM_IDENTITY_SCHEMA_VERSION,
        source_manifest_schema_version=SOURCE_MANIFEST_SCHEMA_VERSION,
        source_content_hash=source_hash,
        algorithm_build_hash=build_hash,
        source_file_count=len(manifest),
        git_available=provenance.git_available,
        git_commit_sha=provenance.git_commit_sha,
        git_dirty=provenance.git_dirty,
    )


def algorithm_build_hash() -> str:
    """Return the server-owned hash of actual outcome-affecting source content."""

    return build_algorithm_identity().algorithm_build_hash


def _read_normalized_source(path: Path, relative_path: str) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AlgorithmIdentityError(
            f"failed to read required algorithm source: {relative_path}"
        ) from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AlgorithmIdentityError(
            f"algorithm source is not valid UTF-8: {relative_path}"
        ) from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _resolved_repository_root(repository_root: Path) -> Path:
    try:
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise AlgorithmIdentityError("repository root is unavailable") from exc
    if not root.is_dir():
        raise AlgorithmIdentityError("repository root must be a directory")
    return root


def _canonical_relative_path(relative_path: str) -> str:
    candidate = PurePosixPath(relative_path.replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise AlgorithmIdentityError(
            f"invalid repository-relative algorithm source path: {relative_path}"
        )
    canonical = candidate.as_posix()
    if canonical in {".", ""}:
        raise AlgorithmIdentityError("algorithm source path cannot be empty")
    return canonical


def _contained_path(root: Path, relative_path: str) -> Path:
    canonical = _canonical_relative_path(relative_path)
    unresolved = root.joinpath(*PurePosixPath(canonical).parts)
    try:
        resolved = unresolved.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise AlgorithmIdentityError(
            f"algorithm source path escapes repository: {relative_path}"
        ) from exc
    return unresolved


def _add_source_path(root: Path, path: Path, discovered: dict[str, Path]) -> None:
    if not path.is_file():
        return
    if path.is_symlink():
        raise AlgorithmIdentityError(
            f"algorithm source files cannot be symlinks: {path.relative_to(root).as_posix()}"
        )
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise AlgorithmIdentityError("algorithm source escapes repository") from exc
    discovered[relative] = resolved


@dataclass(frozen=True)
class _DependencyPackage:
    relative_root: str
    path: Path
    module_name: str


@dataclass(frozen=True)
class _DependencyModuleIndex:
    known_modules: frozenset[str]
    source_by_module: dict[str, Path]
    initializer_by_package: dict[str, Path]


def _expand_internal_dependency_closure(
    root: Path,
    discovered: dict[str, Path],
    relative_package_roots: tuple[str, ...],
) -> None:
    packages = tuple(
        _dependency_package(root, relative_root)
        for relative_root in relative_package_roots
    )
    if len({package.module_name for package in packages}) != len(packages):
        raise AlgorithmIdentityError("dependency package module names must be unique")
    module_indexes = {
        package.module_name: _build_dependency_module_index(package)
        for package in packages
    }
    processed: set[str] = set()
    known_paths = set(discovered.values())

    while True:
        pending = sorted(set(discovered) - processed)
        if not pending:
            return
        relative_path = pending[0]
        processed.add(relative_path)
        source_path = discovered[relative_path]
        package = _package_for_source(source_path, packages)
        if package is None:
            continue

        module_name, is_package = _module_name_for_source(source_path, package)
        for initializer in _package_initializers(source_path, package):
            _add_dependency_source_path(root, initializer, discovered, known_paths)

        source = _read_normalized_source(source_path, relative_path)
        try:
            tree = ast.parse(source.decode("utf-8"), filename=relative_path)
        except SyntaxError as exc:
            raise AlgorithmIdentityError(
                f"failed to parse algorithm source imports: {relative_path}"
            ) from exc

        for imported_module, required in _internal_imports(
            tree,
            module_name=module_name,
            is_package=is_package,
            package=package,
        ):
            resolved, paths = _resolve_internal_module(
                imported_module,
                package,
                module_indexes[package.module_name],
            )
            if required and not resolved:
                raise AlgorithmIdentityError(
                    "required internal algorithm dependency is unavailable: "
                    f"{imported_module} (imported by {relative_path})"
                )
            for dependency in paths:
                _add_dependency_source_path(root, dependency, discovered, known_paths)


def _add_dependency_source_path(
    root: Path,
    path: Path,
    discovered: dict[str, Path],
    known_paths: set[Path],
) -> None:
    if path in known_paths:
        return
    _add_source_path(root, path, discovered)
    known_paths.add(path)


def _dependency_package(root: Path, relative_root: str) -> _DependencyPackage:
    canonical = _canonical_relative_path(relative_root)
    package_path = _contained_path(root, canonical)
    if not package_path.is_dir():
        raise AlgorithmIdentityError(
            f"required dependency package root is unavailable: {relative_root}"
        )
    if package_path.is_symlink():
        raise AlgorithmIdentityError(
            f"dependency package roots cannot be symlinks: {relative_root}"
        )
    module_name = PurePosixPath(canonical).name
    if not module_name.isidentifier():
        raise AlgorithmIdentityError(
            f"dependency package root is not a Python package: {relative_root}"
        )
    return _DependencyPackage(canonical, package_path.resolve(strict=True), module_name)


def _build_dependency_module_index(
    package: _DependencyPackage,
) -> _DependencyModuleIndex:
    known_modules = {package.module_name}
    source_by_module: dict[str, Path] = {}
    initializer_by_package: dict[str, Path] = {}
    try:
        candidates = package.path.rglob("*.py")
        for candidate in candidates:
            relative = candidate.relative_to(package.path)
            source_parts = list(relative.with_suffix("").parts)
            is_package = bool(source_parts and source_parts[-1] == "__init__")
            if is_package:
                source_parts.pop()
            module_parts = [package.module_name, *source_parts]
            if any(not part.isidentifier() for part in module_parts):
                continue
            module_name = ".".join(module_parts)
            if module_name in source_by_module:
                raise AlgorithmIdentityError(
                    f"duplicate internal Python module: {module_name}"
                )
            source_by_module[module_name] = candidate
            if is_package:
                initializer_by_package[module_name] = candidate
            for index in range(1, len(module_parts) + 1):
                known_modules.add(".".join(module_parts[:index]))
    except OSError as exc:
        raise AlgorithmIdentityError(
            f"failed to enumerate dependency package root: {package.relative_root}"
        ) from exc
    return _DependencyModuleIndex(
        known_modules=frozenset(known_modules),
        source_by_module=source_by_module,
        initializer_by_package=initializer_by_package,
    )


def _package_for_source(
    source_path: Path,
    packages: tuple[_DependencyPackage, ...],
) -> _DependencyPackage | None:
    matches: list[_DependencyPackage] = []
    for package in packages:
        try:
            source_path.relative_to(package.path)
        except ValueError:
            continue
        matches.append(package)
    if not matches:
        return None
    return max(matches, key=lambda package: len(package.path.parts))


def _module_name_for_source(
    source_path: Path,
    package: _DependencyPackage,
) -> tuple[str, bool]:
    relative = source_path.relative_to(package.path)
    if relative.suffix != ".py":
        raise AlgorithmIdentityError("algorithm dependency source must be Python")
    parts = list(relative.with_suffix("").parts)
    is_package = bool(parts and parts[-1] == "__init__")
    if is_package:
        parts.pop()
    module_parts = [package.module_name, *parts]
    if any(not part.isidentifier() for part in module_parts):
        raise AlgorithmIdentityError(
            f"algorithm source path is not importable: {source_path.as_posix()}"
        )
    return ".".join(module_parts), is_package


def _package_initializers(
    source_path: Path,
    package: _DependencyPackage,
) -> tuple[Path, ...]:
    relative = source_path.relative_to(package.path)
    parent_parts = relative.parent.parts
    initializers: list[Path] = []
    current = package.path
    root_initializer = current / "__init__.py"
    if root_initializer.is_file():
        initializers.append(root_initializer)
    for part in parent_parts:
        current /= part
        initializer = current / "__init__.py"
        if initializer.is_file():
            initializers.append(initializer)
    return tuple(initializers)


def _internal_imports(
    tree: ast.AST,
    *,
    module_name: str,
    is_package: bool,
    package: _DependencyPackage,
) -> tuple[tuple[str, bool], ...]:
    imports: set[tuple[str, bool]] = set()
    current_package = module_name if is_package else module_name.rpartition(".")[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_internal_module(alias.name, package):
                    imports.add((alias.name, True))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        base = _resolve_import_from_base(node, current_package)
        if base is None or not _is_internal_module(base, package):
            continue
        imports.add((base, True))
        for alias in node.names:
            if alias.name == "*":
                continue
            imports.add((f"{base}.{alias.name}", False))

    return tuple(sorted(imports))


def _resolve_import_from_base(
    node: ast.ImportFrom,
    current_package: str,
) -> str | None:
    if node.level == 0:
        return node.module
    package_parts = current_package.split(".") if current_package else []
    parents_to_remove = node.level - 1
    if parents_to_remove > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - parents_to_remove]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts) or None


def _is_internal_module(module_name: str, package: _DependencyPackage) -> bool:
    return module_name == package.module_name or module_name.startswith(
        f"{package.module_name}."
    )


def _resolve_internal_module(
    module_name: str,
    package: _DependencyPackage,
    module_index: _DependencyModuleIndex,
) -> tuple[bool, tuple[Path, ...]]:
    if not _is_internal_module(module_name, package):
        return False, ()
    if module_name not in module_index.known_modules:
        return False, ()
    module_parts = module_name.split(".")
    paths: list[Path] = []
    for index in range(1, len(module_parts) + 1):
        package_name = ".".join(module_parts[:index])
        initializer = module_index.initializer_by_package.get(package_name)
        if initializer is not None:
            paths.append(initializer)
    source = module_index.source_by_module.get(module_name)
    if source is not None and source not in paths:
        paths.append(source)
    return True, tuple(paths)


def _git_provenance(repository_root: Path) -> GitProvenance:
    root = _resolved_repository_root(repository_root)
    try:
        inside = _run_git(root, "rev-parse", "--is-inside-work-tree")
        if inside.strip().lower() != "true":
            return GitProvenance(False, None, None)
        commit: str | None = _run_git(
            root, "rev-parse", "--verify", "HEAD"
        ).strip().lower()
        if not commit or any(character not in "0123456789abcdef" for character in commit):
            commit = None
        status = _run_git(root, "status", "--porcelain", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError):
        return GitProvenance(False, None, None)
    return GitProvenance(True, commit, bool(status.strip()))


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
        timeout=5,
    )
    return result.stdout


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
