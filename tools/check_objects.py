import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.taxonomy import BUILTIN_TYPES, PromiseType  # noqa: E402
from app.services.detect import detect_promises  # noqa: E402

types = [
    PromiseType(
        code=t["code"], title=t["title"], description=t["description"],
        keywords=t["keywords"], examples=t["examples"], is_builtin=True, priority=t["priority"],
    )
    for t in BUILTIN_TYPES
]
calls = json.load(open(os.path.join(ROOT, "data", "sample_calls.json"), encoding="utf-8"))

bad = []
for call in calls:
    for p in detect_promises(call, types):
        obj = p.object
        if obj and (not obj[0].isalpha() or obj.split()[0].isupper() and False):
            bad.append(obj)

objects = []
for call in calls:
    for p in detect_promises(call, types):
        if p.object:
            objects.append((p.promise_type, p.object))
print("objects:", len(objects), "bad:", len(bad))
for t, o in objects[:15]:
    print(f"  {t:14s} {o}")
