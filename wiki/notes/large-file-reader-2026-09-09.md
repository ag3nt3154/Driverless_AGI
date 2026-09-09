# Large-file reader investigation

> Recorded: 2026-09-09 | Status: proposed design, pending approval

The plan-only investigation is complete. No implementation or design approval is recorded.
No test or GUI verification is claimed.

## Current behavior and configuration findings

- `ReadTool` delegates default reads above 2,000 lines; documents and explicit ranges are
  excluded from that delegation.
- The parent filter estimates tokens as serialized length divided by four, rounded down,
  and filters results at or above the effective `reserve_tokens` threshold.
- Effective `context_window` and `reserve_tokens` values come from the config loader.
- A fresh child applies worker configuration. Supplying `parent_context` instead selects
  the fork-v2 path, which inherits the parent model and prefix and bypasses the ordinary
  worker tier.

## Proposed redesign

The proposal bases delegation on the actual selected result size and uses Chonkie recursive
splitting with one sequential reader. Code would append each section digest and enforce
complete, ordered coverage, with checks on accumulated context. The fully wrapped final
digest must remain strictly below the parent threshold. If needed, the same reader would
perform bounded condensation.

All of this design remains proposed pending approval. The full specification with
review amendments is at [large-file-reader-plan-2026-09-09.md](large-file-reader-plan-2026-09-09.md).

## Dependency findings and open verification

Chonkie is absent from the `dagi` environment. The observed Python version is 3.14.4.
Chonkie 1.7.0 is a candidate identified from official PyPI; compatibility of its transitive
dependencies on Windows remains unverified.

[Notes](index.md) | [Project wiki](../index.md)
