# 0008 Held-out results are reported as they came out

## Decision
Gates were set from the development seeds before the held-out run. The held-out run happened once (`reports/heldout.lock`); its gates are reported pass or fail as they came out and are never loosened afterwards. CI checks the lock was committed exactly once and that a second run exits with code 3.
