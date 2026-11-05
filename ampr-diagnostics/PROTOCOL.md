# AMPR diagnostic protocol 2 (diagnostic 0.3.0)

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


# Optional lane-head protocol 1 (diagnostic 0.3.0)

The lifecycle protocol stays 2, preserving old captures. /metrics advertises
`diag_heads_protocol 1` and /diag/info advertises `head_protocol 1`.
New PC collector 1.8.0 queries /diag/heads?after=0&limit=64. This route is read-only
and cannot fall through to /metrics or reset any maxima.

Response starts `ampr_heads 1`, then diag_build/build, boot_ns, now_ns, busy,
producer_dropped, samples, sample_period_ns, event_capacity, lane_count,
oldest_seq, next_seq, after, next_after, lost_before_page, rows. It ends
`end ROW_COUNT`. Limit is at most 64 rows. Cursor loss means overwritten rows;
producer_dropped counts skipped entire head snapshots, independently of the
lifecycle store's counters. A busy page has no rows and keeps its old cursor.

Each row is `head SEQUENCE` followed by these decimal fields and path hex:

lane source_job diag_id observed_ns first_seen_ns contiguous
block_reason block_since_ns block_opcode command_index command_count source_offset
source_bytes cursor_opcode flags active_reads read_seq_latest read_seq_completed
native_opcode native_retry_at_ns file_id fd file_offset read_bytes
read_submit_ns read_flags chain_active_reads chain_active_bytes chain_retry_at_ns pread_queued
pread_running pread_pending pread_threads path_truncated path_hex

fd is signed, all other integers unsigned. path_truncated is 0/1, path is at
most 96 bytes. Names are resolved on the HTTP thread from file_id, never while
holding the reactor mutex. No buffer or synchronization-memory addresses are exported.

The reactor copies its actual priority-lane heads under its existing mutex,
roughly every 100 ms. It observes flags and cursors; it never polls native
completion or evaluates game synchronization memory for diagnostics. Pread
queued/running counts are global, from sequential atomic state loads, not CPU
load and not an atomic whole-pool snapshot. Idle lanes only emit a transition
when a previously observed head becomes absent; empty heartbeats are filtered.
The ring has 1024 rows. Its time coverage depends on active lane count.

flags bits: 1 nativeSubmitted, 2 nativeBatchReleasePending, 4 native lane wait
sequence not completed, 8 job failed, 16 processingComplete, 32 cached cursor
opcode valid, 64 first read already issued, 128 source cursor at end,
256 successor queued, 512 no admitted lifecycle diagnostic handle.
cursor_opcode is 256 when not known. Native opcode is meaningful with its
native pending flags, not necessarily the current cursor command.

read_flags: 1 first linked unfinished read copied, 2 submit accounted,
4 pread queued, 8 awaiting resubmit, 16 awaiting initial batch submit,
32 read-chain descriptor only (not evidence of an in-flight I/O request).
When bit 1 is set, file/offset/bytes refer to one unfinished read; other reads
of the head are not listed by this row. Chain counts/bytes describe the cursor
chain. read_submit_ns=0 means unknown. Retry timestamps may be time-counter
values or internal sentinel values; never subtract them from monotonic now_ns.

block_reason codes 1..8 have the same labels as lifecycle pre-first-read
waiting, but this independent tag continues after the first read. Codes 9 and
10 mean read-chain retry delay and indexed-FD acquisition deferred. Zero means
no recorded block, 8 is unclassified. block_since_ns is the time the reactor
last observed that exact command/reason pair at a stop branch. Progress clears
the tag; skipped lifecycle history changes do not drop this independent tag.
A cursor mismatch invalidates an older tag. Flags describe observed state;
existence of unfinished reads alone does not prove that the head waits on them.

first_seen_ns is the first retained sample of this head, not exact promotion
time. contiguous=1 means the same job was observed with a sample gap at most
300 ms; a longer gap or new job resets first_seen_ns. Samples do not prove a
condition held continuously between observations. The PC must not extend a
sample to the end of a freeze marker or treat it as frame timing.

Two stores are independently try-locked. Producers never wait for HTTP and
no diagnostic field changes scheduling, completion publication or read knobs.
Combined bounded storage is measured/asserted by host tests. Console overhead
and behavior still require console validation.
