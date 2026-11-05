AMPR diagnostic 0.4.0 - ready handoff candidate

Based on quer3q/ampr-emu-ng 0.3.0 at cd0c11efeedec45f2ed01715ff33c00898d40240.
GPL-3.0-or-later; complete corresponding source and patch are packaged.

Changes from diagnostic 0.3.0:
- After a head is fully released, its successor may run in the same pass.
- At most eight ready handoffs per lane/pass; the read budget is shared.
- No bypass of a blocked head or of its read/native completion fences.
- Recheck pread completions before the cursor pass only if pending work
  exists and the reactor wake epoch changed since the first drain.
- Measure pread DONE publication -> reactor observation for every part.
- Existing diagnostic protocols remain 2 (lifecycle) and 1 (lane heads).
- Pool, read limits, priority policy, thread counts and FW patches unchanged.

Use lane_eop_overlap=0 (baseline A). The earlier B profile did not remove
cutscene freezes. Reset that profile before evaluating this candidate.
This is a code optimization candidate, not a confirmed freeze fix.

Debug-only memory growth: 128 publication stamps x 8 B + 8 counters x 8 B
= 1088 B outside the unchanged 128 MiB pool. Exact layouts are printed by
host tests. CPU overhead, FPS and console live memory peaks are unmeasured.

The PC collector 1.9.0 records the extra counters and the new observation
latency stage. Older collectors retain raw metrics but lack its averages.
Replacing the library requires a full game close and a ShadowMount scan
with emulator cache update. Never replace it while the game is running.
