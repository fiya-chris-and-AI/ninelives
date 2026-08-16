# Write-Ahead Logging: Why Databases Never Really Forget

Every transactional database, from a single-node embedded store to a
globally distributed cluster, relies on the same core discipline to survive
a crash without losing committed work: write-ahead logging. Before any
change is applied to the actual data, the database first writes a record of
that change, sequentially and durably, to an append-only log, and only
acknowledges the transaction as committed once that log record has itself
been made durable on stable storage, so that even if the process is killed
in the exact instant between writing the log record and applying it to the
underlying data structures, the crash-recovery routine that runs on restart
can simply replay every log record after the last known-consistent point and
arrive at precisely the same state the database would have reached if it had
never crashed at all, which is what makes it possible for a distributed
database to relocate a piece of work from a dead node to a healthy one and
have that healthy node pick up exactly where the dead one left off, because
the log, not the process, was always the actual source of truth, the process
was only ever a temporary, disposable executor reading instructions from a
record that outlives it. This is the same principle, generalized past a
single row or table: if the log of what happened is durable, the executor
carrying it out was never load-bearing in the first place, and losing it
mid-sentence is a survivable event rather than a fatal one.
