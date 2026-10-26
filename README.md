# DC Initiative 86: independent agentic forecasts

DC votes on Initiative 86 on November 3, 2026. If it passes, the measure bans force-feeding birds and
the sale of "fattened bird liver products" in DC from July 1, 2027. This repository asks several AI
forecasters, each working alone with web search, what follows if it passes and if it fails. It then
pools their answers through a causal map.

The question behind it: does a small animal-welfare win make bigger reforms likelier (a stepping stone),
or does it release the pressure? The same map also covers what opponents care about: restaurant sales
and jobs, liver pâté, lawsuits, and a congressional rider.

## Design

**A causal map, in the spirit of Metaculus's Radiant.** `graph/graph.yaml` defines 24 nodes, 22 of
them forecast questions with an absolute unit and a resolution source; two are derived by rule. The
vote sets the scenario. If it passes, one question gives the sale ban's status on 2028-12-01 as
exclusive options, the first that holds: repealed by the Council, barred by Congress, blocked by a
court, standing without the CFO's section 8(b) certification, or standing and certified. A single
question keeps those outcomes from being drawn independently of each other. The map records whether
the certification was made; it does not decide which provisions section 8(a) delays until then. The
status feeds the direct outcomes: menus, sales tax collections, employment, and ducks force-fed. The
vote and Denver's same-day foie gras measure feed the political spillovers.

