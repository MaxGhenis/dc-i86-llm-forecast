# Timestamps

`i86 prereg` writes `SHA256SUMS`, the SHA-256 of the graph, the prompt, the response template, the
context files, every run's `meta.json`, `response.md`, `response.json`, `audit.json` and
`transcript.jsonl`, a Codex run's `codex-sessions/audit.json` and `attempts.json`, and the files at
the top of `outputs/` (not the charts). It then stamps the manifest with OpenTimestamps.
Each dated folder keeps one manifest and its proof; `SHA256SUMS` and `SHA256SUMS.ots` at the top are
the latest.

| Folder | Written | Covers | Bitcoin blocks |
|---|---|---|---|
| `2026-10-26-collected/` | 07:35Z | hashes of the first eight runs, committed before their answers | 973210, 973213 |
| `2026-10-26-pooled/` | 08:01Z | all eleven runs, their audits and the pooled outputs | 973213, 973237 |
| `2026-10-26-revised/` | 14:40Z | the same files after the changes below | 973255 |
| `2026-11-04-sessions/` | 00:31Z | the same files after the changes below, plus the Sol runs' session-log audits and attempts | 974462 |
| `2026-11-04-served/` | 05:19Z | the same files after the changes below | 974487 |
| `2026-11-05-wording/` | 16:01Z | the same files after the changes below | 974697, 974704, 974752 |

To check a manifest, run `shasum -a 256 -c prereg/<folder>/SHA256SUMS` from the repository root; it
lists any file whose bytes have changed. `ots verify prereg/<folder>/SHA256SUMS.ots` checks the proof
against a Bitcoin node. Without one, the digest the proof computes can be compared with the block's
merkle root from a block explorer. Commit 007eb25 did this for the first two stamps, and the commits
that added the later blocks to the table did it for the other four.

## Changes after each stamp

After `2026-10-26-collected/`:

- opus-5 and opus-6 were still running. Collecting them at 07:48Z added the usual collection fields
  to their `meta.json`.
- That second collect also changed one field, `transcript`, in six earlier runs' `meta.json`
  (opus-1, opus-2, sol-1 to sol-4). It had pointed at the committed copy and now points at subfleet's
  job store. Commit 68d33e4 stops `collect` from touching a collected run and makes `audit` read the
  committed copy. Both copies of each transcript have the same bytes, so no audit result changed.
- Every answer and transcript in this manifest still matches.

After `2026-10-26-pooled/`:

- Commit 23e6f7d, a fix to the simulator's interpolation and sampler, changed two values in
  `outputs/summary.json` in their last bits:
  `nodes.us_new_coverage_2027_2032.Yc.p05` from 0.22226440432062206 to 0.2222644043206221, and
  `per_run.opus-3.nodes.us_new_coverage_2027_2032.Yc.p50` from 11.83224156361526 to
  11.832241563615261. The first also appears in `outputs/nodes.csv`.
- The round-7 audit changes (findings 2 to 9) leave every run's `audit.json` byte for byte the same.
- Every other file in this manifest still matches.

After `2026-10-26-revised/`:

- `scripts/audit_codex_sessions.py` audited the four Sol runs' session logs, which hold their
  sub-agents and the first attempts of sol-1 and sol-3 (see the README). This manifest adds each Sol
  run's `codex-sessions/audit.json` and `attempts.json`.
- That audit found one suspect call, in sol-3. `simulate` now adds that call to sol-3's count, so one
  cell of `outputs/summary.md`, sol-3's suspect calls, changed from 0 to 1. The summary's note on
  suspect calls now names the session logs. A Claude Code session read the call and admitted it with
  `--accept-suspect sol-3`, so sol-3 stays in the pool.
- Every other file in the previous manifest still matches.

After `2026-11-04-sessions/`:

- The session-log audit now counts a page the web tool served when its reply puts an escaped newline
  between the page's address and its cite marker. sol-1's and sol-2's new `codex-sessions/audit.json`
  count more served pages: 1,349 for sol-1, up from 1,308, and 671 for sol-2, up from 654. The audit
  accepts each added address, and no run's verdict or suspect count changed.
- The summary's note on suspect calls now lists what only a Codex run's session logs record, the
  pages the web tool served among them. No other line of `outputs/summary.md` changed.
- Every other file in the previous manifest still matches.

After `2026-11-04-served/`:

- The session-log audit now reports a first line that names the work directory but does not parse,
  whichever way its quotes pair. It counts a line that gives a key twice or nests more than 64 levels
  as one that does not parse. It flags a record with a field of a type its checks cannot read, a
  session that gives a start time it cannot read, and any script nested deeper than its checks read.
  It fails a run whose transcript holds an item of a type it cannot read. It writes each number a
  cell writes out as JavaScript writes it in a string, however many digits it has. Re-auditing the
  four Sol runs leaves every `codex-sessions/audit.json` and `attempts.json` byte for byte the same.
