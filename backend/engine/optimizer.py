"""Optimization pipeline orchestrator - chains stages 0-5."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .community import CommunityDetector
from .constraints import ConstraintEnforcer
from .decision_log import DecisionLog
from .discovery import GraphDiscovery
from .hub_election import HubElector
from .model import TopologyModel
from .pruner import DeadObjectPruner
from .rationalizer import Rationalizer
from .scorer import ComplexityMetrics, ComplexityScorer


@dataclass
class StageResult:
    stage_name: str
    metrics_before: ComplexityMetrics
    metrics_after: ComplexityMetrics
    complexity_delta: float = 0.0

    def to_dict(self) -> dict:
        return {
            "stage_name": self.stage_name,
            "metrics_before": self.metrics_before.to_dict(),
            "metrics_after": self.metrics_after.to_dict(),
            "complexity_delta": round(self.complexity_delta, 2),
        }


@dataclass
class OptimizationResult:
    as_is_model: TopologyModel
    target_model: TopologyModel
    as_is_metrics: ComplexityMetrics
    target_metrics: ComplexityMetrics
    stage_results: List[StageResult] = field(default_factory=list)
    decision_log: DecisionLog = field(default_factory=DecisionLog)

    @property
    def complexity_reduction_pct(self) -> float:
        if self.as_is_metrics.composite_score == 0:
            return 0.0
        delta = self.as_is_metrics.composite_score - self.target_metrics.composite_score
        return round(delta / self.as_is_metrics.composite_score * 100, 1)

    def to_dict(self) -> dict:
        return {
            "as_is_summary": self.as_is_model.summary(),
            "target_summary": self.target_model.summary(),
            "as_is_metrics": self.as_is_metrics.to_dict(),
            "target_metrics": self.target_metrics.to_dict(),
            "complexity_reduction_pct": self.complexity_reduction_pct,
            "stages": [s.to_dict() for s in self.stage_results],
            "decision_count": len(self.decision_log),
        }


class OptimizationPipeline:
    """Orchestrates the 6-stage optimization pipeline."""

    def __init__(self, scorer: ComplexityScorer | None = None):
        self.scorer = scorer or ComplexityScorer()

    def run(self, model: TopologyModel, resolution: float = 1.0) -> OptimizationResult:
        log = DecisionLog()

        # Snapshot the as-is model (pre-discovery, for reference)
        as_is_model = model.deep_copy()

        stage_results: List[StageResult] = []

        # Stage 0: Graph Discovery — infer channels not present in input
        model, sr = self._run_stage(
            "Stage 0: Graph Discovery",
            GraphDiscovery(log),
            model,
        )
        stage_results.append(sr)

        # Use post-discovery score as the true as-is baseline
        # (channels don't exist in raw CSV, so pre-discovery score is misleading)
        as_is_metrics = self.scorer.score(model)
        as_is_model = model.deep_copy()

        # Stage 1: Constraint Enforcement
        model, sr = self._run_stage(
            "Stage 1: Constraint Enforcement",
            ConstraintEnforcer(log),
            model,
        )
        stage_results.append(sr)

        # Stage 2: Dead Object Pruning
        model, sr = self._run_stage(
            "Stage 2: Dead Object Pruning",
            DeadObjectPruner(log),
            model,
        )
        stage_results.append(sr)

        # Stage 3: Community Detection (resolution tunable: >1 = smaller, <1 = larger)
        model, sr = self._run_stage(
            "Stage 3: Community Detection",
            CommunityDetector(log, resolution=resolution),
            model,
        )
        stage_results.append(sr)

        # Stage 4: Hub Election + Spoke Wiring
        model, sr = self._run_stage(
            "Stage 4: Hub Election",
            HubElector(log),
            model,
        )
        stage_results.append(sr)

        # Stage 5: Rationalization
        model, sr = self._run_stage(
            "Stage 5: Rationalization",
            Rationalizer(log),
            model,
        )
        stage_results.append(sr)

        target_metrics = self.scorer.score(model)
        model.decision_log = log.records

        return OptimizationResult(
            as_is_model=as_is_model,
            target_model=model,
            as_is_metrics=as_is_metrics,
            target_metrics=target_metrics,
            stage_results=stage_results,
            decision_log=log,
        )

    def _run_stage(
        self,
        stage_name: str,
        stage,
        model: TopologyModel,
    ) -> tuple[TopologyModel, StageResult]:
        metrics_before = self.scorer.score(model)
        model = stage.run(model)
        metrics_after = self.scorer.score(model)

        delta = metrics_after.composite_score - metrics_before.composite_score

        return model, StageResult(
            stage_name=stage_name,
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            complexity_delta=delta,
        )
