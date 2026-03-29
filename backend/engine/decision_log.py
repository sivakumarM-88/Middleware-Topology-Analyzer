"""Decision logging for every topology transformation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class DecisionRecord:
    stage: str
    action: str
    subject_type: str
    subject_id: str
    description: str
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    from_state: Dict[str, Any] = field(default_factory=dict)
    to_state: Dict[str, Any] = field(default_factory=dict)
    complexity_delta: float = 0.0
    confidence: float = 1.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "stage": self.stage,
            "action": self.action,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "description": self.description,
            "reason": self.reason,
            "evidence": self.evidence,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "complexity_delta": self.complexity_delta,
            "confidence": self.confidence,
        }


class DecisionLog:
    """Manages a list of decision records with filtering capabilities."""

    def __init__(self) -> None:
        self._records: List[DecisionRecord] = []

    def record(self, **kwargs) -> DecisionRecord:
        rec = DecisionRecord(**kwargs)
        self._records.append(rec)
        return rec

    @property
    def records(self) -> List[DecisionRecord]:
        return list(self._records)

    def filter_by_stage(self, stage: str) -> List[DecisionRecord]:
        return [r for r in self._records if r.stage == stage]

    def filter_by_subject(self, subject_id: str) -> List[DecisionRecord]:
        return [r for r in self._records if r.subject_id == subject_id]

    def filter_by_action(self, action: str) -> List[DecisionRecord]:
        return [r for r in self._records if r.action == action]

    def last_n(self, n: int = 50) -> List[DecisionRecord]:
        return self._records[-n:]

    def to_list(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._records]

    def __len__(self) -> int:
        return len(self._records)
