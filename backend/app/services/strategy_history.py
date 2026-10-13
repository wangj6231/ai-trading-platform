"""Server-owned history sizing; never selects a direction or changes a level."""
from datetime import datetime

from app.market_data.timeframes import timeframe_bucket_start, timeframe_duration
from app.schemas.strategy import DeterministicStrategyPipelineConfig


def strategy_history_start(
    pipeline: DeterministicStrategyPipelineConfig, cutoff: datetime,
) -> datetime:
    """Acquire enough complete buckets, including the optional context targets.

    Requested capacity is not an availability vote: each timeframe is assessed
    independently by the deterministic engine. No fixed candle count can cover
    52 closed weeks at every possible intra-week cutoff.
    """
    minimum = pipeline.minimum_history_by_timeframe
    targets = pipeline.multi_timeframe.mtf_target_timeframes
    earliest = min(timeframe_bucket_start(cutoff, tf) - minimum[tf] * timeframe_duration(tf)
                   for tf in targets)
    # Every supplied target starts on a full UTC boundary. For the approved
    # domain the largest bucket is ISO Monday, also a valid day/hour boundary.
    largest = max(targets, key=timeframe_duration)
    return timeframe_bucket_start(earliest, largest)
