"""Event contracts + validation for the e-commerce pipeline.

Every record that enters the platform is checked against these schemas before
it is allowed into the Bronze layer.  The same contract is used by:
  * the Python producer (producer-side validation)
  * the streaming processor (consumer-side validation / dead-letter routing)
  * the data-quality suite (contract conformance checks)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

TOPIC_ORDERS = "ecom.orders.raw"
TOPIC_PAYMENTS = "ecom.payments.raw"
TOPIC_SHIPMENTS = "ecom.shipments.raw"
TOPIC_RETURNS = "ecom.returns.raw"
TOPIC_DLQ = "ecom.orders.dlq"

ORDER_SCHEMA_VERSION = "1.0.0"

REQUIRED_ORDER_FIELDS = (
    "event_id",
    "event_type",
    "event_ts",
    "order_id",
    "customer_id",
    "order_ts",
    "currency",
    "items",
)

ITEM_REQUIRED_FIELDS = ("product_id", "quantity", "unit_price", "discount_pct")


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    record: dict[str, Any]

    @property
    def error_summary(self) -> str:
        return "; ".join(self.errors)


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def validate_order_event(record: dict[str, Any]) -> ValidationResult:
    """Structural + business-rule validation of an order event."""
    errors: list[str] = []

    for field in REQUIRED_ORDER_FIELDS:
        if field not in record or record[field] in (None, ""):
            errors.append(f"missing_field:{field}")

    if errors:
        return ValidationResult(False, errors, record)

    if not isinstance(record["items"], list) or not record["items"]:
        errors.append("business_rule:empty_order")
    else:
        for idx, item in enumerate(record["items"]):
            if not isinstance(item, dict):
                errors.append(f"business_rule:item_{idx}_not_object")
                continue
            for field in ITEM_REQUIRED_FIELDS:
                if field not in item or item[field] in (None, ""):
                    errors.append(f"missing_field:item_{idx}.{field}")
            qty = item.get("quantity")
            price = item.get("unit_price")
            disc = item.get("discount_pct")
            if isinstance(qty, (int, float)) and qty <= 0:
                errors.append(f"business_rule:item_{idx}_non_positive_qty")
            if isinstance(price, (int, float)) and price < 0:
                errors.append(f"business_rule:item_{idx}_negative_price")
            if isinstance(disc, (int, float)) and not (0 <= disc <= 1):
                errors.append(f"business_rule:item_{idx}_discount_out_of_range")

    order_ts = _parse_ts(record.get("order_ts"))
    event_ts = _parse_ts(record.get("event_ts"))
    now = datetime.now(timezone.utc)

    if order_ts is None:
        errors.append("malformed:order_ts")
    elif order_ts > now.replace(microsecond=0) + __import__("datetime").timedelta(days=1):
        errors.append("business_rule:order_ts_in_future")

    if event_ts is None:
        errors.append("malformed:event_ts")

    currency = record.get("currency")
    if currency not in {"USD", "EUR", "GBP", "INR", "AUD", "JPY", "BRL", "AED"}:
        errors.append(f"business_rule:unsupported_currency:{currency}")

    return ValidationResult(not errors, errors, record)


def compute_order_totals(items: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """Return (subtotal, discount_total, shipping_total, grand_total)."""
    subtotal = 0.0
    discount_total = 0.0
    for item in items:
        qty = float(item.get("quantity") or 0)
        price = float(item.get("unit_price") or 0)
        disc = float(item.get("discount_pct") or 0)
        line = qty * price
        subtotal += line
        discount_total += line * disc
    net = subtotal - discount_total
    # Flat-rate shipping, free above a threshold - mirrors typical store rules.
    shipping = 0.0 if net >= 75.0 or net == 0 else 6.99
    grand_total = round(net + shipping, 2)
    return round(subtotal, 2), round(discount_total, 2), round(shipping, 2), grand_total


VALIDATORS: dict[str, Callable[[dict[str, Any]], ValidationResult]] = {
    "order_created": validate_order_event,
    "order_updated": validate_order_event,
}
