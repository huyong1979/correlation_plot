# correlation_plot.py

Retrieve archived EPICS PV history from the NSLS-II channel archiver with
[`arget`](https://webhostapp.nsls2.bnl.gov), plot one or more PVs on a shared
time axis, and show the correlation of the **1st PV (Y)** against the
**2nd PV (X)**. It was originally written to study why the Booster injection
efficiency (`INJ-BI{}Eff:BRInj-I`) occasionally dropped, but it works as a
general-purpose PV history / correlation viewer.

## Requirements

- `arget` available on `PATH` (the NSLS-II conda-wrapped archiver client).
- Python 3 with `numpy` and `matplotlib`.

> **Note:** `arget` is a shell script that `source`s a conda environment and has
> no shebang, so it cannot be `execve`'d directly. The script runs it through
> `bash -lc`, which activates the environment and handles the `ENOEXEC`
> fallback automatically.

## Usage

```bash
correlation_plot.py                                        # defaults, 1-day history from yesterday
correlation_plot.py -s 2026-09-30                          # defaults, 2026-09-30 00:00 -> +1 day
correlation_plot.py -s 2026-09-30 -e 2026-10-01            # explicit window, defaults
correlation_plot.py -s 2026-09-30 -e 2026-10-01 \
    --pv-configs '{"pv1": [10, 100], "pv2": [0, 1320]}' --corr-step 100
```

Make it executable first (`chmod +x correlation_plot.py`) or call it with
`python3 correlation_plot.py ...`.

### Options

| Flag | Meaning | Default |
|------|---------|---------|
| `-s`, `--start` | Window start: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM[:SS]` | yesterday `00:00:00` |
| `-e`, `--end` | Window end, same formats | `start + 1 day` |
| `--pv-configs` | JSON object mapping each PV name to its valid `[min, max]` range | built-in `DEFAULT_PV_CONFIGS` |
| `--corr-step` | Bin width (in X-PV units) for the correlation panel | `DEFAULT_CORR_STEP` (`100`) |

Notes:

- Start/end accept either a bare date or a date plus time; `--end` must be after
  `--start`.
- `--pv-configs` takes **one quoted JSON object**, e.g.
  `--pv-configs '{"pv1": [10, 100], "pv2": [0, 1320]}'`. **Order matters**: the
  **1st PV is the Y signal** (e.g. efficiency) and the **2nd PV is the X signal**
  (e.g. target bucket) of the correlation panel.
- Each PV's `[min, max]` is its valid range; samples outside it are dropped as
  glitches (see filtering below).

### Default PV configs

| # | PV | Range `[min, max]` | Meaning |
|---|----|--------------------|---------|
| 1 | `INJ-BI{}Eff:BRInj-I` | `[10, 100]` | Booster injection efficiency [%] (Y) |
| 2 | `ACC-TS{}Bucket-SP` | `[0, 1320]` | Target bucket: start of RF buckets (X) |

The **1st PV is the Y signal** and the **2nd PV is the X signal**; this ordering
drives the correlation panel (see below).

## Output

For a start date `YYYY-MM-DD` the script creates an output directory named after
the start (`YYYY-MM-DD`, or `YYYY-MM-DD_HHMMSS` when a non-midnight start time is
given) containing:

- one `*.txt` file per PV with the raw `arget` output (posix timestamps), and
- `history_plot.png` — a stacked plot with one time-history panel per PV, plus a
  final **Y-vs-X correlation** panel when at least two PVs carry data.

## How it works

1. **Parse arguments** (`parse_args`, using `argparse`) — determine the start and
   end datetimes (`parse_datetime` accepts a bare date or date+time), the
   PV→`[min, max]` config map (`--pv-configs`, order-preserving JSON), and the
   correlation bin width (`--corr-step`); `--end` defaults to `start + 1 day`.
2. **Fetch** (`fetch`) — for each PV, run
   `arget -T posix --no-enum -s <start> -e <end> <pv>` via `bash -lc` and write
   stdout to `<outdir>/<safe_pv_name>.txt`. PV names are sanitized into
   filesystem-safe stems (`safe_name`).
3. **Load** (`load`) — parse each file into `(time, value)` NumPy arrays,
   skipping header lines, the trailing `Found N points` line, and any
   non-numeric/enum rows.
4. **Range filter** — for each PV, only samples within its configured
   `[min, max]` range are kept; anything outside (including archiver
   sentinel/invalid values such as negative numbers) is treated as a glitch and
   dropped.
5. **Plot** (`plot_all`) — draw one time-history panel per PV sharing the time
   (UTC) axis, using a zero-order-hold (`steps-post`) line that matches how the
   archiver stores values. Each panel shows a small statistics box (`N`, `max`,
   `min`, `ave`, `std`); a panel with no data is annotated accordingly.
6. **Correlation panel** (`correlate_xy`) — when both the Y signal (PV #1) and
   the X signal (PV #2) carry data, a final panel plots the **average of Y vs X**.
   Each Y sample is paired with the X value active at that instant (zero-order
   hold, `value_at`), X is rounded into bins of width `--corr-step`, and the
   mean ± std of Y is drawn for each bin. This reveals whether Y depends on X.
   The figure is saved to `history_plot.png`.

## Example

```bash
./correlation_plot.py -s 2026-09-30 -e 2026-10-01 \
    --pv-configs '{"INJ-BI{}Eff:BRInj-I": [10, 100], "ACC-TS{}Bucket-SP": [0, 1320]}' \
    --corr-step 100
```

```
Window    : 2026-09-30 00:00:00  ->  2026-10-01 00:00:00  (UTC)
Output    : 2026-09-30/
PVs       : 2
Corr step : 100
  fetching INJ-BI{}Eff:BRInj-I   -> 2026-09-30/INJ_BI_Eff_BRInj_I.txt
           dropped 36 samples outside [10, 100]
           1260 samples
  ...
Saved plot: 2026-09-30/history_plot.png
```
