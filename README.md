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
analyze_eff.py                                   # default PVs, 1-day history from yesterday
analyze_eff.py 2026-08-01                         # default PVs, 2026-08-01 00:00 -> 2026-08-02 00:00
analyze_eff.py 2026-08-01 06:30:00                # default PVs, starting at given date+time (+1 day)
analyze_eff.py 2026-08-01 00:00:00 pv1 pv2 pv3    # custom PV list over the same window
```

Make it executable first (`chmod +x analyze_eff.py`) or call it with
`python3 analyze_eff.py ...`.

### Argument rules

- The **first argument**, if it looks like a date (`YYYY-MM-DD`), sets the start
  date. A following `HH:MM[:SS]` token sets the start time (default
  `00:00:00`).
- If **no date** is given, the window defaults to **yesterday** at `00:00:00`.
- The query window is **always 1 day** (`start` → `start + 24 h`).
- Any **remaining arguments** replace the default PV list.

### Default PV list

| # | PV | Meaning |
|---|----|---------|
| 1 | `INJ-BI{}Eff:BRInj-I` | Booster injection efficiency [%] |
| 2 | `ACC-TS{}Bucket-SP` | Start of RF buckets to be filled |
| 3 | `LN-TS{EVR:EGUN-Out:FP3}WfCalc:Width-SP` | e-Gun pulser width → bunch-train length |
| 4 | `LN-TS{EVR:EGUN-Out:FP3}Ena-Sel` | e-Gun pulse disable / enable |

## Output

For a start date `YYYY-MM-DD` the script creates an output directory named after
the start (`YYYY-MM-DD`, or `YYYY-MM-DD_HHMMSS` when a non-midnight start time is
given) containing:

- one `*.txt` file per PV with the raw `arget` output (posix timestamps), and
- `history_plot.png` — a stacked plot with one panel per PV.

## How it works

1. **Parse arguments** (`parse_args`) — determine the start datetime and the PV
   list following the rules above; the end time is always `start + 1 day`.
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
5. **Plot** (`plot_all`) — draw one panel per PV sharing the time (UTC) axis,
   using a zero-order-hold (`steps-post`) line that matches how the archiver
   stores values. Each panel shows a small statistics box (`N`, `max`, `min`,
   `ave`, `std`); a panel with no data is annotated accordingly. The figure is
   saved to `history_plot.png`.

## Example

```bash
./analyze_eff.py 2026-08-01
```

```
Window : 2026-08-01 00:00:00  ->  2026-08-02 00:00:00  (UTC)
Output : 2026-08-01/
PVs    : 4
  fetching INJ-BI{}Eff:BRInj-I   -> 2026-08-01/INJ_BI_Eff_BRInj_I.txt
           dropped 4 glitch samples <= 10% (efficiency)
           1107 samples
  ...
Saved plot: 2026-08-01/history_plot.png
```
