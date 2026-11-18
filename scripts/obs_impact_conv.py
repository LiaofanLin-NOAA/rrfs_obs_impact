#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================
Observation Impact Analysis – JEDI Conventional Observations
Adapted from pyDAmonitor PR #67 (ea9e286).
Text columns: data_type total_impact data_count.
Impact = (OMA**2 - OMB**2) / ObsError**2, without a 1/2 factor.
Negative values indicate reduced normalized observation departures.
Wind observations are not included. Missing diagnostics have NaN impact.
==============================================================
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
import numpy as np
import netCDF4 as nc

from obs_impact_functions import (
    plot_jo_histogram,
    save_legacy_pickle,
    split_data_types,
    resolve_diagnostic_types,
    departure_statistics,
    print_departure_statistics,
)


def analyze_conv(CDATE, input_dir='.', output_dir='.', plots=False, pickle_output=False,
                 figures_dir=None, pickle_dir=None, data_types=None):
    repo = Path(__file__).resolve().parents[1]
    figures_dir = Path(figures_dir) if figures_dir else repo / 'figures'
    pickle_dir = Path(pickle_dir) if pickle_dir else repo / 'pickle'

    # ------------------------------------------------------------
    # Choose conventional observation types
    # ------------------------------------------------------------
    if data_types is None:
        raise ValueError("--data-types is required; supply the conventional checkDA string")
    groups = split_data_types(data_types)
    if groups['conv_uv'] or groups['sate']:
        raise ValueError("obs_impact_conv.py accepts only non-wind conventional types")
    sensor_types = resolve_diagnostic_types(groups['conv'], input_dir)
    if not sensor_types:
        raise ValueError("No conventional types selected")

    departure_stats = {}
    n_sensor = len(sensor_types)

    final_total_size = np.zeros(n_sensor)
    final_assim_size = np.zeros(n_sensor)
    final_mean_jo_diff = np.full(n_sensor, np.nan)
    final_sum_jo_diff = np.full(n_sensor, np.nan)
    final_max_abs_jo_diff = np.full(n_sensor, np.nan)

    for ss, sensor in enumerate(sensor_types):

        print()
        print(ss)
        print(sensor)

        filename = str(Path(input_dir) / f"jdiag_{sensor}.nc")

        if not os.path.exists(filename):
            print(f"[WARN] Missing file: {filename}")
            continue

        ncd = nc.Dataset(filename, "r")

        print(f"=== Processing {sensor} ===")

        # --------------------------------------------------------
        # NetCDF global attributes
        # --------------------------------------------------------
        nc_attrs = ncd.ncattrs()

        print("NetCDF Global Attributes: ")
        print("nc_attrs = ", nc_attrs)

        for nc_attr in nc_attrs:
            print("nc_attr", ncd.getncattr(nc_attr))

        # --------------------------------------------------------
        # Determine diagnostic variable automatically
        #
        # Example for jdiag_aircar_t133.nc:
        #
        #   ombg/airTemperature
        #   oman/airTemperature
        #   EffectiveError1/airTemperature
        #   EffectiveQC1/airTemperature
        # --------------------------------------------------------
        common_variables = (
            set(ncd.groups["ombg"].variables.keys())
            & set(ncd.groups["oman"].variables.keys())
            & set(ncd.groups["EffectiveError1"].variables.keys())
            & set(ncd.groups["EffectiveQC1"].variables.keys())
        )

        common_variables = sorted(common_variables)

        if len(common_variables) == 0:
            print(
                f"[WARN] No common diagnostic variable "
                f"found for {sensor}"
            )
            ncd.close()
            continue

        if len(common_variables) > 1:
            print(
                f"[ERROR] Multiple diagnostic variables found "
                f"for {sensor}: {common_variables}"
            )
            print(
                "Please check the jdiag structure before "
                "computing data impact."
            )
            ncd.close()
            continue

        variable = common_variables[0]

        print(f"Diagnostic variable: {variable}")

        # --------------------------------------------------------
        # Read diagnostics
        # --------------------------------------------------------
        omb = (
            ncd.groups["ombg"]
            .variables[variable][:]
        )

        oma = (
            ncd.groups["oman"]
            .variables[variable][:]
        )

        obserr = (
            ncd.groups["EffectiveError1"]
            .variables[variable][:]
        )

        qc = (
            ncd.groups["EffectiveQC1"]
            .variables[variable][:]
        )

        print(f"OMB shape:    {omb.shape}")
        print(f"OMA shape:    {oma.shape}")
        print(f"ObsErr shape: {obserr.shape}")
        print(f"QC shape:     {qc.shape}")

        # --------------------------------------------------------
        # Convert masked arrays
        # --------------------------------------------------------
        omb = np.ma.filled(
            np.ma.asarray(omb, dtype=np.float64),
            np.nan
        )

        oma = np.ma.filled(
            np.ma.asarray(oma, dtype=np.float64),
            np.nan
        )

        obserr = np.ma.filled(
            np.ma.asarray(obserr, dtype=np.float64),
            np.nan
        )

        qc = np.ma.filled(
            qc,
            999
        )

        # --------------------------------------------------------
        # Select assimilated observations
        #
        # EffectiveQC == 0 means accepted/used
        # --------------------------------------------------------
        valid = (
            (qc == 0)
            & np.isfinite(omb)
            & np.isfinite(oma)
            & np.isfinite(obserr)
            & (obserr > 0)
        )

        # --------------------------------------------------------
        # Jo difference
        #
        # Jo = (O-H)^2 / sigma_o^2
        #
        # Delta Jo = Jo_analysis - Jo_background
        # --------------------------------------------------------
        jo_diff = np.full(
            omb.shape,
            np.nan
        )

        jo_diff[valid] = (
            oma[valid] ** 2 - omb[valid] ** 2
        ) / (
            obserr[valid] ** 2
        )

        if not np.all(np.isfinite(jo_diff[valid])):
            ncd.close()
            raise ValueError(f"Non-finite Jo differences in {filename}")

        departure_stats[sensor] = departure_statistics(omb[valid], oma[valid])
        print_departure_statistics(sensor, departure_stats[sensor])
        jo_diffs = jo_diff[valid]

        # --------------------------------------------------------
        # Counts
        # --------------------------------------------------------
        count_total = omb.size
        count_assim = np.sum(valid)

        count_large = np.sum(
            np.abs(jo_diffs) > 25
        )

        count_zero = np.sum(
            jo_diffs == 0
        )

        print()
        print(
            f"Total elements:           "
            f"{count_total}"
        )

        print(
            f"Assimilated elements:     "
            f"{count_assim}"
        )

        print(
            f"|Jo-diff| > 25 count:     "
            f"{count_large}"
        )

        print(
            f"Jo-diff == 0 count:       "
            f"{count_zero}"
        )

        final_total_size[ss] = count_total
        final_assim_size[ss] = count_assim
        final_sum_jo_diff[ss] = 0.0  # Read successfully, but no accepted observations

        if count_assim == 0:

            print(
                f"[WARN] No assimilated observations "
                f"for {sensor}"
            )

            ncd.close()
            continue

        # --------------------------------------------------------
        # Statistics
        # --------------------------------------------------------
        mean_jo_diff = np.mean(
            jo_diffs
        )

        sum_jo_diff = np.sum(
            jo_diffs
        )

        max_abs_jo_diff = np.max(
            np.abs(jo_diffs)
        )

        print()
        print(
            f"Mean Jo-diff:    "
            f"{mean_jo_diff}"
        )

        print(
            f"Sum Jo-diff:     "
            f"{sum_jo_diff}"
        )

        print(
            f"Max |Jo-diff|:   "
            f"{max_abs_jo_diff}"
        )

        # --------------------------------------------------------
        # Save summary arrays
        # --------------------------------------------------------
        final_total_size[ss] = count_total
        final_assim_size[ss] = count_assim
        final_mean_jo_diff[ss] = mean_jo_diff
        final_sum_jo_diff[ss] = sum_jo_diff
        final_max_abs_jo_diff[ss] = max_abs_jo_diff

        # --------------------------------------------------------
        # Plot Jo-diff histogram
        # --------------------------------------------------------
        if plots:
            plot_jo_histogram(
                sensor,
                CDATE,
                jo_diffs,
                obserr[valid],
                count_total,
                count_assim,
                count_large,
                count_zero,
                output_dir=str(figures_dir)
            )

        ncd.close()

    # ------------------------------------------------------------
    # Save summary pickle
    # ------------------------------------------------------------
    save_legacy_pickle(
        sensor_types,
        final_total_size,
        final_assim_size,
        final_mean_jo_diff,
        final_sum_jo_diff,
        final_max_abs_jo_diff,
        CDATE,
        label="conv",
        output_dir=str(pickle_dir),
        departure_stats=departure_stats
    )

    # ------------------------------------------------------------
    # Final sensor summary
    # ------------------------------------------------------------
    print()
    print("====================================================")
    print("Final Summary")
    print("====================================================")

    for ss, sensor in enumerate(sensor_types):

        print(
            f"{sensor:20s} "
            f"total={final_total_size[ss]:10.0f} "
            f"assim={final_assim_size[ss]:10.0f} "
            f"mean={final_mean_jo_diff[ss]:12.5f} "
            f"sum={final_sum_jo_diff[ss]:12.5f} "
            f"maxabs={final_max_abs_jo_diff[ss]:12.5f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycle", help="UTC cycle YYYYMMDDHH")
    parser.add_argument("--data-types", required=True, help="Comma-separated conventional checkDA types, e.g. t181,q183,ps181")
    parser.add_argument("--input-dir", default=".", help="Directory containing jdiag_TYPE.nc files")
    parser.add_argument("--output-dir", default=".", help="Hourly text output directory")
    parser.add_argument("--figures-dir", help="Figure output directory; independent of text output")
    parser.add_argument("--pickle-dir", help="Summary pickle directory; independent of text output")
    parser.add_argument("--plots", action="store_true", help="Also save histograms under figures/")
    parser.add_argument("--pickle", action="store_true", help="Also save the legacy summary pickle")
    args = parser.parse_args()
    try:
        if len(args.cycle) != 10 or not args.cycle.isdigit():
            raise ValueError("cycle must be YYYYMMDDHH")
        datetime.strptime(args.cycle, "%Y%m%d%H")
        if not Path(args.input_dir).is_dir():
            raise ValueError(f"Input directory does not exist: {args.input_dir}")
        if not any(Path(args.input_dir).glob("jdiag_*.nc")):
            raise ValueError(f"Cycle {args.cycle}: no jdiag_*.nc files directly in {Path(args.input_dir).resolve()}")
        analyze_conv(args.cycle, args.input_dir, args.output_dir, args.plots, args.pickle,
                     args.figures_dir, args.pickle_dir, args.data_types)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")

