"""编排层：把 preprocess → parser → validators → renderer 串成一条可跑通的链路。"""

from __future__ import annotations

from qqe.orchestrator.pipeline import PipelineResult, run_pipeline
from qqe.orchestrator.state import (
    EXPORTABLE_STATES,
    TRANSITIONS,
    BatchState,
    BatchStateMachine,
    IllegalTransition,
)

__all__ = [
    "EXPORTABLE_STATES",
    "TRANSITIONS",
    "BatchState",
    "BatchStateMachine",
    "IllegalTransition",
    "PipelineResult",
    "run_pipeline",
]
