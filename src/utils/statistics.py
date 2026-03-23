"""Utility for tracking aggregate statistics across pipeline stages and steps."""

import json
import os
import re
from datetime import datetime
from typing import Any

from src.paths import AGGREGATE_STATISTICS_PATH


def _load_stats() -> dict[str, Any]:
    """Load existing statistics JSON, or return empty structure."""
    if os.path.exists(AGGREGATE_STATISTICS_PATH):
        try:
            with open(AGGREGATE_STATISTICS_PATH) as f:
                result: dict[str, Any] = json.load(f)
                return result
        except Exception:
            pass
    return {"last_updated": None}


def _save_stats(data: dict[str, Any]) -> None:
    """Save statistics JSON atomically."""
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parent = os.path.dirname(AGGREGATE_STATISTICS_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = AGGREGATE_STATISTICS_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, AGGREGATE_STATISTICS_PATH)


def _step_sort_key(step_name: str) -> int:
    """Extract step number for sorting."""
    match = re.search(r"Step (\d+)", step_name)
    return int(match.group(1)) if match else 999


def update_statistics(stage_name: str, step_name: str, stats: dict[str, Any]) -> None:
    """
    Update the aggregate statistics file with new stats for a stage/step.

    Args:
        stage_name: Name of the stage (e.g., "Stage 1: Generate Clean Data").
        step_name: Name of the step (e.g., "Step 3: Employee Directory").
        stats: Dictionary of statistics to record.
    """
    data = _load_stats()

    if stage_name not in data:
        data[stage_name] = {}

    data[stage_name][step_name] = stats

    # Sort steps within each stage by step number
    for stage_key in list(data.keys()):
        if stage_key == "last_updated":
            continue
        stage_data = data[stage_key]
        if isinstance(stage_data, dict):
            data[stage_key] = dict(
                sorted(stage_data.items(), key=lambda x: _step_sort_key(x[0]))
            )

    _save_stats(data)
