from typing import Protocol

from app.schemas.strategy import StrategyConfig, StrategyEvaluationContext, StrategyEvaluationResult
from app.schemas.strategy_identity import StrategyIdentity


class DeterministicStrategyEngine(Protocol):
    """The single strategy boundary used by live analysis and backtests.

    OpenAI validation is deliberately outside this protocol.
    """

    @property
    def strategy_identity(self) -> StrategyIdentity: ...

    @property
    def strategy_config(self) -> StrategyConfig: ...

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult: ...
