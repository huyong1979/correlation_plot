#!/usr/bin/env python3
"""
correlation_plot.py -- retrieve archived PV history with `arget`, plot each PV,
and show the correlation of the 1st PV (Y) vs the 2nd PV (X).

Usage
-----
    correlation_plot.py                                    # defaults, yesterday (1 day)
    correlation_plot.py -s 2026-09-30                      # defaults, 2026-09-30 -> +1 day
    correlation_plot.py -s 2026-09-30 -e 2026-10-01        # explicit window, defaults
    correlation_plot.py -s 2026-09-30 -e 2026-10-01 \\
        --pv-configs '{"pv1": [10, 100], "pv2": [0, 1320]}' --corr-step 100

Rules
-----
* -s/--start    : window start.  "YYYY-MM-DD" or "YYYY-MM-DD HH:MM[:SS]".
                  Defaults to *yesterday* 00:00:00 when omitted.
* -e/--end      : window end (same formats).  Defaults to start + 1 day.
* --pv-configs  : a JSON object mapping each PV name to its valid value range
                  [min, max].  Samples outside the range are dropped as glitches.
                  Order matters: the 1st PV is the Y signal (e.g. efficiency) and
                  the 2nd PV is the X signal (e.g. target bucket) of the
                  correlation panel.  Defaults to DEFAULT_PV_CONFIGS.
* --corr-step   : bin width (in X-PV units) for the correlation panel.
                  Defaults to DEFAULT_CORR_STEP.
* Each PV is fetched with `arget`, written to a text file under an output
  directory named after the start date, then all PVs are plotted together.
"""
import os
import re
import sys
import json
import shlex
import argparse
import subprocess
from collections import OrderedDict
from datetime import datetime, timedelta

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# ------------------------------------------------------------------ defaults
# Ordered mapping: PV name -> [min, max] valid range.
# 1st entry = Y signal (efficiency), 2nd entry = X signal (target bucket).
DEFAULT_PV_CONFIGS = OrderedDict([
    ("INJ-BI{}Eff:BRInj-I", [10, 100]),   # Booster injection efficiency [%]
    ("ACC-TS{}Bucket-SP", [0, 1320]),     # target bucket: start of RF buckets
])
DEFAULT_CORR_STEP = 100                    # correlation bin width (bucket units)

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
    """Return (start_dt, end_dt, pv_configs, corr_step) from the argument list."""
    p = argparse.ArgumentParser(
        description="Retrieve archived PV history with arget and plot "
                    "correlations.")
    p.add_argument("-s", "--start",
                   help="window start: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]' "
                        "(default: yesterday 00:00:00)")
    p.add_argument("-e", "--end",
                   help="window end, same formats (default: start + 1 day)")
    p.add_argument("--pv-configs", dest="pv_configs",
                   help='JSON dict mapping each PV name to its valid '
                        '[min, max] range, e.g. '
                        '\'{"pv1": [10, 100], "pv2": [0, 1320]}\'. '
                        '1st PV = Y (efficiency), 2nd PV = X (bucket). '
                        '(default: built-in DEFAULT_PV_CONFIGS)')
    p.add_argument("--corr-step", dest="corr_step", type=float,
                   default=DEFAULT_CORR_STEP,
                   help="correlation bin width in X-PV units "
                        "(default: %d)" % DEFAULT_CORR_STEP)
    args = p.parse_args(argv)

    if args.start:
        start_dt = parse_datetime(args.start)
    else:
        yesterday = datetime.now() - timedelta(days=1)
        start_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)

    end_dt = parse_datetime(args.end) if args.end else start_dt + timedelta(days=1)

    if end_dt <= start_dt:
        p.error("end (%s) must be after start (%s)" % (end_dt, start_dt))

    if args.pv_configs:
        try:
            pv_configs = json.loads(args.pv_configs,
                                    object_pairs_hook=OrderedDict)
        except ValueError as exc:
            p.error("--pv-configs is not valid JSON: %s" % exc)
        if not isinstance(pv_configs, dict) or not pv_configs:
            p.error("--pv-configs must be a non-empty JSON object")
        for pv, rng in pv_configs.items():
            if (not isinstance(rng, (list, tuple)) or len(rng) != 2
                    or rng[0] > rng[1]):
                p.error("range for %r must be [min, max] with min <= max" % pv)
    else:
        pv_configs = OrderedDict(DEFAULT_PV_CONFIGS)

    if args.corr_step <= 0:
        p.error("--corr-step must be positive")

    return start_dt, end_dt, pv_configs, args.corr_step


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


def value_at(sig_t, sig_v, query_t):
    """Zero-order-hold: last known value of (sig_t, sig_v) at each query_t."""
    if len(sig_t) == 0:
        return np.full(len(query_t), np.nan)
    idx = np.searchsorted(sig_t, query_t, side="right") - 1
    idx = np.clip(idx, 0, len(sig_v) - 1)
    return sig_v[idx]


