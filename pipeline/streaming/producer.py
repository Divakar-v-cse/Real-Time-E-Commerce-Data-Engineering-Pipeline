"""Real-time e-commerce event producer.

Generates order events with the same factory used for the historical dataset,
validates them against the message schema and publishes to the event bus
(Kafka when available, otherwise the local Kafka-compatible broker).

Features
--------
* configurable rate (events / second) and duration or total count
* schema validation before publish; invalid payloads go to ``ecom.orders.dlq``
* realistic defect injection (duplicates, nulls, negative price, future ts)
* optional back-dated ("late arriving") events to exercise the watermark logic
* returns a per-run summary used by ``POST /api/events/generate``
"""
from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pipeline.generator import catalog
from pipeline.generator.factory import DQ_RATES, Factory
from pipeline.generator.schemas import (
    TOPIC_DLQ,
    TOPIC_ORDERS,
    TOPIC_PAYMENTS,
    TOPIC_RETURNS,
    TOPIC_SHIPMENTS,
    validate_order_event,
)
from pipeline.streaming.broker import broker


@dataclass
class ProducerStats:
    generated: int = 0
    published: int = 0
    rejected: int = 0
    defects: dict[str, int] = field(default_factory=dict)
    late_events: int = 0
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated": self.generated,
            "published": self.published,
            "rejected": self.rejected,
            "defects": self.defects,
            "late_events": self.late_events,
            "duration_ms": self.duration_ms,
            "events_per_second": round(self.published / max(self.duration_ms / 1000, 0.001), 2),
        }


class EventProducer:
    def __init__(self, seed: int | None = None, live: bool = True) -> None:
        self.factory = Factory(seed=seed if seed is not None else random.randint(1, 10**6))
        self.rng = self.factory.rng
        self.live = live
        self._sequence = 900_000
        self.stats = ProducerStats()

    # ------------------------------------------------------------------ helpers
    def _next_id(self, ts: datetime) -> str:
        self._sequence += 1
        return f"O{ts:%Y%m%d}{self._sequence:07d}"

    def _defect(self, name: str) -> bool:
        return self.rng.random() < DQ_RATES.get(name, 0.0)

    # ------------------------------------------------------------------- events
    def emit_one(self, late_probability: float = 0.0) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        late = late_probability > 0 and self.rng.random() < late_probability
        order_ts = now - timedelta(
            days=self.rng.randint(1, 4), hours=self.rng.randint(1, 20)
        ) if late else now
        order = self.factory.make_order(order_ts, self._sequence + 1)
        order["order_id"] = self._next_id(order_ts)
        items = order.pop("_items")
        order.pop("_customer", None)
        order.pop("_payment_roll", None)
        order.pop("_success_rate", None)
        order["schema_version"] = "1.0.0"
        order["event_id"] = uuid4().hex
        order["event_type"] = "order.created"
        order["event_ts"] = order_ts.isoformat()
        order["ingest_ts"] = now.isoformat()
        order["items"] = items

        self.stats.generated += 1
        if late:
            self.stats.late_events += 1

        # --- deliberate data-quality defects (mirrors the batch generator) ----
        if self._defect("duplicate_order"):
            self._produce_item(order, order["order_id"], "duplicate_order")
            self.stats.defects["duplicate_order"] = self.stats.defects.get("duplicate_order", 0) + 1

        if self._defect("null_customer"):
            order["customer_id"] = None
            self.stats.defects["null_customer"] = self.stats.defects.get("null_customer", 0) + 1

        if self._defect("negative_price") and items:
            items[0]["unit_price"] = -abs(items[0]["unit_price"])
            self.stats.defects["negative_price"] = self.stats.defects.get("negative_price", 0) + 1

        if self._defect("future_timestamp"):
            order["order_ts"] = (now + timedelta(days=self.rng.randint(2, 30))).isoformat()
            order["event_ts"] = order["order_ts"]
            self.stats.defects["future_timestamp"] = self.stats.defects.get("future_timestamp", 0) + 1

        if self._defect("total_mismatch"):
            order["order_total"] = round(order["order_total"] * 1.37, 2)
            self.stats.defects["total_mismatch"] = self.stats.defects.get("total_mismatch", 0) + 1

        if self._defect("orphan_product") and items:
            items[0]["product_id"] = "PRD-MISSING-9999"
            self.stats.defects["orphan_product"] = self.stats.defects.get("orphan_product", 0) + 1

        if self._defect("missing_payment_status"):
            order["payment_status"] = None
            self.stats.defects["missing_payment_status"] = (
                self.stats.defects.get("missing_payment_status", 0) + 1
            )

        result = validate_order_event(order)
        if not result.ok:
            self.stats.rejected += 1
            broker.produce(
                TOPIC_DLQ,
                order.get("order_id") or "unknown",
                {
                    "order_id": order.get("order_id"),
                    "errors": result.errors,
                    "payload": order,
                    "event_ts": order.get("event_ts"),
                    "ingest_ts": now.isoformat(),
                },
            )
            return {"order_id": order.get("order_id"), "status": "rejected", "errors": result.errors}

        self._produce_item(order, order["order_id"], "ok")
        self.stats.defects["accepted"] = self.stats.defects.get("accepted", 0) + 1

        # Downstream events (payments / shipments / returns) follow the order.
        payment = self.factory.build_payment(order)
        payment["event_ts"] = now.isoformat()
        broker.produce(TOPIC_PAYMENTS, payment["payment_id"], payment)

        shipment = self.factory.build_shipment(order)
        if shipment:
            shipment["event_ts"] = now.isoformat()
            broker.produce(TOPIC_SHIPMENTS, shipment["shipment_id"], shipment)
            returned = self.factory.build_return(order, shipment)
            if returned:
                returned["event_ts"] = now.isoformat()
                broker.produce(TOPIC_RETURNS, returned["return_id"], returned)

        return {"order_id": order["order_id"], "status": "accepted", "order_total": order["order_total"]}

    def _produce_item(self, order: dict[str, Any], key: str, tag: str) -> None:
        broker.produce(TOPIC_ORDERS, key, order)
        self.stats.published += 1
        _ = tag

    # ---------------------------------------------------------------------- run
    def run(
        self,
        count: int | None = None,
        duration_seconds: float | None = None,
        rate: float = 5.0,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        interval = 1.0 / max(rate, 0.1)
        emitted = 0
        deadline = started + duration_seconds if duration_seconds else None
        while True:
            if count is not None and emitted >= count:
                break
            if deadline is not None and time.perf_counter() >= deadline:
                break
            self.emit_one(late_probability=0.06)
            emitted += 1
            if rate > 0 and (count is None or emitted < count):
                time.sleep(interval)
        self.stats.duration_ms = int((time.perf_counter() - started) * 1000)
        return {"emitted": emitted, **self.stats.as_dict()}


def main() -> int:
    parser = argparse.ArgumentParser(description="publish synthetic e-commerce events")
    parser.add_argument("--rate", type=float, default=5.0, help="events per second")
    parser.add_argument("--count", type=int, default=None, help="total events to publish")
    parser.add_argument("--duration", type=float, default=None, help="run for N seconds")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    producer = EventProducer(seed=args.seed)
    count = args.count if args.count is not None else (None if args.duration else 50)
    summary = producer.run(count=count, duration_seconds=args.duration, rate=args.rate)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
