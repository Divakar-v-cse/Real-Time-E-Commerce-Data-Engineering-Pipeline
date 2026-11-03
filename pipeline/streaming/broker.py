"""Kafka-compatible local broker.

The sandbox cannot run Apache Kafka (no reachable Docker daemon), so the event
bus is implemented as a **durable, partitioned append-only log on disk** with
the same semantics the pipeline depends on:

* topics with N partitions and key-based partitioning (``crc32(key) % N``)
* monotonic per-partition offsets
* consumer groups with committed offsets
* consumer lag = latest offset - committed offset
* re-play from any committed offset (at-least-once delivery)

When ``USE_REAL_KAFKA=true`` the producer/consumer use ``kafka-python`` against
``KAFKA_BOOTSTRAP_SERVERS`` instead; the rest of the pipeline is unchanged.
"""
from __future__ import annotations

import json
import threading
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from common.settings import DATA_DIR

BROKER_ROOT = DATA_DIR / "broker"
OFFSET_ROOT = BROKER_ROOT / "_offsets"

_TOPIC_PARTITIONS = {
    "ecom.orders.raw": 4,
    "ecom.payments.raw": 2,
    "ecom.shipments.raw": 2,
    "ecom.returns.raw": 1,
    "ecom.orders.dlq": 1,
    "ecom.orders.silver": 4,
}


@dataclass
class Record:
    topic: str
    partition: int
    offset: int
    key: str
    value: dict[str, Any]
    produced_at: str

    @property
    def event_ts(self) -> str:
        return str(self.value.get("event_ts") or self.produced_at)


@dataclass
class _PartitionLog:
    path: Path
    count: int = 0

    def append(self, payload: dict[str, Any]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        offset = self.count
        self.count += 1
        return offset

    def iter_records(self, start: int = 0) -> Iterator[tuple[int, dict[str, Any]]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index < start:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    yield index, json.loads(line)
                except json.JSONDecodeError:
                    continue


class LocalBroker:
    """File-backed topic log with consumer groups (Kafka semantics, no JVM)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or BROKER_ROOT)
        self._lock = threading.Lock()
        self._logs: dict[tuple[str, int], _PartitionLog] = {}
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ topics
    def partitions(self, topic: str) -> int:
        return _TOPIC_PARTITIONS.get(topic, 1)

    def topic_dir(self, topic: str) -> Path:
        return self.root / topic

    def _log(self, topic: str, partition: int) -> _PartitionLog:
        key = (topic, partition)
        if key not in self._logs:
            path = self.topic_dir(topic) / f"partition={partition}" / "log.jsonl"
            count = 0
            if path.exists():
                with path.open("rb") as handle:
                    count = sum(1 for _ in handle)
            self._logs[key] = _PartitionLog(path=path, count=count)
        return self._logs[key]

    # ---------------------------------------------------------------- producer
    def produce(self, topic: str, key: str, value: dict[str, Any]) -> Record:
        n = self.partitions(topic)
        partition = zlib.crc32(str(key).encode("utf-8")) % n
        produced_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            log = self._log(topic, partition)
            offset = log.append({"key": key, "value": value, "produced_at": produced_at})
        return Record(topic, partition, offset, key, value, produced_at)

    def produce_many(self, topic: str, rows: list[tuple[str, dict[str, Any]]]) -> int:
        return sum(1 for key, value in rows if self.produce(topic, key, value))

    # ---------------------------------------------------------------- consumer
    def _offset_path(self, group: str, topic: str) -> Path:
        return OFFSET_ROOT / group / f"{topic}.json"

    def committed_offsets(self, group: str, topic: str) -> dict[str, int]:
        path = self._offset_path(group, topic)
        if not path.exists():
            return {}
        try:
            return {str(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    def commit(self, group: str, topic: str, offsets: dict[int, int]) -> None:
        path = self._offset_path(group, topic)
        path.parent.mkdir(parents=True, exist_ok=True)
        current = self.committed_offsets(group, topic)
        current.update({str(k): v for k, v in offsets.items()})
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    def latest_offsets(self, topic: str) -> dict[int, int]:
        return {p: self._log(topic, p).count for p in range(self.partitions(topic))}

    def lag(self, topic: str, group: str) -> int:
        latest = self.latest_offsets(topic)
        committed = self.committed_offsets(group, topic)
        return sum(max(0, n - int(committed.get(str(p), 0))) for p, n in latest.items())

    def consume(
        self, topic: str, group: str, max_records: int = 500, start_over: bool = False
    ) -> list[Record]:
        """Read up to ``max_records`` across partitions, starting at committed offsets."""
        committed = {} if start_over else self.committed_offsets(group, topic)
        records: list[Record] = []
        new_offsets: dict[int, int] = {}
        for partition in range(self.partitions(topic)):
            if len(records) >= max_records:
                break
            log = self._log(topic, partition)
            start = int(committed.get(str(partition), 0))
            for offset, payload in log.iter_records(start):
                if len(records) >= max_records:
                    break
                records.append(
                    Record(
                        topic=topic,
                        partition=partition,
                        offset=offset,
                        key=str(payload.get("key", "")),
                        value=payload.get("value", {}),
                        produced_at=str(payload.get("produced_at", "")),
                    )
                )
                new_offsets[partition] = offset + 1
        if new_offsets:
            self.commit(group, topic, new_offsets)
        return records

    # -------------------------------------------------------------- inspection
    def topic_stats(self) -> list[dict[str, Any]]:
        stats = []
        for topic in _TOPIC_PARTITIONS:
            latest = self.latest_offsets(topic)
            stats.append(
                {
                    "topic": topic,
                    "partitions": self.partitions(topic),
                    "messages": sum(latest.values()),
                    "bytes": sum(
                        p.stat().st_size
                        for p in (self.topic_dir(topic)).glob("partition=*/log.jsonl")
                        if p.exists()
                    ),
                }
            )
        return stats

    def total_messages(self) -> int:
        return sum(sum(self.latest_offsets(t).values()) for t in _TOPIC_PARTITIONS)

    def reset_offsets(self, group: str) -> None:
        target = OFFSET_ROOT / group
        if target.exists():
            for child in target.glob("*.json"):
                child.unlink()


broker = LocalBroker()


@dataclass
class KafkaProducerAdapter:
    """Real Kafka producer used when ``USE_REAL_KAFKA=true`` and a broker exists."""

    bootstrap: str
    _producer: Any = field(default=None, init=False)

    def __post_init__(self) -> None:  # pragma: no cover - requires a broker
        from kafka import KafkaProducer  # type: ignore

        self._producer = KafkaProducer(
            bootstrap_servers=self.bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: str(k).encode("utf-8"),
            linger_ms=20,
            acks="all",
        )

    def send(self, topic: str, key: str, value: dict[str, Any]) -> None:  # pragma: no cover
        self._producer.send(topic, key=key, value=value)
