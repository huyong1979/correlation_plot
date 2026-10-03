#!/usr/bin/env python3
"""
analyze_eff.py -- retrieve archived PV history with `arget` and plot it.

Usage
-----
    analyze_eff.py                                         # default PVs, yesterday (1 day)
    analyze_eff.py -s 2026-09-30                           # default PVs, 2026-09-30 -> +1 day
    analyze_eff.py -s 2026-09-30 -e 2026-10-01            # explicit window, default PVs
    analyze_eff.py -s 2026-09-30 -e 2026-10-01 --pvlist "pv1 pv2 pv3"

Rules
-----
* -s/--start : window start.  Accepts "YYYY-MM-DD" or "YYYY-MM-DD HH:MM[:SS]".
               Defaults to *yesterday* 00:00:00 when omitted.
* -e/--end   : window end (same formats).  Defaults to start + 1 day.
* --pvlist   : a single string of whitespace-separated PV names that replaces
               the default PV list.  Defaults to the built-in DEFAULT_PVS.
* Each PV is fetched with `arget`, written to a text file under an output
  directory named after the start date, then all PVs are plotted together.
"""
import os
import re
import sys
import shlex
import argparse
import subprocess
from datetime import datetime, timedelta

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# ------------------------------------------------------------------ defaults
DEFAULT_PVS = [
    "INJ-BI{}Eff:BRInj-I",                      # Booster injection efficiency [%]
    "ACC-TS{}Bucket-SP",                        # start of RF buckets to be filled
    "LN-TS{EVR:EGUN-Out:FP3}WfCalc:Width-SP",   # e-Gun pulser width -> bunch-train length
    "LN-TS{EVR:EGUN-Out:FP3}Ena-Sel",           # e-Gun pulse disable / enable
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


# ------------------------------------------------------------- CLI parsing
def parse_datetime(text):
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]' into a datetime."""
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        "invalid date/time %r (use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]')" % text)


def parse_args(argv):
    """Return (start_dt, end_dt, pv_list) from the raw argument list."""
    p = argparse.ArgumentParser(
        description="Retrieve archived PV history with arget and plot it.")
    p.add_argument("-s", "--start",
                   help="window start: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]' "
                        "(default: yesterday 00:00:00)")
    p.add_argument("-e", "--end",
                   help="window end, same formats (default: start + 1 day)")
    p.add_argument("--pvlist",
                   help="whitespace-separated PV names in one string "
                        "(default: built-in DEFAULT_PVS)")
    args = p.parse_args(argv)

    if args.start:
        start_dt = parse_datetime(args.start)
    else:
        yesterday = datetime.now() - timedelta(days=1)
        start_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)

    end_dt = parse_datetime(args.end) if args.end else start_dt + timedelta(days=1)

    if end_dt <= start_dt:
        p.error("end (%s) must be after start (%s)" % (end_dt, start_dt))

    pvs = args.pvlist.split() if args.pvlist else list(DEFAULT_PVS)
    if not pvs:
        p.error("--pvlist is empty")
    return start_dt, end_dt, pvs


# ------------------------------------------------------------- data fetch
def safe_name(pv):
    """Turn a PV name into a filesystem-safe file stem."""
    return re.sub(r"[^A-Za-z0-9]+", "_", pv).strip("_")


def fetch(pv, start_str, end_str, outfile):
    """Retrieve a PV with arget and write the raw output to `outfile`.

    `arget` is a conda-wrapper shell script with no shebang, so it must be
    run through bash (which handles the ENOEXEC fallback) rather than execve.
    """
    cmd = "arget -T posix --no-enum -s %s -e %s %s" % (
        shlex.quote(start_str), shlex.quote(end_str), shlex.quote(pv))
    with open(outfile, "w") as f:
        proc = subprocess.run(["bash", "-lc", cmd],
                              stdout=f, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sys.stderr.write("  ! arget failed for %s: %s\n"
                         % (pv, proc.stderr.decode(errors="replace").strip()))
    return outfile


def load(fn):
    """Load (time, value) arrays from an arget posix-time text file."""
    t, v = [], []
    try:
        with open(fn) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    t.append(float(parts[0]))
                    v.append(float(parts[1]))
                except ValueError:
                    continue          # header / "Found N points" / enum strings
    except IOError:
        pass
    return np.array(t), np.array(v)


# ------------------------------------------------------------- plotting
def dt(arr):
    return [datetime.utcfromtimestamp(x) for x in arr]


def plot_all(pvs, series, start_dt, end_dt, outpng):
    n = len(pvs)
    fig, axes = plt.subplots(n, 1, figsize=(15, max(2.4 * n, 3)),
                             sharex=True, squeeze=False)
    axes = axes[:, 0]
    colors = plt.get_cmap("tab10").colors

    fig.suptitle("PV history   %s  ->  %s  (UTC)"
                 % (start_dt.strftime("%Y-%m-%d %H:%M"),
                    end_dt.strftime("%Y-%m-%d %H:%M")),
                 fontsize=13, fontweight="bold")

    for i, (pv, ax) in enumerate(zip(pvs, axes)):
        t, v = series[pv]
        color = colors[i % len(colors)]
        if len(t):
            ax.plot(dt(t), v, color=color, lw=0.9, marker=".", ms=2,
                    drawstyle="steps-post")
            stat_txt = ("N=%d\nmax=%.3g\nmin=%.3g\nave=%.3g\nstd=%.3g"
                        % (len(v), v.max(), v.min(), v.mean(), v.std()))
            ax.text(0.008, 0.95, stat_txt, transform=ax.transAxes,
                    fontsize=8, va="top", ha="left", family="monospace",
                    bbox=dict(boxstyle="round", fc="lightyellow",
                              ec="gray", alpha=0.85))
        else:
            ax.text(0.5, 0.5, "no data", transform=ax.transAxes,
                    ha="center", va="center", color="red")
        ax.set_ylabel(pv, fontsize=8, rotation=0, ha="right", va="center")
        ax.grid(alpha=0.3)

    axes[-1].set_xlabel("UTC time")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(outpng, dpi=130)
    print("Saved plot: %s" % outpng)


# ------------------------------------------------------------- main
def main():
    start_dt, end_dt, pvs = parse_args(sys.argv[1:])
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    outdir = start_dt.strftime("%Y-%m-%d_%H%M%S") if start_dt.hour or start_dt.minute \
        else start_dt.strftime("%Y-%m-%d")
    os.makedirs(outdir, exist_ok=True)

    print("Window : %s  ->  %s  (UTC)" % (start_str, end_str))
    print("Output : %s/" % outdir)
    print("PVs    : %d" % len(pvs))

    series = {}
    for i, pv in enumerate(pvs):
        outfile = os.path.join(outdir, safe_name(pv) + ".txt")
        print("  fetching %-45s -> %s" % (pv, outfile))
        fetch(pv, start_str, end_str, outfile)
        t, v = load(outfile)
        # The FIRST PV is the efficiency signal: keep only v > 10 %,
        # anything <= 10 % is treated as a glitch and filtered out.
        if i == 0 and len(v):
            good = v > 10.0
            n_bad = int(np.sum(~good))
            if n_bad:
                print("           dropped %d glitch samples <= 10%% (efficiency)" % n_bad)
            t, v = t[good], v[good]
        series[pv] = (t, v)
        print("           %d samples" % len(t))

    outpng = os.path.join(outdir, "history_plot.png")
    plot_all(pvs, series, start_dt, end_dt, outpng)


if __name__ == "__main__":
    main()
