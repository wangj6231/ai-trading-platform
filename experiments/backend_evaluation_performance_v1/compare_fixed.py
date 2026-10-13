"""Use the existing canonical snapshot hash to compare complete frozen results."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from app.database.snapshot_integrity import canonical_sha256


def main(args):
    contract = json.loads((OUT / "baseline_contract.json").read_text(encoding="utf-8"))
    changed = [path for path, digest in contract["source_hashes"].items()
               if sha256((ROOT / path).read_bytes()).hexdigest() != digest]
    frozen_changed = [path for path in changed if (path.startswith("frontend/") and not args.allow_authorized_async_frontend)
                      or path.startswith("config/") or path.startswith("backend/app/schemas/")]
    assert not frozen_changed, frozen_changed
    if args.allow_authorized_async_frontend:
        async_contract = json.loads((OUT / 'async_contract_baseline.json').read_text(encoding='utf-8'))
        for path, digest in async_contract['existing_backend_api_schema_sha256'].items():
            assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
        assert sha256((ROOT / 'config/strategy.yaml').read_bytes()).hexdigest() == async_contract['strategy_config_sha256']
        proxy = 'frontend/src/lib/backend-proxy.ts'
        assert sha256((ROOT / proxy).read_bytes()).hexdigest() == contract['source_hashes'][proxy]
    reference_meta = json.loads((OUT / f"{args.before_label}_fixed_meta.json").read_text(encoding="utf-8"))
    after_meta = json.loads((OUT / f"{args.label}_fixed_meta.json").read_text(encoding="utf-8"))
    for key in ("symbol", "cutoff", "history_hash", "provider", "bars"):
        assert reference_meta[key] == after_meta[key], key
    # Full equality under a fixed explicit comparison identity; actual build
    # identities remain separately reported because source edits change them.
    reference = json.loads((OUT / f"{args.before_label}_fixed_result.json").read_text(encoding="utf-8"))
    before_hash = canonical_sha256(reference)
    del reference
    after = json.loads((OUT / f"{args.label}_fixed_result.json").read_text(encoding="utf-8"))
    after_hash = canonical_sha256(after)
    assert before_hash == after_hash, "Complete evidence differs; stop performance work and fix correctness"
    row = {"label": args.label, "equivalence": "PASS", "comparison": "complete result; existing canonical_sha256; exact values, no tolerance",
           "before_hash": before_hash, "after_hash": after_hash,
           "actual_before_identity": reference_meta["actual_strategy_identity"],
           "actual_after_identity": after_meta["actual_strategy_identity"],
           "frozen_frontend_config_schemas": "EXISTING BACKEND SCHEMAS / CONFIG / PROXY UNCHANGED; FRONTEND ASYNC CHANGES EXPLICITLY AUTHORIZED" if args.allow_authorized_async_frontend else "UNCHANGED", "changed_existing_sources": changed}
    (OUT / f"{args.label}_equivalence.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(row))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--before-label", default="before")
    parser.add_argument('--allow-authorized-async-frontend', action='store_true')
    main(parser.parse_args())
