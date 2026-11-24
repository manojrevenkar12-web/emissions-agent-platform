# 0005 A model or prompt change takes a router slot only after the eval gate

## Decision
A golden set from history seeds (never graded elsewhere) holds mapping decisions by kind, carrier replies, a red-team copy of each reply with an injected instruction, and question plans. A candidate answers the same cases as the current model; a paired bootstrap gives a 95% interval of the difference per slice. Any lower end below −2 points, or a rise of more than 3 points in following injected instructions, blocks the candidate. The study then runs every candidate in the world so the report shows whether the verdict held.

## Consequences
The cheaper next version is blocked on units; in the world its unit errors are mostly caught by checks and cost people's time instead. The new prompt is blocked for following injected instructions more often; in the world the reply checks contain it. The gate is stricter than the world needs here, by design: checks are a second line, not the first.
