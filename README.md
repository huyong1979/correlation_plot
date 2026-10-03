# analyze_eff.py

Retrieve archived EPICS PV history from the NSLS-II channel archiver with
[`arget`](https://webhostapp.nsls2.bnl.gov) and plot one or more PVs on a shared
time axis. It was originally written to study why the Booster injection
efficiency (`INJ-BI{}Eff:BRInj-I`) occasionally dropped to 0 %, but it works as a
general-purpose PV history viewer.

## Requirements

- `arget` available on `PATH` (the NSLS-II conda-wrapped archiver client).
- Python 3 with `numpy` and `matplotlib`.

> **Note:** `arget` is a shell script that `source`s a conda environment and has
> no shebang, so it cannot be `execve`'d directly. The script runs it through
> `bash -lc`, which activates the environment and handles the `ENOEXEC`
> fallback automatically.

## Usage

```bash
analyze_eff.py                                            # default PVs, 1-day history from yesterday
analyze_eff.py -s 2026-09-30                               # default PVs, 2026-09-30 00:00 -> +1 day
analyze_eff.py -s 2026-09-30 -e 2026-10-01                # explicit window, default PVs
analyze_eff.py -s 2026-09-30 -e 2026-10-01 --pvlist "pv1 pv2 pv3"   # custom PV list
```

Make it executable first (`chmod +x analyze_eff.py`) or call it with
`python3 analyze_eff.py ...`.

### Options

| Flag | Meaning | Default |
|------|---------|---------|
| `-s`, `--start` | Window start: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM[:SS]` | yesterday `00:00:00` |
| `-e`, `--end` | Window end, same formats | `start + 1 day` |
| `--pvlist` | A single string of whitespace-separated PV names | built-in `DEFAULT_PVS` |

Notes:

- Start/end accept either a bare date or a date plus time; `--end` must be after
  `--start`.
- `--pvlist` takes **one quoted string**, e.g. `--pvlist "pv1 pv2 pv3"`; the
  **first PV is treated as the efficiency signal** (see filtering below).

### Default PV list

| # | PV | Meaning |
|---|----|---------|
| 1 | `INJ-BI{}Eff:BRInj-I` | Booster injection efficiency [%] |
| 2 | `ACC-TS{}Bucket-SP` | Target bucket: start of RF buckets to be filled |

The **first PV is the efficiency signal** and the **second PV is the target
bucket**; this ordering drives the glitch filtering and the correlation panel
(see below).

## Output

For a start date `YYYY-MM-DD` the script creates an output directory named after
the start (`YYYY-MM-DD`, or `YYYY-MM-DD_HHMMSS` when a non-midnight start time is
given) containing:

- one `*.txt` file per PV with the raw `arget` output (posix timestamps), and
- `history_plot.png` — a stacked plot with one time-history panel per PV, plus a
  final **efficiency-vs-target-bucket** panel when at least two PVs are present.

## How it works

1. **Parse arguments** (`parse_args`, using `argparse`) — determine the start and
   end datetimes (`parse_datetime` accepts a bare date or date+time) and the PV
   list; `--end` defaults to `start + 1 day`.
2. **Fetch** (`fetch`) — for each PV, run
   `arget -T posix --no-enum -s <start> -e <end> <pv>` via `bash -lc` and write
   stdout to `<outdir>/<safe_pv_name>.txt`. PV names are sanitized into
   filesystem-safe stems (`safe_name`).
3. **Load** (`load`) — parse each file into `(time, value)` NumPy arrays,
   skipping header lines, the trailing `Found N points` line, and any
   non-numeric/enum rows.
4. **Filter efficiency glitches** — the **first PV in the list is treated as the
   efficiency signal**. Only samples with `value > 10` are kept; anything
   `<= 10 %` (including archiver sentinel/invalid values such as negative
   numbers) is treated as a glitch and dropped. All other PVs are left
   untouched.
5. **Plot** (`plot_all`) — draw one time-history panel per PV sharing the time
   (UTC) axis, using a zero-order-hold (`steps-post`) line that matches how the
   archiver stores values. Each panel shows a small statistics box (`N`, `max`,
   `min`, `ave`, `std`); a panel with no data is annotated accordingly.
6. **Correlation panel** (`eff_vs_bucket`) — when both the efficiency (PV #1) and
   the target bucket (PV #2) carry data, a final panel plots **average injection
   efficiency vs target bucket**. Each efficiency sample is paired with the
   target-bucket setpoint active at that instant (zero-order hold, `value_at`),
   the bucket is rounded to the nearest 100 (bins `0, 100, …, ~1300`), and the
   mean ± std efficiency is drawn for each bin. This reveals whether injection
   efficiency depends on the target bucket. The figure is saved to
   `history_plot.png`.

## Example

```bash
./analyze_eff.py -s 2026-09-30 -e 2026-10-01
```

```
Window : 2026-09-30 00:00:00  ->  2026-10-01 00:00:00  (UTC)
Output : 2026-09-30/
PVs    : 4
  fetching INJ-BI{}Eff:BRInj-I   -> 2026-09-30/INJ_BI_Eff_BRInj_I.txt
           dropped 36 glitch samples <= 10% (efficiency)
           1260 samples
  ...
Saved plot: 2026-09-30/history_plot.png
```
