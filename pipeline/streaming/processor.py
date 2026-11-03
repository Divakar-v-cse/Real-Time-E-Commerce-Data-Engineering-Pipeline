"""Micro-batch stream processor (local equivalent of the Spark Structured Streaming job).

Runs the same logical plan as ``spark_job.py``:

    Kafka topic -> Bronze (raw Parquet, partitioned by event_date)
                -> validate / deduplicate / normalise timestamps
                -> Silver (clean Parquet + warehouse upserts)
                -> Gold (daily aggregates in Parquet and analytics.sales_daily)

Processing guarantees / rules implemented here
-----------------------------------------------
* schema validation with per-record quarantine (never aborts the batch)
* deduplication by ``order_id`` (batch-local + warehouse existence check)
* null handling and timestamp normalisation to UTC
* business rules: recomputed totals, discount clamped to [0, 1], status whitelist
* late-arriving events inside the tolerance window are accepted and the affected
  day is re-aggregated; older ones are accepted into Bronze but flagged
* failure isolation per record; the batch itself is tracked in ``ops.pipeline_runs``
* metrics (processed / rejected / latency / consumer lag) go to ``ops.pipeline_metrics``
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from common.db import get_engine, session_scope
from common.logging import configure_logging
from common.settings import LAKE_DIR, settings
from pipeline.generator.schemas import TOPIC_DLQ, TOPIC_ORDERS, validate_order_event
from pipeline.streaming.broker import Record, broker
from warehouse.load import finish_run, record_metric, start_run
from warehouse.stream_sink import (
    ensure_gold_layer,
    record_event,
    refresh_gold,
    set_watermark,
    upsert_order,
    upsert_order_items,
    upsert_payment,
    upsert_return,
    upsert_shipment,
)

CONSUMER_GROUP = "ecommerce-streaming-v1"
STATUSES = {"completed", "processing", "pending", "cancelled", "returned"}


@dataclass
class BatchResult:
    batch_id: str
    run_id: int | None = None
    consumed: dict[str, int] = field(default_factory=dict)
    bronze_rows: int = 0
    silver_rows: int = 0
    rejected: int = 0
    duplicates: int = 0
    late_events: int = 0
    warehouse_rows: int = 0
    gold_days: int = 0
    latency_ms: float = 0.0
    duration_ms: float = 0.0
    consumer_lag: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "run_id": self.run_id,
            "consumed": self.consumed,
            "bronze_rows": self.bronze_rows,
            "silver_rows": self.silver_rows,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "late_events": self.late_events,
            "warehouse_rows": self.warehouse_rows,
            "gold_days": self.gold_days,
            "latency_ms": self.latency_ms,
            "duration_ms": self.duration_ms,
            "consumer_lag": self.consumer_lag,
            "errors": self.errors[:5],
        }


def _event_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write_parquet(records: list[Record], layer: str, topic: str, batch_id: str) -> int:
    if not records:
        return 0
    rows = []
    for rec in records:
        payload: dict[str, Any] = {}
        for key, value in rec.value.items():
            # Parquet needs a uniform column type: nested structures become JSON text.
            payload[key] = json.dumps(value) if isinstance(value, (list, dict)) else value
        payload["_kafka_topic"] = rec.topic
        payload["_kafka_partition"] = rec.partition
        payload["_kafka_offset"] = rec.offset
        payload["_produced_at"] = rec.produced_at
        payload["_event_date"] = _event_date(rec.value.get("event_ts") or rec.value.get("order_ts"))
        rows.append(payload)
    frame = pd.DataFrame(rows)
    written = 0
    for day, group in frame.groupby("_event_date"):
        target = Path(LAKE_DIR) / layer / topic / f"dt={day}"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"part-{batch_id}.parquet"
        group.to_parquet(path, index=False, compression="snappy")
        written += len(group)
    return written


class StreamProcessor:
    def __init__(
        self,
        batch_size: int = 400,
        tolerance_days: int | None = None,
        group: str = CONSUMER_GROUP,
    ) -> None:
        self.batch_size = batch_size
        self.tolerance_days = settings.late_arrival_tolerance_days if tolerance_days is None else tolerance_days
        self.group = group
        self._seen: set[str] = set()

    # ---------------------------------------------------------------- silver
    def _clean_order(self, order: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        result = validate_order_event(order)
        if not result.ok:
            return None, "; ".join(result.errors[:3])

        items = order.get("items") or []
        if not items:
            return None, "no order items"

        # business rules ----------------------------------------------------
        subtotal = 0.0
        discount = 0.0
        cleaned_items = []
        for item in items:
            qty = int(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            disc = min(max(float(item.get("discount_pct") or 0), 0.0), 1.0)
            if qty <= 0 or price < 0:
                return None, "invalid line quantity/price"
            subtotal += qty * price
            discount += qty * price * disc
            cleaned_items.append({**item, "quantity": qty, "unit_price": price, "discount_pct": disc})

        subtotal = round(subtotal, 2)
        discount = round(discount, 2)
        net = round(subtotal - discount, 2)
        shipping = float(order.get("shipping_total") or 0)
        if shipping < 0:
            shipping = 0.0
        total = round(net + shipping, 2)

        status = str(order.get("status") or "pending").lower()
        if status not in STATUSES:
            status = "pending"

        ts = datetime.fromisoformat(str(order["order_ts"]).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        cleaned = {
            **order,
            "items": cleaned_items,
            "item_count": sum(i["quantity"] for i in cleaned_items),
            "subtotal": subtotal,
            "discount_total": discount,
            "shipping_total": shipping,
            "order_total": total,
            "status": status,
            "order_ts": ts.astimezone(timezone.utc).isoformat(),
            "event_ts": ts.astimezone(timezone.utc).isoformat(),
        }
        return cleaned, None

    # ------------------------------------------------------------------ batch
    def process_once(self, topics: list[str] | None = None) -> BatchResult:
        topics = topics or [TOPIC_ORDERS]
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        started = time.perf_counter()
        result = BatchResult(batch_id=batch_id)
        ensure_gold_layer()
        result.run_id = start_run("streaming_micro_batch", "micro_batch", {"batch_id": batch_id})

        try:
            collected: dict[str, list[Record]] = {}
            for topic in [TOPIC_ORDERS, "ecom.payments.raw", "ecom.shipments.raw", "ecom.returns.raw"]:
                collected[topic] = broker.consume(topic, self.group, self.batch_size)
                result.consumed[topic] = len(collected[topic])
            result.consumer_lag = {
                topic: broker.lag(topic, self.group)
                for topic in ["ecom.orders.raw", "ecom.payments.raw", "ecom.shipments.raw", "ecom.returns.raw"]
            }

            orders = collected[TOPIC_ORDERS]
            result.bronze_rows = sum(
                _write_parquet(records, "bronze", topic, batch_id) for topic, records in collected.items()
            )

            watermark_row = self._watermark()
            tolerance = (watermark_row or datetime.now(timezone.utc)) - timedelta(days=self.tolerance_days)

            silver: list[dict[str, Any]] = []
            with session_scope() as session:
                existing = set()
                ids = [o.value.get("order_id") for o in orders if o.value.get("order_id")]
                if ids:
                    rows = session.execute(
                        _text("SELECT order_id FROM warehouse.fact_orders WHERE order_id = ANY(:ids)"),
                        {"ids": ids},
                    )
                    existing = {r[0] for r in rows}

                for rec in orders:
                    payload = rec.value
                    order_id = payload.get("order_id")
                    if not order_id:
                        result.rejected += 1
                        broker.produce(TOPIC_DLQ, "missing-id", {"errors": ["missing order_id"], "payload": payload})
                        continue
                    if order_id in self._seen:
                        result.duplicates += 1
                        continue
                    if order_id in existing:
                        result.duplicates += 1
                        continue

                    cleaned, error = self._clean_order(payload)
                    if cleaned is None:
                        result.rejected += 1
                        broker.produce(
                            TOPIC_DLQ,
                            order_id,
                            {"order_id": order_id, "errors": [error], "payload": payload,
                             "event_ts": payload.get("event_ts")},
                        )
                        record_event(session, rec.topic, rec.partition, rec.offset, order_id,
                                     self._parse(rec), "silver", "rejected", error)
                        continue

                    event_ts = datetime.fromisoformat(cleaned["order_ts"])
                    if event_ts < tolerance:
                        result.late_events += 1
                        cleaned["_late"] = True
                    self._seen.add(order_id)
                    silver.append(cleaned)
                    record_event(session, rec.topic, rec.partition, rec.offset, order_id,
                                 event_ts, "silver", "accepted", None)

                # warehouse upserts (idempotent) --------------------------------
                affected_dates = set()
                for order in silver:
                    try:
                        upsert_order(session, order)
                        upsert_order_items(session, order["order_id"], order.get("items") or [])
                        result.warehouse_rows += 1
                        affected_dates.add(datetime.fromisoformat(order["order_ts"]).date())
                    except Exception as exc:  # isolate the bad record
                        result.errors.append(f"{order.get('order_id')}: {exc}")
                        session.rollback()

                for payment in collected["ecom.payments.raw"]:
                    try:
                        upsert_payment(session, payment.value)
                    except Exception as exc:
                        result.errors.append(f"payment {payment.key}: {exc}")
                        session.rollback()

                for shipment in collected["ecom.shipments.raw"]:
                    try:
                        upsert_shipment(session, shipment.value)
                    except Exception as exc:
                        result.errors.append(f"shipment {shipment.key}: {exc}")
                        session.rollback()

                for ret in collected["ecom.returns.raw"]:
                    try:
                        upsert_return(session, ret.value)
                    except Exception as exc:
                        result.errors.append(f"return {ret.key}: {exc}")
                        session.rollback()

            result.silver_rows = _write_parquet(
                [Record(TOPIC_ORDERS, 0, i, o["order_id"], o, o["order_ts"]) for i, o in enumerate(silver)],
                "silver",
                TOPIC_ORDERS,
                batch_id,
            )
            result.gold_days = refresh_gold(affected_dates)

            if silver:
                newest = max(datetime.fromisoformat(o["order_ts"]) for o in silver)
                set_watermark("orders_stream", newest)
                age_ms = (datetime.now(timezone.utc) - newest).total_seconds() * 1000
                result.latency_ms = round(age_ms, 2)

        except Exception as exc:  # batch-level failure
            result.errors.append(f"{type(exc).__name__}: {exc}")
            result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            finish_run(
                result.run_id, "failed",
                records_in=sum(result.consumed.values()),
                records_out=result.warehouse_rows,
                records_rejected=result.rejected,
                error_message=str(exc)[:500],
                details=result.as_dict(),
            )
            raise

        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        finish_run(
            result.run_id, "success",
            records_in=sum(result.consumed.values()),
            records_out=result.warehouse_rows,
            records_rejected=result.rejected,
            details=result.as_dict(),
        )
        self._publish_metrics(result)
        return result

    # --------------------------------------------------------------- helpers
    def _publish_metrics(self, result: BatchResult) -> None:
        record_metric("events_processed", float(result.bronze_rows), "events", {"batch": result.batch_id})
        record_metric("records_rejected", float(result.rejected), "records", {"batch": result.batch_id})
        record_metric("duplicates_dropped", float(result.duplicates), "records", {"batch": result.batch_id})
        record_metric("late_events", float(result.late_events), "events", {"batch": result.batch_id})
        record_metric("processing_latency", float(result.latency_ms), "ms", {"batch": result.batch_id})
        record_metric("batch_duration", float(result.duration_ms), "ms", {"batch": result.batch_id})
        for topic, lag in result.consumer_lag.items():
            record_metric("consumer_lag", float(lag), "messages", {"topic": topic, "group": self.group})

    def _watermark(self) -> datetime | None:
        from common.db import fetch_scalar

        value = fetch_scalar(
            "SELECT watermark_ts FROM analytics.pipeline_watermark WHERE pipeline_name = 'orders_stream'"
        )
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return None

    @staticmethod
    def _parse(rec: Record) -> datetime | None:
        try:
            return datetime.fromisoformat(str(rec.value.get("event_ts")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None


def _text(sql: str):
    from sqlalchemy import text

    return text(sql)


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="micro-batch stream processor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=400)
    args = parser.parse_args()

    processor = StreamProcessor(batch_size=args.batch_size)
    if args.once:
        print(json.dumps(processor.process_once().as_dict(), indent=2))
        return 0

    while True:
        summary = processor.process_once().as_dict()
        print(json.dumps(summary))
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
