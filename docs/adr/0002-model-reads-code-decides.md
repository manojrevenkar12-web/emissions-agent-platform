# 0002 The model reads, code decides

## Context
A model can read "Gew." as a weight in pounds with high confidence. One wrong unit turns a customer's monthly report into nonsense; a model alone gets this wrong often enough to make reports useless (see the README).

## Decision
A reading is a typed `Mapping`. Code applies it and checks what it implies against public reference data: distances against each lane's great-circle distance, weights against what the mode can carry (and a full truckload's median weight), modes against the ports, airports and terminals on each lane and against what the carrier moves, fuel per tonne-km against the default. A failed check names the decisions it rejects. Those, plus decisions the model doubts, go to a second model and then to a person. The emissions calculation, deduplication and data-quality labels are code.

## Consequences
Unit and column errors drop from about 1,900 per 10,000 shipments (model alone) to the low tens. What checks cannot see (kilograms read as pounds on light loads, groupage read as full truckload) remains; a person confirms any unit the header does not state before it is remembered (ADR 0003).
