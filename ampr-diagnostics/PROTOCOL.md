# AMPR diagnostic protocol 1

Read-only routes on the existing TCP 9090 debug server:

- `/diag/info`
- `/diag/active?cursor=0&limit=64`
- `/diag/events?after=0&limit=64`
- `/diag/hist`

All pages start with `ampr_diag 1` and end with `end N`. Numbers are decimal.
Paths are raw bytes encoded as lowercase hex, or `-` for unavailable.
An absent/invalid end marker must cause the client to reject the page.
`busy=1` means retry later, not an empty table. No route resets /metrics.

An item row is `item` followed by these 16 fields:

`id parent kind stage source_job created_ns changed_ns file_id fd offset bytes command priority result path_truncated path_hex`

An event row is `event seq at_ns previous_stage_ns ended` followed by the
same 16 item fields. `ended=1` is a lifecycle removal, not an assertion of
successful I/O. `READ_REMOVED` result is the runtime's result snapshot.

Kinds: 1 APR job, 2 APR active read, 3 blocking pread task.
Stages: 1 job accepted, 2 job issued read, 3 job read completion observed,
4 job notification, 5 job released, 10 APR read listed, 11 APR read accepted,
12 APR completion observed, 13 APR read removed, 20 pread queued,
21 pread running, 22 pread finished. Not every engine path emits every stage.

`id` is unique within the module instance. `boot_ns` scopes that instance.
`parent` connects an APR read to its diagnostic job, or a loose pread task
to its APR read. Pack physical pread may have parent=0 and no indexed path.
All times are console CLOCK_MONOTONIC nanoseconds. PC receipt is a different
clock; map an observation to the PC request's begin/end interval.

`producer_dropped`, `active_table_skips`, `missing_updates` are cumulative
loss counters. Any nonzero value marks the active table potentially
incomplete/stale. It does not turn old entries into proven hung requests.
Active pages are independently sampled and are not one atomic whole-table
snapshot. Repeated IDs should be deduplicated by the client.

The event ring contains 8192 events. `next_seq` is the next event sequence,
`oldest_seq` is the first still available. `next_after` is the cursor for the
next page, and `lost_before_page` counts overwritten events after the requested
cursor. Reset the cursor on a new boot_ns. A busy page never advances it.

A histogram row is `hist stage` followed by 32 cumulative bucket counts.
The inclusive upper bounds are 1000*2^b nanoseconds for b=0..30; bin 31 is
open-ended. Values at a boundary belong to that boundary's bin. Histograms
measure completed spans in the previous stage. 29/30/31 are total lifetime
histograms for jobs/APR reads/pread tasks. Quantiles are bucket intervals,
never exact operation latencies. Dropped observations bias coverage.
