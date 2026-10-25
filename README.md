# DC Initiative 86: independent agentic forecasts

DC votes on Initiative 86 on November 3, 2026. If it passes, the measure bans force-feeding birds and
the sale of "fattened bird liver products" in DC from July 1, 2027. This repository asks several AI
forecasters, each working alone with web search, what follows if it passes and if it fails. It then
pools their answers through a causal map.

The question behind it: does a small animal-welfare win make bigger reforms likelier (a stepping stone),
or does it release the pressure? The same map also covers what opponents care about: restaurant sales
and jobs, liver pâté, lawsuits, and a congressional rider.

## Design

**A causal map, in the spirit of Metaculus's Radiant.** `graph/graph.yaml` defines 23 nodes, each a
forecast question with an absolute unit and a resolution source. The vote sets the scenario. If it
passes, one question gives the sale ban's status on 2028-12-01 as exclusive options: repealed by the
Council, barred by Congress, blocked by a court, unfunded (so section 8(a) holds it back), or applying.
A single question keeps those outcomes from being drawn independently of each other. The status feeds
the direct outcomes: menus, sales tax collections, employment, and ducks force-fed. The vote and
Denver's same-day foie gras measure feed the political spillovers.

**Conditional forecasts at vote-share cells.** Every forecaster gives each node at certified Yes shares
of 42%, 49.5%, 50.5%, 60% and 72%. There are two exceptions: nodes that exist only if it passes take
only the passing shares, and nodes the margin barely moves take only 49.5% and 50.5%. Where a node
depends on another node, the forecaster also conditions on that node's outcome (for example, menus in
December 2028 if the measure failed, if it passed and was removed, if it passed unfunded, or if the
ban applies).

**Absolute distributions.** Quantities take five quantiles in their own units, such as establishments,
votes, dollars, jobs or birds. Yes/no questions take probabilities, and the ban's status takes a
probability for each option. The Yes share takes a full cumulative distribution.

**The cutoff contrast.** Comparing the 49.5% and 50.5% cells separates what passing changes from what
a large margin reveals about voters. This follows the paired within-run design of
[dc-mayor-llm-forecast](https://github.com/MaxGhenis/dc-mayor-llm-forecast), and the paired legal-state
arms of Thesis's bill lane.

Denver votes the same day, so DC's result cannot cause Denver's. The simulator interpolates Denver's
question across 50% and holds it at 50% in both cutoff arms.

**Pooling.** `src/i86/simulate.py` runs a Monte Carlo through the map for each forecaster, and every
draw keeps one forecaster's answers together. Under each condition the pooled summary weights each
forecaster's own conditional distribution equally, whatever that forecaster thinks the chance of
passing is. Pooling the raw draws instead would let the forecasters who expect it to pass dominate the
"passes" column. Each node is reported:
- if the measure fails and if it passes (their gap also carries what the result says about voters, so
  it is not an effect);
- in the close bands (47–50% and 50–53%);
- at a fixed 49.5% and 50.5%, with shared random numbers (their difference is what a bare pass changes);
- per Yes ballot, which is the cutoff effect times the chance one ballot decides the measure.

Runs count equally. With four Claude Opus 5.5 runs and four GPT-6.1 Sol runs, the two model families
also count equally. Runs of one model on one prompt are not independent opinions.

**The chance one ballot decides it.** This comes from the same distributions. The margin in votes is
`N(2V − 1)`, and a ballot changes the outcome at one value of that margin. So the chance is about
`f_V(½) / 2N`, averaged over the forecaster's turnout distribution.

## Run it

```bash
uv venv --python 3.13
uv pip install -e ".[dev]"
.venv/bin/i86 prompt                     # regenerate prompts/forecaster.md from the graph
.venv/bin/pytest -q
```

Dispatch forecasters with any of three backends:

```bash
.venv/bin/i86 dispatch subfleet opus-1 --tier standard -m opus      # the author's lanes: Claude Opus 5.5
.venv/bin/i86 dispatch subfleet sol-1 --tier hard                    # the author's lanes: GPT-6.1 Sol
.venv/bin/i86 dispatch claude my-run -m claude-opus-5-5              # Claude Code, bare, web tools only
.venv/bin/i86 dispatch manual my-run                                 # paste any agent's answer yourself
```

Then collect, check, audit and pool:

```bash
.venv/bin/i86 collect      # copy subfleet answers into runs/<label>/response.md once all have finished
.venv/bin/i86 check        # parse and validate every response
.venv/bin/i86 audit        # check each transcript's tool calls
.venv/bin/i86 simulate     # pool the accepted runs into outputs/
.venv/bin/i86 prereg       # hash everything into prereg/SHA256SUMS and timestamp it
```

`simulate` is deterministic given the committed responses and the seed, and each run's draws depend
only on its own label. The `claude` backend runs Claude Code in bare mode, which skips hooks, memory and
CLAUDE.md files but needs `ANTHROPIC_API_KEY`. A response that fails `check` is not repaired: dispatch
a fresh run under a new label.

## Independence

Every forecaster gets the same prompt, byte for byte; its SHA-256 is in `prompts/forecaster.md.sha256`
and in each run's `meta.json`, and `simulate` pools only runs made with the current prompt. Forecasters
work in empty directories outside the repository, and the prompt tells them not to read local files.
No subfleet answer is copied into the repository until every subfleet run has finished, so a run that
starts late cannot find an earlier answer there. Each forecaster also reports anything in its context,
other than the brief, that mentions the measure (`forecaster.prior_context`).

`i86 audit` reads each run's own transcript. Any of these is a violation:
- a call that names the repository, another run's work directory, an agent's home or job store, or the
  author's notes;
- a broad search of the home directory or the filesystem;
- any MCP tool.

Other local calls are listed for review. A run with no parseable transcript fails the audit, and
`simulate` pools only runs that pass. `--allow-unaudited` admits manual runs.

## Files

- `graph/graph.yaml`: the map: nodes, cells, states and resolution criteria.
- `context/`: the measure's text and the CFO's fiscal impact statement, given to every forecaster.
- `prompts/forecaster.md`: the generated prompt; `schemas/template.json`: the response template.
- `runs/<label>/`: each run's prompt, metadata, verbatim answer, parsed response and audit.
- `outputs/`: pooled summaries (`summary.md`, `summary.json`, `nodes.csv`, `runs.csv`).
- `src/i86/`: graph loading, response checks, samplers, simulator, pooling, report, runners and audit.
- `tests/`: property-based tests of the samplers and simulator invariants, and a differential test of
  the decisive-ballot formula against its closed form. Test responses are labelled MOCK.

## What the numbers are

They are model forecasts under stated scenarios. They are not observations, and the cutoff contrast is
not an observed causal estimate. Most questions resolve against public records between 2027 and 2033;
`us_ducks_force_fed_2030` has no source that can settle it and is logged unscored.

Each run's summary row shows two copying diagnostics: the share of its answers that are identical at
every cell, and identical at 49.5% and 50.5%. Quantity tails beyond the 5th and 95th percentiles extend
the neighbouring slope, so means of heavy right tails are understated. Count distributions treat their
top label (`5+`) as 5 in means.
