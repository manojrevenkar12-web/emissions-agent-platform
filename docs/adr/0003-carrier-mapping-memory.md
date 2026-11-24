# 0003 Remember a carrier's mapping, and notice when the carrier changes its export

## Context
Most weekly files come from a carrier the desk has seen before. Reading every file again costs tokens and people's time and adds new chances to be wrong.

## Decision
A mapping that passed checks, or that a person settled, is remembered under a fingerprint of the file's header names (never row values, so memory can be shared across tenants). A remembered mapping is used only if the file's mode codes are all known, the checks pass again, and the medians of the numbers it reads have not moved by more than the configured ratio (a carrier switching from kilograms to pounds keeps its headers). A unit the header does not state is confirmed by a person once before it is remembered.

## Consequences
Memory is the largest lever on people's time and model cost (see the ablation table). A wrong mapping that is remembered is wrong for a whole quarter, which is why units are confirmed once.