def correlate_xy(y_t, y_v, x_t, x_v, step):
    """Average Y binned by X (rounded to nearest `step`).

    Returns (centers, mean_y, std_y, counts).
    Each Y sample is paired with the X-signal value active at that instant
    (zero-order hold), then grouped into bins of width `step`.
    """
    x_at_y = value_at(x_t, x_v, y_t)
    groups = np.round(x_at_y / float(step)) * step
    centers = np.unique(groups[~np.isnan(groups)])
    mean_y, std_y, counts = [], [], []
    for g in centers:
        sel = groups == g
        mean_y.append(y_v[sel].mean())
        std_y.append(y_v[sel].std())
        counts.append(int(np.sum(sel)))
    return centers, np.array(mean_y), np.array(std_y), np.array(counts)


def plot_all(pvs, series, start_dt, end_dt, outpng, corr_step):
    n = len(pvs)

    # Add a correlation panel (avg Y vs X) when both the Y signal (PV #1) and
    # the X signal (PV #2) carry data.
    can_corr = (n >= 2 and len(series[pvs[0]][0]) and len(series[pvs[1]][0]))
    nrows = n + (1 if can_corr else 0)

    fig, axes = plt.subplots(nrows, 1, figsize=(15, max(2.4 * nrows, 3)),
                             squeeze=False)
    axes = axes[:, 0]
    colors = plt.get_cmap("tab10").colors

    # share the time (x) axis across the first n time-history panels only
    for ax in axes[1:n]:
        axes[0].get_shared_x_axes().join(axes[0], ax)
    for ax in axes[:n - 1]:
        plt.setp(ax.get_xticklabels(), visible=False)

    fig.suptitle("PV history   %s  ->  %s  (UTC)"
                 % (start_dt.strftime("%Y-%m-%d %H:%M"),
                    end_dt.strftime("%Y-%m-%d %H:%M")),
                 fontsize=13, fontweight="bold")

    for i, pv in enumerate(pvs):
        ax = axes[i]
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

    axes[n - 1].set_xlabel("UTC time")
    axes[n - 1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    plt.setp(axes[n - 1].get_xticklabels(), rotation=30, ha="right")

    # ----- correlation panel: avg Y (PV #1) vs X (PV #2) -----
    if can_corr:
        cax = axes[n]
        y_pv, x_pv = pvs[0], pvs[1]
        y_t, y_v = series[y_pv]
        x_t, x_v = series[x_pv]
        centers, mean_y, std_y, counts = correlate_xy(
            y_t, y_v, x_t, x_v, step=corr_step)
        cax.errorbar(centers, mean_y, yerr=std_y, fmt="o-",
                     color="tab:red", ecolor="gray", elinewidth=0.8,
                     capsize=3, ms=5, lw=1.2)
        cax.set_xlabel("%s  (binned, step=%g)" % (x_pv, corr_step))
        cax.set_ylabel("Avg of\n%s" % y_pv, fontsize=8)
        cax.set_xticks(centers)
        cax.set_xticklabels([("%g" % c) for c in centers], fontsize=7,
                            rotation=45, ha="right")
        cax.grid(alpha=0.3)
        cax.set_title("Correlation: mean +/- std of  %s  vs  %s  "
                      "(per %g-wide bin)" % (y_pv, x_pv, corr_step), fontsize=9)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(outpng, dpi=130)
    print("Saved plot: %s" % outpng)


# ------------------------------------------------------------- main
def main():
    start_dt, end_dt, pv_configs, corr_step = parse_args(sys.argv[1:])
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    outdir = start_dt.strftime("%Y-%m-%d_%H%M%S") if start_dt.hour or start_dt.minute \
        else start_dt.strftime("%Y-%m-%d")
    os.makedirs(outdir, exist_ok=True)

    pvs = list(pv_configs.keys())
    print("Window    : %s  ->  %s  (UTC)" % (start_str, end_str))
    print("Output    : %s/" % outdir)
    print("PVs       : %d" % len(pvs))
    print("Corr step : %g" % corr_step)

    series = {}
    for pv in pvs:
        lo, hi = pv_configs[pv]
        outfile = os.path.join(outdir, safe_name(pv) + ".txt")
        print("  fetching %-45s -> %s" % (pv, outfile))
        fetch(pv, start_str, end_str, outfile)
        t, v = load(outfile)
        # Range filter: keep only samples within the PV's [min, max] range;
        # anything outside is treated as a glitch and dropped.
        if len(v):
            good = (v >= lo) & (v <= hi)
            n_bad = int(np.sum(~good))
            if n_bad:
                print("           dropped %d samples outside [%g, %g]"
                      % (n_bad, lo, hi))
            t, v = t[good], v[good]
        series[pv] = (t, v)
        print("           %d samples" % len(t))

    outpng = os.path.join(outdir, "history_plot.png")
    plot_all(pvs, series, start_dt, end_dt, outpng, corr_step)


if __name__ == "__main__":
    main()