**Conditional forecasts at vote-share cells.** Every forecaster gives each node at certified Yes shares
of 42%, 49.5%, 50.5%, 60% and 72%. There are two exceptions: nodes that exist only if it passes take
only the passing shares, and nodes that the ban's status, not the margin, mainly drives (the direct
outcomes, and a few spillovers) take only 49.5% and 50.5%. Where a node depends on another node, the
forecaster also conditions on that node's outcome: menus in December 2028, for example, if the
measure failed, if it passed and was removed, if it stands without certification, or if it stands
certified. Only pairs of cell and state that can occur are asked (no "removed" at 49.5%), 98 answers
in all.

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
draw keeps one forecaster's answers together. Each condition is its own simulation, with the Yes share
drawn from the forecaster's distribution truncated to that condition, so every forecaster gets the same
number of draws under "fails" however unlikely it thinks failing is. The pooled summary then weights
each forecaster's own conditional distribution equally. Pooling the raw draws of one simulation instead
would let the forecasters who expect it to pass dominate the "passes" column. Questions defined only
under a condition (the ban standing, say) report both the conditional probability and the joint one.
The conditional comes from a further simulation. When the condition turns on one node (the ban's
status), that node is drawn only from the values that satisfy it. The ban's status depends on nothing
but the Yes share, so the chance that a draw meets the condition is linear in the share between the
forecast cells, and the share is drawn exactly from the forecaster's distribution tilted by that
chance. Every draw then counts fully, with weight 1 (the condition's probability is kept apart), and a
forecaster that gives the condition 1 in 10,000 counts as much as one that gives it 9 in 10; only one
that gives it zero is left out, and the report says so. For a condition this cannot handle (one on a
node that also depends on other nodes, or on more than one node; the current map has none), each draw
is weighted by its probability of the condition, or the draws where it holds are kept, and the Yes
share comes from a defensive mixture: half from the forecaster's own distribution and half spread
evenly over the stretches of share it gives any probability, each draw weighted to undo the mixture.
Each node is reported:
- if the measure fails and if it passes (their gap also carries what the result says about voters, so
  it is not an effect);
- in the close bands (47–50% and 50–53%);
- at a fixed 49.5% and 50.5%, with shared random numbers (their difference is what a bare pass changes);
- per Yes ballot: each forecaster's cutoff effect times its chance that one ballot decides the
  measure, averaged over forecasters.

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
.venv/bin/i86 dispatch manual my-run                                 # stage any agent's answer yourself
```

Then collect, check, audit and pool:

```bash
.venv/bin/i86 collect      # once every run has finished, copy answers and transcripts into runs/
.venv/bin/i86 abandon LABEL  # mark a run that will never finish (a killed process), so collect can proceed; final
.venv/bin/i86 check        # parse and validate every response
.venv/bin/i86 audit        # check each transcript's tool calls
.venv/bin/i86 simulate     # pool the accepted runs into outputs/ (see Independence for exclusions)
.venv/bin/i86 prereg       # hash everything into prereg/SHA256SUMS and timestamp it
```

`simulate` is deterministic given the committed responses and the seed, and each run's draws depend
only on its own label. The `claude` backend runs Claude Code in bare mode, which skips hooks, memory and
CLAUDE.md files but needs `ANTHROPIC_API_KEY`. A response that fails `check` is not repaired: dispatch
a fresh run under a new label. Once any answer is in `runs/`, `dispatch` refuses a new run unless it is
marked `--late`, and the report flags late runs.

## Independence

Every forecaster gets the same prompt, byte for byte; its SHA-256 is in `prompts/forecaster.md.sha256`
and in each run's `meta.json`, and `simulate` pools only runs made with the current prompt. Subfleet
lanes add their own preamble; `collect` saves exactly what the model was given as
`runs/<label>/prompt.sent.md`, with its hash. Forecasters work in empty directories outside the
repository, and the prompt tells them not to read local files. No answer enters the repository until
every run has finished: the `claude` and `manual` backends write to a staging directory, and
`collect` copies answers in only when no run of any backend is still going. `prepare`, `abandon` and
`collect` take one lock on the staging area, and `collect` checks the list of runs again under it
before copying anything, so a run dispatched while it works holds it back. The lock also holds
between threads of one process. A run marked abandoned stays abandoned even if its process later
reports back or an answer is staged for it; what arrives is kept as the run's `backend_state`.

Each forecaster reports, before researching, anything in its context other than the brief that
mentions the measure (`forecaster.prior_context`). `simulate` excludes a run whose report mentions
these questions, other than a bare "none"; after reading it, `--accept-prior <label>` admits it.

`i86 audit` reads each run's own transcript and parses every shell command with tree-sitter's bash
grammar: quoting, pipes, here-documents, subshells, command substitutions, redirections (`cat <file`),
loops, functions and the rest, with the grammar's misreading of `!` before a compound command
repaired. It tracks the working directory as the set of places the shell could be, each with the
last command's exit status. `&&`, `||`, `if`, loops and `case` run their parts only where the status
allows (the audit knows `true`, `false`, `cd`, tests of known values and files present, literal
`case` values; after anything else, either way may have run). A `cd`, `pushd` or `popd` moves every
place, following `CDPATH`, functions, aliases, `eval`, `env -C` and the like, and positional
parameters for `sh -c` and shell code on standard input; one inside a subshell, a command
substitution, a pipeline stage or a background job does not move the commands after it. zsh is the
exception twice over: it runs a pipeline's last stage in the current shell (`x | cd d`, a `while read`
loop at the end of a pipeline), and of `cd a && make &` it runs only `make` in the background. The
audit follows the shell a command names (`zsh -c`, `bash -c`) and otherwise keeps both outcomes. Scratch
directories are often gone by the time the audit runs, so a `cd` to a missing directory (or one the
command makes only later) leaves the shell either there or where it was, and the second place is an
alternative. Loops are followed pass by pass, through `break`, `continue` and `return`, until they
end or repeat a state (after 12 passes changing variables become unknown, and after 24 the audit
stops following the directory), and arithmetic is evaluated where bash and zsh agree on it. Words
split into fields as each shell splits them (bash splits unquoted variables at `IFS`, zsh does not;
both split command substitutions and drop empty unquoted expansions), and so do `read` and bash
3.2's here-strings. A new shell (`sh -c`, a script) sees only exported variables. A script written by
an earlier tool call, or present in the work directory, is read when it is run. Variables, `read`
from a known input, and variables, functions and aliases that branches may each have set
differently (or not at all) are followed in each version. The audit resolves every local path from every place, expands globs, takes a command's own
directory option (`git -C`, `tar -C`) as a further base, and reads each search tool's and
interpreter's options as that tool does, so it mistakes neither a search pattern nor a `python -c`
or awk program for a path, while still scanning that code for paths and for a literal `os.chdir`.
Running a file by path counts as reading it, and so does a `file://` URL. These exclude the run:
- a path resolved from a main place in, or text naming, the repository, the staging area, another
  run's work directory, an agent's home or job store, or the author's notes;
- a search rooted at the home directory or above, or `locate` or `mdfind`;
- a content search, or a name search whose results reach another command (through `xargs`, a shell,
  a read loop, a command substitution, `find -exec` or `fd -x`), rooted above any of those;
- any MCP tool.

Calls that warrant reading without excluding the run are listed as suspect: a name-only search above a
protected place, a listing of the home directory, a relative path after a `cd` the audit cannot follow
(an unexpandable target, more possible places than it tracks), a path
or search from an alternative place, or with a part the audit cannot work out, that would reach a
protected place, a command the parser cannot fully read, a path outside the work directory next to a
term from these questions, a web call that opens this repository (it holds no answers until every run
has finished), and sub-agent calls. The summary counts them per run. A run with no parseable
transcript fails the audit, and `simulate` pools only runs that pass. `--allow-unaudited` admits manual
runs, which have no transcript. Whether a directory exists is judged at audit time, apart from what the
same command makes or removes. A generated-program test (`tests/test_audit_shell_differential.py`)
runs each program under bash and zsh and checks that every program that reads a MOCK answer is
reported, that the audit's possible places include where the shell ended, and that where the audit
has one place it is that one. `tests/test_audit_shell_semantics.py` checks the arithmetic, `read`,
field splitting and here-strings against both shells on generated inputs. The audit catches
accidental and casual reads, not a forecaster set on hiding them.

## Files

- `graph/graph.yaml`: the map: nodes, cells, states and resolution criteria.
- `context/`: the measure's text and the CFO's fiscal impact statement, given to every forecaster.
- `prompts/forecaster.md`: the generated prompt; `schemas/template.json`: the response template.
- `runs/<label>/`: each run's prompt (and the prompt as sent), metadata, verbatim answer, transcript,
  parsed response and audit.
- `outputs/`: pooled summaries (`summary.md`, `summary.json`, `nodes.csv`, `runs.csv`).
- `src/i86/`: graph loading, response checks, samplers, simulator, pooling, report, runners and audit.
- `tests/`: property-based tests of the samplers and simulator invariants; differential tests of the
  decisive-ballot formula against its closed form and of the weighted conditionals against plain
  filtering; audit cases, including every bypass found in review, and the audit against bash and zsh
  on generated programs; and the staging and pooling rules. `test_review_r3_*.py` to
  `test_review_r6_*.py` are the independent reviews' probes, kept as regression tests. Test responses
  are labelled MOCK.

## What the numbers are

They are model forecasts under stated scenarios. They are not observations, and the cutoff contrast is
not an observed causal estimate. Most questions resolve against public records between 2027 and 2033;
`us_ducks_force_fed_2030` has no source that can settle it and is logged unscored.

Each run's summary row shows two copying diagnostics: the share of its answers that are identical at
every cell, and identical at 49.5% and 50.5%. Quantity tails beyond the 5th and 95th percentiles extend
the neighbouring slope, so means of heavy right tails are understated. Count distributions treat their
top label (`5+`) as 5 in means.

## License

MIT. See [LICENSE](LICENSE).
