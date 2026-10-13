"""Bounded registry-only lock review + advisory lookup, not a security proof."""
from hashlib import sha256
import json
import tomllib

import httpx

from tests.fixtures.rust_core_evidence import ARTIFACTS, ROOT


def run() -> None:
    path = ROOT / "rust/utc_alignment/Cargo.lock"
    packages = tomllib.loads(path.read_text(encoding="utf8"))["package"]
    if len(packages) > 100 or any(p.get("source", "").startswith("git+") for p in packages):
        raise ValueError("unsupported lockfile dependency policy")
    registry = [p for p in packages if "source" in p]
    queries = [{"package": {"name": p["name"], "ecosystem": "crates.io"}, "version": p["version"]} for p in registry]
    result = {"lock_hash": sha256(path.read_bytes()).hexdigest(), "registry_dependencies": len(registry),
        "git_dependencies": 0, "packages": [{"name": p["name"], "version": p["version"]} for p in registry]}
    try:
        with httpx.stream("POST", "https://api.osv.dev/v1/querybatch", json={"queries": queries}, timeout=30) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes(65536):
                if len(body) + len(chunk) > 1_048_576:
                    raise ValueError("advisory response size cap")
                body.extend(chunk)
        records = json.loads(body)["results"]
        if len(records) != len(queries):
            raise ValueError("advisory response cardinality")
        result.update(scan="EXECUTED", vulnerabilities=[{"package": p["name"], "version": p["version"],
            "ids": [v["id"] for v in r.get("vulns", [])]} for p, r in zip(registry, records, strict=True) if r.get("vulns")])
    except (httpx.HTTPError, ValueError, KeyError):
        result.update(scan="UNAVAILABLE", vulnerabilities=None)
    (ARTIFACTS / "dependency_scan.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    run()
