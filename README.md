# flakelens

**Find the flaky tests in your suite before they erode trust in your CI.**

A flaky test is one that passes and fails on the same code. Every team has
them: a payment-gateway timeout, a race in a WebSocket test, a selector that
is not visible "yet". They are expensive in quiet ways: people re-run
pipelines, stop trusting red builds and eventually ignore real failures.

`flakelens` reads the JUnit XML reports your test runner already produces,
keeps their history in a local SQLite database and tells you which tests
are **flaky**, which are genuinely **broken**, and which are **stable**.

```text
$ flakelens report
11 tests analyzed: 3 flaky, 1 broken, 6 stable, 1 skipped

STATUS  FLIP  FAIL  FAILED/RUNS  TEST
------  ----  ----  -----------  --------------------------------------------------------------
FLAKY   36%   17%   2/12         tests.test_search::test_autocomplete_suggestions
FLAKY   27%   33%   4/12         tests.test_notifications::test_websocket_receives_order_update
FLAKY   27%   25%   3/12         tests.test_checkout::test_payment_gateway_timeout
BROKEN  9%    42%   5/12         tests.test_promotions::test_expired_coupon_is_rejected
```

## Features

- **Works with any test runner** that emits JUnit XML: pytest, Jest
  (jest-junit), Cypress, Playwright, Maven Surefire, Gradle, and more.
- **Tells flaky apart from broken.** A test that started failing and keeps
  failing is a regression, not flakiness, and is reported separately.
- **Same-commit detection.** Tag imports with `--commit` and a test that both
  passed and failed on the same commit is flagged immediately.
- **CI gate.** `flakelens report --fail-on-flaky` exits with code 1 when
  flaky tests are found.
- **Safe re-imports.** Reports are fingerprinted (SHA-256), so importing the
  same file twice never skews the numbers.
- **JSON output** for dashboards and scripts.
- **Zero runtime dependencies.** Pure Python standard library.

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/<your-user>/flakelens.git
cd flakelens
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

Try it with the bundled sample data (12 simulated CI runs of an e-commerce
suite):

```bash
python examples/generate_sample_reports.py   # writes examples/reports/run-01.xml ... run-12.xml
flakelens import examples/reports
flakelens report
flakelens history websocket
```

Use it on your own project:

```bash
pytest --junitxml=reports/run.xml
flakelens import reports/run.xml --commit "$(git rev-parse HEAD)" --branch main
flakelens report
```

## Commands

| Command | What it does |
| --- | --- |
| `flakelens import REPORT... [--commit SHA] [--branch NAME]` | Import report files, directories (every `*.xml` inside) or glob patterns. |
| `flakelens report [--status S] [--min-runs N] [--branch B] [--limit N] [--format table\|json] [--fail-on-flaky]` | Analyze history. `--status` is `problems` (default: flaky + broken), `all`, `flaky`, `broken`, `stable`, `insufficient` or `skipped`. |
| `flakelens history TEST` | Every recorded result of one test. `TEST` may be any unique part of its id. |
| `flakelens runs` | List imported runs. |

The database lives at `.flakelens/flakelens.db` by default. Override it with
`--db PATH` or the `FLAKELENS_DB` environment variable.

## How tests are classified

Runs are ordered by import order. Skipped runs are ignored. For each test:

1. **Same-code conflict -> FLAKY.** The test passed *and* failed on the same
   commit (or inside one report, e.g. after a retry). The code did not change,
   the result did. This needs no minimum number of runs.
2. **Fewer than `--min-runs` executions (default 3) -> INSUFFICIENT.**
3. **Two or more flips -> FLAKY.** A *flip* is a change between pass and fail
   in consecutive runs. A single flip is just a regression (pass -> fail) or a
   fix (fail -> pass); `pass -> fail -> pass` is a test that keeps changing
   its mind.
4. Otherwise **BROKEN** if the latest run failed, **STABLE** if it passed.

`FLIP` is the share of consecutive runs whose outcome changed and is the main
sort key. `FAIL` is the overall failure rate.

## Project layout

```text
src/flakelens/
  parser.py     JUnit XML -> CaseResult (tolerant of reporter differences)
  storage.py    SQLite persistence (runs, results)
  analysis.py   flaky / broken / stable classification
  cli.py        argparse command-line interface
tests/          pytest suite (unit + end-to-end CLI tests)
examples/       sample report generator
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

CI runs the test suite on Python 3.10-3.13 on Linux and Windows. It also
imports its own test results with flakelens and runs a report.

## Roadmap

- [ ] **Retry awareness.** Read Surefire `<flakyFailure>` and
      pytest-rerunfailures `<rerunFailure>` elements: a pass after a retry
      is flakiness, not a pass.
- [ ] **CI metadata auto-detection.** Pick up the commit and branch from
      `GITHUB_SHA`/`GITHUB_REF_NAME`, GitLab and Jenkins variables.
- [ ] **Time windows.** `--last N` runs / `--since DATE`, so fixed tests
      leave the report.
- [ ] **Duration analysis.** Detect slow and increasingly slow tests.
- [ ] **HTML report and web dashboard** with per-test timelines.
- [ ] **GitHub Action** that comments flaky-test summaries on pull requests.
- [ ] **Quarantine export.** Generate a skip list or pytest marker file for
      known-flaky tests.
- [ ] **Failure clustering.** Group failures with similar messages to point
      at shared root causes.

## License

MIT
