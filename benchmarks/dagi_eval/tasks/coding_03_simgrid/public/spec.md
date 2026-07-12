# Task: optimize the epidemic simulation

`sim.py` simulates entities moving in a 2D world with infection spread. Make
`sim.run(input_dir)` as fast as possible without changing its output.

## Contract
- Entry point: `sim.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Output identical (floats within 1e-6 relative). The update semantics defined
  by the current implementation are the ground truth — read it carefully
  (simultaneous infection based on previous-step states; recovery order).

## Input
`<input_dir>/world.json`: width, height, radius, steps, recover_steps, and
entities `[{x, y, vx, vy, state}, ...]` with state "S" or "I".

## Dynamics per step (as implemented)
1. Every entity moves by its velocity and reflects off the walls.
2. Susceptible ("S") entities that have at least one infected ("I") entity
   within `radius` (squared-distance comparison, using previous-step states)
   are marked for infection.
3. Entities already "I" advance their infection counter and become "R" once
   it reaches `recover_steps`; then newly marked entities become "I".
4. The number of "I" entities is recorded.

Output: infected count per step, final S/I/R counts, and a positional checksum.

## Scoring
Hidden worlds of the same format (larger). Score = baseline_runtime /
your_runtime. Any output mismatch = 0.
