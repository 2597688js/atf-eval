# METRICS.md — pointer, not a copy

The frozen ATF scoring specification lives in
[`agent-eval-main/METRICS.md`](agent-eval-main/METRICS.md). That folder is the
canonical source of truth for metric formulas, weights, the normalized
trajectory schema, and the deviation taxonomy.

This stub exists only so `METRICS.md` still resolves from the repo root, as
older docs and links expect. **Do not duplicate spec content here** — a prior
duplicate copy of this file drifted out of sync with the real spec and had to
be reconciled by hand (see `ATF_SESSION_NOTES.md`'s "METRICS.md alignment"
entry); keeping exactly one copy, in `agent-eval-main/`, is what prevents that
from happening again.

If you're implementing or reviewing a metric, read `agent-eval-main/METRICS.md`
directly. If you're implementing the schema contract an adapter must produce,
read `agent-eval-main/schema/normalized_trajectory.schema.json`.
