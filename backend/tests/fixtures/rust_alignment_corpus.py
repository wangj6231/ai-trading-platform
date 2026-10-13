"""Seal Python-oracle alignment evidence BEFORE native verification. No prices."""
from dataclasses import asdict
from hashlib import sha256
import json

from app.market_data.rust_alignment import RustComputeInputV1, python_alignment_oracle
from app.market_data.timeframes import timeframe_duration
from app.schemas.types import Timeframe
from tests.fixtures.rust_core_evidence import ARTIFACTS


def corpus() -> list[dict]:
    rows = []
    for timeframe in Timeframe:
        interval = timeframe_duration(timeframe) // timeframe_duration(Timeframe.ONE_MINUTE) * 60_000_000
        anchor = -259_200_000_000 if timeframe is Timeframe.ONE_WEEK else 0
        for label, values in (
            ("empty", ()), ("aligned", (anchor, anchor + interval)),
            ("negative", (anchor - interval, anchor)), ("microsecond", (anchor + 1,)),
            ("first_error", (anchor, anchor + 1, anchor + 2)),
            ("duplicate", (anchor, anchor)), ("unordered", (anchor + interval, anchor)),
            ("range_edges", (-62_135_596_800_000_000, 253_402_300_799_999_999)),
        ):
            value = RustComputeInputV1(timeframe, values)
            error = None
            try:
                output = asdict(python_alignment_oracle(value))
            except (OSError, ValueError, OverflowError) as exc:
                output = None
                error = type(exc).__name__
            encoded = json.dumps(output if error is None else {"error": error}, separators=(",", ":")).encode("ascii")
            rows.append({"label": f"{timeframe.value}:{label}", "contract_version": "1",
                "input": json.loads(value.encode()), "expected_output": output, "expected_error": error,
                "input_hash": sha256(value.encode()).hexdigest(), "output_hash": sha256(encoded).hexdigest()})
    return rows


def seal() -> None:
    destination = ARTIFACTS / "python_oracle_corpus.json"
    if destination.exists():
        raise ValueError("oracle corpus already sealed; refuse overwrite")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(corpus(), sort_keys=True, indent=2), encoding="utf8")
    print(json.dumps({"cases": len(corpus()), "sha256": sha256(destination.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    seal()
