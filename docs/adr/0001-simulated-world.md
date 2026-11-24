# 0001 A simulated world with its own truth, and the same luck for every design

## Context
Carrier files, carrier replies and customer questions are confidential at every shipper. Without a truth to grade against, "the agents work" is an opinion.

## Decision
`src/eap/world/` simulates shippers, carriers, a quarter of weekly files in the carriers' own formats, format changes, carrier mailboxes and customer questions. Every file keeps its truth (fields, units, modes, real distances, real fuel) next to the view a design may read. The simulated model and the simulated desk live in the world: they may look at the truth to decide, by luck, whether they are right. Every coin is keyed by (seed, purpose, id), so two designs that make the same call get the same draw, and a model that is better than another is right on every case the weaker one gets right.

## Consequences
Differences between designs come from the designs. The numbers are only as good as the world's assumptions, which are in `config/world.yml` and listed under Limits in the README.
