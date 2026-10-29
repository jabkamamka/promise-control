import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.detect import detect_promises  # noqa: E402
from app.services.taxonomy import BUILTIN_TYPES, PromiseType  # noqa: E402

types = [
    PromiseType(code=t["code"], title=t["title"], description=t["description"], keywords=t["keywords"],
                examples=t["examples"], is_builtin=True, priority=t["priority"])
    for t in BUILTIN_TYPES
]

for name in ("sample_calls.json", "sample_calls_extra.json"):
    path = os.path.join(ROOT, "data", name)
    calls = json.load(open(path, encoding="utf-8"))
    by_type = collections.Counter()
    total = 0
    empty = []
    for call in calls:
        promises = detect_promises(call, types)
        total += len(promises)
        for p in promises:
            by_type[p.promise_type] += 1
            if not p.title or len(p.title) < 3:
                empty.append((call["id"], p.title))
    print(f"{name}: звонков {len(calls)}, задач {total}, среднее {total / len(calls):.2f}")
    print("  ", dict(by_type))
    if empty:
        print("   пустые заголовки:", empty[:5])
