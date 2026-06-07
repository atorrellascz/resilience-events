"""
Replayer adapter -- Stage 6 of the loop (REPLAY): the "Veeam moment".

After a successful recovery, re-process requests that arrived during the outage
but were never persisted, reading them from the durable write-ahead-log the
edge-gateway journals to Redpanda. This is deterministic data recovery, not an
LLM decision.

The Redpanda/Kafka consumer is isolated behind a `fetch_fn` (returns the lost
records for an incident) and a `reprocess_fn` (re-applies one record, returns
True on success). This keeps the replay accounting logic testable without a
broker, and makes the operation idempotent at the record level: re-applying a
record that already landed is a no-op, so replay is safe to retry.

────────────────────────────────────────────────────────────────────────────
PRODUCTION REPLAY STRATEGY (design for the real Redpanda wiring)
────────────────────────────────────────────────────────────────────────────
This v1 fetches a list of records and reprocesses them. When wired to a real
Redpanda topic (the write-ahead-log the edge-gateway journals each incoming
request to, BEFORE processing), `fetch_fn` becomes offset-aware and three
properties must hold:

1) INCIDENT WINDOW -- replay only the outage, not the whole log.
   The system records the log offset when the dependency went DOWN
   (offset_start) and when it RECOVERED (offset_end). Replay operates ONLY on
   the window [offset_start, offset_end]. Requests that arrive AFTER recovery
   are persisted normally by the healthy service and are NOT replayed -- they
   are outside the window.

       ... 999 | 1000 .......... 1320 | 1321 1322 ...
               |                       |
            DB DOWN                DB RECOVERED
               +------- window -------+
        replay reprocesses offsets [1000..1320]  (the 320 lost requests)
        offsets >= 1321 are new traffic -> normal flow, never replayed

2) CHECKPOINTS -- resume, don't restart. The replayer commits a checkpoint of
   the last successfully reprocessed offset. If it dies after 319/320, the
   retry resumes at offset_start+319, not from zero. Efficient on large windows.

3) IDEMPOTENCY -- the safety net under both of the above. Because new traffic
   can arrive while we replay, and because a retry may re-touch a record, every
   reprocess is idempotent: re-applying an already-persisted request is a no-op.
   Combined with Redpanda's per-partition ordering, this preserves correctness
   even when replayed (old) and live (new) writes interleave.

The current engine and ReplayResult already support this -- only `fetch_fn`
becomes smarter (query by offset window + checkpoint). No core change needed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.models import Incident, ReplayResult

FetchFn = Callable[[Incident], list[Any]]      # the lost records to replay
ReprocessFn = Callable[[Any], bool]            # re-apply one record; True if ok


class NoopReplayer:
    """Replays nothing (attempted=0). Used when no WAL is wired yet."""

    def replay(self, incident: Incident) -> ReplayResult:
        return ReplayResult(attempted=0, succeeded=0, failed=0, detail="no replay source configured")


class RedpandaReplayer:
    """
    Replays lost requests from the WAL. Counts successes/failures so the
    post-mortem can report exact data recovery (e.g. 320/320).
    """

    def __init__(self, fetch_fn: FetchFn, reprocess_fn: ReprocessFn, source: str = "redpanda:wal") -> None:
        self._fetch = fetch_fn
        self._reprocess = reprocess_fn
        self._source = source

    def replay(self, incident: Incident) -> ReplayResult:
        records = self._fetch(incident)
        succeeded = 0
        failed = 0
        for record in records:
            try:
                ok = self._reprocess(record)
            except Exception:
                ok = False
            if ok:
                succeeded += 1
            else:
                failed += 1
        return ReplayResult(
            attempted=len(records),
            succeeded=succeeded,
            failed=failed,
            source=self._source,
            detail=f"replayed {succeeded}/{len(records)} from {self._source}",
        )