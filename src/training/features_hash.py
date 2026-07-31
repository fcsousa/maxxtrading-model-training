"""Feature-vector hashing, intentionally identical to the Score Engine's
AD-007 algorithm (app/domain/services/features_hash.py) and NestJS's
computeFeaturesHash (features-hash.util.ts) — duplicated here rather than
imported across repos (AD-013: no runtime code sharing between this repo and
the Score Engine).

Used to verify, once NestJS DB read access exists, that a training-side
reconstructed feature vector matches a real signal_scores.features_hash —
see docs/schema-discovery.md's A* parity study. Do not use this to build
feature-export SQL; that remains blocked until the hash-match proof runs
against real data.
"""

import hashlib
import json
from typing import Any


def compute_features_hash(features: dict[str, Any]) -> str:
    canonical = json.dumps(features, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
