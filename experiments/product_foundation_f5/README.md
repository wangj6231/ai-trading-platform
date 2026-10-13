# F5 lifecycle verification artifacts

Only the four TEST_SEAMS_CONFIRMED lifecycle seams are in scope. No object/archive tests or implementation, no financial destructive purge.

`nonpostgresql.xml` and `postgresql.xml` record two disjoint full-suite partitions against the same final source. `coverage.json` combines their coverage. `source_freeze.json` freezes protected authored files before these runs; `verification.json` verifies actual collection coverage, no duplicate/missing tests, no failures/errors/skips, and unchanged protected source. These are not historical F4.1 results. Initial RED evidence is summarized in the F5 report; unsuccessful infrastructure connections and an aborted earlier run are not final passing evidence.
