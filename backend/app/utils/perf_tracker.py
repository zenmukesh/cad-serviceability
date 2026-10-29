"""
Performance and request timing instrumentation tracker.
Tracks request durations and heavy geometry analysis invocation counts.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
import logging
from typing import Dict

logger = logging.getLogger("timing_middleware")

# Global invocation counters for heavy analysis functions
_COUNTERS: Dict[str, int] = {
    "compute_serviceability_scoring": 0,
    "build_disassembly_graph": 0,
    "analyze_clearances": 0,
    "analyze_component_obstructions": 0,
    "get_assembly_shapes": 0,
}

def record_call(function_name: str) -> None:
    if function_name in _COUNTERS:
        _COUNTERS[function_name] += 1
    else:
        _COUNTERS[function_name] = 1

def get_call_counts() -> Dict[str, int]:
    return dict(_COUNTERS)

def reset_call_counts() -> None:
    for k in _COUNTERS:
        _COUNTERS[k] = 0