- The audit now also fails a run whose transcript holds a line it cannot read or gives a thread id that
  is not a string, and its check of the transcript counts each item that repeats another's id. It flags
  a tool output or a command's working directory of a type its checks cannot read. In the strings a
  cell builds, it reads `true`, `false` and `null`, reads a template's line breaks as JavaScript does,
  and joins the two halves of a character that two strings spell. It reads the first line of every
  session log to find a run's threads. It flags a log it cannot open and a session in a folder inside
  the work directory or at another path that names it. It also flags a log that names the work
  directory without saying on its first line where its thread started. Re-auditing the four Sol runs
  again leaves every `codex-sessions/audit.json` and `attempts.json` byte for byte the same.
- The audit now also fails a run whose transcript holds any line but the thread's one start, events of
  its turns that hold no call, and items that each complete with the calls they started with. It flags
  a log that names the work directory but whose first line gives no absolute path for where its
  thread started, an agent path it cannot read, and a command run in a relative folder or one with a
  `..` part. Anything but a regular file in a kept copy's place stops it, and so does a kept copy it
  cannot read. Re-auditing the four Sol runs leaves every `codex-sessions/audit.json` and
  `attempts.json` byte for byte the same.
- `simulate` also checks each audit's work directory, job and counts, and that each thread's own audit
  read one event or more. It checks which threads the audit marks as collected, and with which attempt.
  It checks each thread's fields, and its counts of events and calls against its items, and excludes a
  run whose audit or attempts file it cannot read as JSON. `prereg` stops at anything but a regular
  file in place of a run's file.
- The audit's check of the transcript now compares a call in a message's line, and compares ids that
  are numbers exactly, as `i86 audit` pairs them. The audit flags a log whose first line gives, as the
  folder where its thread started, a path with a NUL or a character UTF-8 cannot encode, and a command
  run in a folder that a file URL places on another host. A link in place of `codex-sessions/` stops
  it. So does a link, anything but a regular file, or a file it cannot write in place of
  `audit.json`. `prereg` stops at a file it cannot read. Re-auditing the four Sol runs leaves every
  `codex-sessions/audit.json` and `attempts.json` byte for byte the same.
- `simulate` now requires each thread's web, suspect and local calls to add up to its calls. The
  audit flags a folder of the lanes it cannot list, and a transcript line that starts or updates an
  item with a call in its `message`. It stops when it cannot list or write in `codex-sessions/`. It
  writes each kept copy and `attempts.json` only where nothing sits yet, and writes `audit.json` to a
  new file that it renames into place. `prereg` stops at a run's file in a folder it may not search.
  Re-auditing the four Sol runs leaves every `codex-sessions/audit.json` and `attempts.json` byte for
  byte the same.
- `simulate` now also requires each thread's audit to list only searches and commands as suspect calls
  and only commands as local calls, no more of either than the thread made, and each thread to name a
  kept log of its own. The audit flags a command that a thread ran in a folder whose file URL holds a
  `?`, `#` or `%`. It writes each kept copy, `attempts.json` and `audit.json` in full to a part file
  before it gives the file its name, and removes the part file a process left when it died part way
  through a write. It stops when it cannot search `codex-sessions/` or remove such a part file.
  `prereg`, `simulate` and the audit stop, by name, at a `runs/` they cannot list and at a run folder
  they may not search, and the audit at a collected run's `meta.json` that it cannot read as a JSON
  object. Re-auditing the four Sol runs leaves every `codex-sessions/audit.json` and `attempts.json`
  byte for byte the same.
- The audit's check of the transcript now fails a run whose transcript records the log's calls in
  another order. It counts two commands as one call when they match as written, or when a shell reads
  nothing but words from each and the same words from both. The audit and `simulate` count an attempt
  as started when subfleet's record gives it a session, a start time, an outcome class other than
  `unknown`, or the state `starting`, `running`, `finalizing` or `succeeded`. With no attempts on
  record, they fail a run that collected anything but its own job's first attempt. The audit also
  flags a command that ran in a folder whose file URL holds a control character, and a run that gives
  as its job anything but a string. `prereg`, `simulate` and the audit stop at a link in place of
  `runs/` or of a run folder. Re-auditing the four Sol runs leaves every `codex-sessions/audit.json`
  and `attempts.json` byte for byte the same.
- The summary's note on suspect calls now says the audit cannot clear them, and that `simulate` pools
  such a run only when `--accept-suspect` names it. No other line of `outputs/summary.md` changed.
- Every other file in this manifest still matches.

After `2026-11-05-wording/`:

- `simulate` now excludes a run that gives as its job anything but a string, and a run with a link at
  `codex-sessions/`, `audit.json` or `attempts.json`. `prereg` stops at a link in place of any run
  file or of `codex-sessions/`. The audit stops at a link anywhere in `codex-sessions/`, before it
  reads or removes anything there, and at a label that does not name one folder in `runs/`. It keeps
  as written a command whose first word starts with `%`, since zsh reads a bare one as a job. A job
  no command can name, or a reply from subfleet that does not decode as UTF-8, gives no attempts on
  record. Re-auditing the four Sol runs leaves every `codex-sessions/audit.json` and `attempts.json`
  byte for byte the same.
- Every file in this manifest still matches.
