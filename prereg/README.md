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
| `2026-11-04-served/` | 05:19Z | the same files after the changes below | pending |

To check a manifest, run `shasum -a 256 -c prereg/<folder>/SHA256SUMS` from the repository root; it
lists any file whose bytes have changed. `ots verify prereg/<folder>/SHA256SUMS.ots` checks the proof
against a Bitcoin node. Without one, the digest the proof computes can be compared with the block's
merkle root from a block explorer. Commit 007eb25 did this for the first two stamps, and the commits
that added blocks 973255 and 974462 to the table did it for the third and fourth.

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
  suspect calls now names the session logs. A reader admitted the call with `--accept-suspect sol-3`,
  so sol-3 stays in the pool.
- Every other file in the previous manifest still matches.

After `2026-11-04-sessions/`:

- The session-log audit now counts a page the web tool served when its reply puts an escaped newline
  between the page's address and its cite marker. sol-1's and sol-2's new `codex-sessions/audit.json`
  count more served pages: 1,349 for sol-1, up from 1,308, and 671 for sol-2, up from 654. The audit
  accepts each added address, and no run's verdict or suspect count changed.
- The summary's note on suspect calls now lists what only a Codex run's session logs record, the
  pages the web tool served among them. No other line of `outputs/summary.md` changed.
- Every other file in the previous manifest still matches.
