# Running ATF for `collection_agent` — 3-script dataset

For prerequisites, environment setup, and the general step-by-step walkthrough, see
`GETTING_STARTED.md` §5 in this same folder. This file covers just one thing: running the
fastest possible live example — 3 scripts from the categories with the fewest turns each
(a fixed 8 turns, vs. 9-11 for most others): **Wrong Contact, Suspicious Customer, Debt
Dispute**.

```bash
cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval/integrations/collection_agent"
source .venv/bin/activate
export PYTHONPATH="/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents:/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents/src"
export ANTHROPIC_API_KEY="sk-ant-..."   # optional, enables the real RS judge

# build the golden dataset (3 scripts, 24 turns total)
python3 convert_golden_dataset.py --categories "Wrong Contact,Suspicious Customer,Debt Dispute"

# run it -- took ~20-25 min total on the last run (varies with Ollama's cloud load)
python3 -u run_live_eval.py
```

## What to expect

This exact 3-script set has actually been run twice this session, so these numbers are a
real reference point, not a guess:

```
ATF score: 0.394    coverage: 100.0%
  NTS 0.904   STS 0.077   TIS 0.000   RS 1.000   OS 0.000
```

| Script | Category | ATF | NTS | STS | TIS | RS | OS |
|---|---|---:|---:|---:|---:|---:|---:|
| COLL_TRAJ_0841 | Wrong Contact | 0.408 | 0.951 | 0.075 | 0.000 | 1.00 | 0.00 |
| COLL_TRAJ_0861 | Suspicious Customer | 0.392 | 0.930 | 0.043 | 0.000 | 1.00 | 0.00 |
| COLL_TRAJ_0901 | Debt Dispute | 0.383 | 0.832 | 0.112 | 0.000 | 1.00 | 0.00 |

(`RS=1.000` here used the real Anthropic-backed judge; without `ANTHROPIC_API_KEY` set,
expect RS to fall back to its deterministic order-only component instead, typically in the
0.6-0.7 range for this set.) TIS and OS at exactly `0.000` is consistent across every run
this session — the live agent has not yet invoked a tool call or reached an outcome that
matched what these particular golden scripts expected.
