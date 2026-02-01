"""Export destinations — file and webhook exporters for per-source output.

These run after Parquet write as optional supplementary exports.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anysite.dataset.models import ExportDestination

logger = logging.getLogger(__name__)


async def run_exports(
    records: list[dict[str, Any]],
    exports: list[ExportDestination],
    source_id: str,
    dataset_name: str,
) -> None:
    """Run all export destinations for a source's records."""
    for export in exports:
        try:
            if export.type == "file":
                await _export_file(records, export, source_id, dataset_name)
            elif export.type == "webhook":
                await _export_webhook(records, export, source_id, dataset_name)
        except Exception as e:
            logger.error("Export %s failed for source %s: %s", export.type, source_id, e)


async def _export_file(
    records: list[dict[str, Any]],
    config: ExportDestination,
    source_id: str,
    dataset_name: str,
) -> None:
    """Write records to a file (JSON, JSONL, or CSV)."""
    if not config.path or not records:
        return

    path = _expand_template(config.path, source_id, dataset_name)
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)

    fmt = config.format.lower()

    if fmt == "jsonl":
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, default=str, ensure_ascii=False) + "\n")
    elif fmt == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, default=str, ensure_ascii=False, indent=2)
    elif fmt == "csv":
        if not records:
            return
        fieldnames = list(records[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow({k: _csv_value(v) for k, v in r.items()})
    else:
        raise ValueError(f"Unsupported export format: {fmt}")

    logger.info("Exported %d records to %s (%s)", len(records), path, fmt)


async def _export_webhook(
    records: list[dict[str, Any]],
    config: ExportDestination,
    source_id: str,
    dataset_name: str,
) -> None:
    """POST records to a webhook URL."""
    if not config.url or not records:
        return

    import httpx

    payload = {
        "dataset": dataset_name,
        "source": source_id,
        "count": len(records),
        "records": records,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            config.url,
            json=payload,
            headers=config.headers,
        )
        resp.raise_for_status()

    logger.info("Exported %d records to webhook %s", len(records), config.url)


def _expand_template(path: str, source_id: str, dataset_name: str) -> str:
    """Expand {{date}}, {{datetime}}, {{source}}, {{dataset}} placeholders."""
    now = datetime.now(UTC)
    return (
        path.replace("{{date}}", now.strftime("%Y-%m-%d"))
        .replace("{{datetime}}", now.strftime("%Y-%m-%dT%H%M%S"))
        .replace("{{source}}", source_id)
        .replace("{{dataset}}", dataset_name)
    )


def _csv_value(v: Any) -> Any:
    """Convert complex values to strings for CSV output."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str, ensure_ascii=False)
    return v
