# AMPR diagnostic protocol 2 (diagnostic 0.2.0)

Read-only HTTP routes on port 9090: /diag/info, /diag/active?cursor=0&limit=64,
/diag/events?after=0&limit=64, /diag/hist. These never reset /metrics maxima.
The PC collector accepts both protocol 1 and 2. Old collectors do not support 2.

The first line is `ampr_diag 2`. Each page ends with `end ROW_COUNT`.
Limits remain 64 rows per active/event page, 64 KiB per response.
Headers include build/upstream/boot_ns/now_ns, busy, producer_dropped,
active_table_skips, missing_updates, tracked_active, active_may_be_incomplete,
oldest_seq/next_seq and capacities. New fields:

- completion_guaranteed=1: an admitted diagnostic lifecycle publishes completion
  independently of the history try-lock; it does not guarantee admission of all I/O.
- begin_skipped_busy: sampled starts skipped when the history lock is busy.
  Their handle is zero and subsequent updates are ignored.
- completion_deferred/reaped: deferred publication and processed endings.
  A completed slot is omitted from active snapshots even before reclamation.
- sample_job_every=1, sample_read_every=16, sample_pread_every=64.
- seen_jobs/reads/preads: operations considered before deterministic per-kind sampling.
- events_filtered: intentionally suppressed fast completion summaries, separate
  from lost_before_page (ring overwrite). Ring capacity is 4096, active 1024.

A protocol 2 item has these 28 decimal fields, then path hex (or `-`):
id parent kind stage source_job created_ns changed_ns file_id fd offset bytes
command priority result path_truncated gapped wait_reason wait_since_ns
wait_blocker wait_opcode wait_ns_1 wait_ns_2 wait_ns_3 wait_ns_4 wait_ns_5
wait_ns_6 wait_ns_7 wait_ns_8 path_hex

The first 15 fields retain protocol 1 meanings. fd/result are signed. Path is at
most 96 bytes. `event` adds seq at_ns previous_stage_ns ended before the item.
An ended record is a completion summary; intermediate tiny transitions are not
an exhaustive trace. Slow wait transitions (at least 100 ms on the old reason)
are retained; their item describes the reason being closed. Endings at least 50 ms (job), 20 ms (sampled APR), 10 ms (sampled
pread), failures, and one in 16 other endings are retained.

wait_reason is only pre-first-read waiting: 0 none, 1 prior job in priority lane,
2 game address/counter signal, 3 per-pass issue budget, 4 per-read active window,
5 native operation/batch, 6 own read fence, 7 I/O admission, 8 scheduler/other
(unclassified). wait_blocker is a source job ID, never a pointer. wait_opcode is
an opcode when available; zero means unavailable. Initial unclassified waiting
starts at acceptance. For queued jobs the lane predecessor is recorded; entering
progress ends that queue span. Explicit blocking branches then change the reason.
The eight wait_ns counters accumulate closed spans before the first read. For a
currently waiting job, add now_ns-wait_since_ns only to its current reason.
Missing reason/stage updates set gapped; these totals must then be treated as
partial attribution, not an exact explanation of game freeze time.

Hist rows keep the 32 inclusive powers-of-two microsecond bins. Stage spans
with a missing update are excluded; tracked full lifetimes (29/30/31) continue
to be counted from known begin/end times. Histograms describe admitted sampled
lifecycles, not all game requests. They do not freeze if intermediate events or
stage changes are dropped. No elapsed-time eviction hides a truly unfinished
operation. A full table skips admission rather than overwriting live state.

Completion slot identities include a generation and are atomically claimed.
A late or duplicate ending cannot finish a new operation reusing that slot.
No producer spins or waits on the history lock; no diagnostic network calls run
on game threads. This does not establish zero console overhead.
