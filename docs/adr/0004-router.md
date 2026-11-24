# 0004 A small model reads first; a mid-size model reads again on doubt

## Decision
`routing.first` reads every new format. If code rejects a decision or the model doubts one, `routing.escalate` reads the whole file again and the reading with fewer doubts is kept. A quality monitor (Bernoulli CUSUM on first reads that fail checks) pins first reads to the escalation model for ten days after an alarm.

## Consequences
About 60% lower model cost than using the mid-size model for every read, at a small cost in mode errors (ablation `no_router`). The small model's first read fails checks on most new formats; the router is worth it because each read is cheap and checks catch what it gets wrong.
