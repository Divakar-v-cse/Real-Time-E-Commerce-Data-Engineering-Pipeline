import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.streaming.producer import EventProducer
from pipeline.generator.schemas import validate_order_event
p = EventProducer(seed=7)
res = p.emit_one()
print("RESULT:", res)
# regenerate raw to inspect
import pipeline.streaming.broker as B
recs = B.broker.consume("ecom.orders.dlq", "dbg", 1, start_over=True)
if recs:
    print("ERRORS:", recs[0].value.get("errors"))
    print("KEYS:", sorted(recs[0].value.get("payload", {}).keys()))
