#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import pickle
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import tempfile

# Adapted from pyDAmonitor PR #66 (7e3cc736).


def compute_bins(data):
    """
    Compute histogram bins based on data spread.
    """

    data = np.asarray(data)

    if len(data) == 0:
        return np.arange(-1, 1.1, 0.1)

    std = np.std(data)

    if std == 0 or not np.isfinite(std):
        return np.linspace(
            np.min(data) - 1,
            np.max(data) + 1,
            20
        )

    xmin = -4.0 * std
    xmax = 4.0 * std

    binsize = (np.max(data) - np.min(data)) / np.sqrt(len(data))

    if binsize <= 0 or not np.isfinite(binsize):
        binsize = std / 20.0

    return np.arange(xmin, xmax + binsize, binsize)


def plot_jo_histogram(
    sensor,
    CDATE,
    jo_diffs,
    obserr,
    count_total,
    count_assim,
    count_large,
    count_zero,
    output_dir="./figures"
):
    """
    Plot Jo-diff histogram for one sensor.
    """

    os.makedirs(output_dir, exist_ok=True)

    jo_diffs = np.asarray(jo_diffs)
    obserr = np.asarray(obserr)

    if len(jo_diffs) == 0:
        print(f"[WARN] No Jo-diff values for {sensor}")
        return

    bins = compute_bins(jo_diffs)

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.hist(
        jo_diffs,
        bins=bins,
        edgecolor="black"
    )

    ax.set_xlabel("Jo Diff")
    ax.set_ylabel("Count")
    ax.set_title(
        f"{sensor} {CDATE}",
        fontsize=14
    )

    ax.grid(True)

    # ------------------------------------------
    # Statistics
    # ------------------------------------------
    mean_jo = np.mean(jo_diffs)
    sum_jo = np.sum(jo_diffs)
    max_abs_jo = np.max(np.abs(jo_diffs))

    valid_obserr = (
        np.isfinite(obserr) &
        (obserr > 0)
    )

    obserr_valid = obserr[valid_obserr]

    text = (
        f"Total Obs Count = {count_total}\n"
        f"Assim Obs Count = {count_assim}\n"
        f"Mean Jo-diff = {mean_jo:.4f}\n"
        f"Sum Jo-diff = {sum_jo:.4f}\n"
        f"Max Abs Jo-diff = {max_abs_jo:.4f}\n"
        f"|Jo-diff| > 25 = {count_large}\n"
        f"Jo-diff = 0 = {count_zero}\n"
        f"Mean ObsErr = {np.mean(obserr_valid):.4f}\n"
        f"STD ObsErr = {np.std(obserr_valid):.4f}"
    )

    ax.text(
        0.66,
        0.95,
        text,
        transform=ax.transAxes,
        verticalalignment="top",
        fontsize=11
    )

    output_file = os.path.join(
        output_dir,
        f"{sensor}-{CDATE}.png"
    )

    plt.savefig(
        output_file,
        dpi=200,
        bbox_inches="tight"
    )

    plt.close()

    print(f"[SAVE] Figure: {output_file}")


def save_legacy_pickle(
    sensor_types,
    final_total_size,
    final_assim_size,
    final_mean_jo_diff,
    final_sum_jo_diff,
    final_max_abs_jo_diff,
    CDATE,
    label="sate",
    output_dir="./pickle",
    departure_stats=None
):
    """
    Save summary statistics using the legacy data-impact
    pickle structure.
    """

    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(
        output_dir,
        f"{CDATE}_{label}.pkl"
    )

    output = [
        sensor_types,
        final_total_size,
        final_assim_size,
        final_mean_jo_diff,
        final_sum_jo_diff,
        final_max_abs_jo_diff
    ]

    if departure_stats is not None:
        output.append({'schema_version': 3, 'departure_stats': departure_stats,
                       'selection': 'impact-valid observations'})
    with open(output_file, "wb") as f:
        pickle.dump(
            output,
            f,
            protocol=pickle.HIGHEST_PROTOCOL
        )

    print(f"[SAVE] Summary pickle: {output_file}")


def save_hourly_text(sensor_types, impacts, counts, output_file):
    """Atomically save type, summed Jo difference, and valid observation count.

    NaN impact means the diagnostic was missing or could not be interpreted.
    A successfully read diagnostic with no valid observations has impact 0/count 0.
    The _conv suffix prevents collision with a future satellite processor.
    """
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if not (len(sensor_types) == len(impacts) == len(counts)):
        raise ValueError("Summary arrays must have the same length")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=output_file.parent,
                                         prefix=output_file.name + ".", delete=False) as f:
            temporary = f.name
            f.write("# data_type total_impact data_count\n")
            for sensor, impact, count in zip(sensor_types, impacts, counts):
                f.write(f"{sensor} {impact:.16g} {int(count)}\n")
        os.replace(temporary, output_file)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)



def split_data_types(value):
    """Group a checkDA observation string; deduplicate tokens to avoid double counting."""
    import re
    if not isinstance(value, str) or not value.strip():
        raise ValueError("experiment.data_types must be a nonempty checkDA string")
    groups = {"conv": [], "conv_uv": [], "sate": []}
    seen = set()
    for name in re.split(r"[,\s]+", value.strip()):
        if not name:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"Invalid observation type: {name}")
        if name in seen:
            continue
        seen.add(name)
        if re.fullmatch(r"uv\d+", name) or re.search(r"_uv\d+$", name):
            group = "conv_uv"
        elif re.fullmatch(r"(?:t|q|ps)\d+", name) or re.search(r"_(?:t|q|ps)\d+$", name):
            group = "conv"
        else:
            group = "sate"
        groups[group].append(name)
    return groups


def resolve_diagnostic_types(data_types, input_dir):
    """Resolve short checkDA types using exact suffixes, never substring matches.

    t183 selects jdiag_*_t183.nc; atms_n20 selects jdiag_atms_n20.nc.
    Return full observer names for separate statistics and output rows.
    A missing token is retained as a NaN row by the conventional processor.
    """
    import re
    folder = Path(input_dir)
    resolved = []
    seen = set()
    for token in data_types:
        if re.fullmatch(r"(?:t|q|ps|uv)\d+", token):
            matches = sorted(folder.glob(f"jdiag_*_{token}.nc"))
        else:
            candidate = folder / f"jdiag_{token}.nc"
            matches = [candidate] if candidate.is_file() else []
        matches = [p for p in matches if p.is_file()]
        if not matches:
            print(f"[WARN] No diagnostic match for {token} in {folder.resolve()}", flush=True)
            names = [token]
        else:
            names = [p.name[len('jdiag_'):-len('.nc')] for p in matches]
            print(f"[MATCH] {token}: {', '.join(p.name for p in matches)}", flush=True)
        for name in names:
            if name not in seen:
                resolved.append(name)
                seen.add(name)
    return resolved


def analyze_jedi_group(cycle, data_types, input_dir, output_dir, group,
                       figures_dir=None, pickle_dir=None, plots=False,
                       pickle_output=False):
    """Process satellite radiances or independent scalar wind components.

    Same Jo-diff convention as PR #66: (OMA**2 - OMB**2) / error**2.
    U and V each count as one scalar observation; a location can contribute
    either, both or neither depending on the component QC and valid values.
    Missing files produce NaN impact/count 0; malformed files fail the job.
    """
    import netCDF4 as nc
    if group not in ('sate', 'conv_uv'):
        raise ValueError(f'Unsupported processor group: {group}')
    groups = split_data_types(data_types)
    if any(values for key, values in groups.items() if key != group):
        raise ValueError(f'This processor accepts only {group} data types')
    if not groups[group]:
        raise ValueError(f'No {group} types selected')
    sensors = resolve_diagnostic_types(groups[group], input_dir)
    repo = Path(__file__).resolve().parents[1]
    figure_path = Path(figures_dir) if figures_dir else repo / 'figures'
    pickle_path = Path(pickle_dir) if pickle_dir else repo / 'pickle'
    totals = np.zeros(len(sensors), dtype=np.int64)
    counts = np.zeros(len(sensors), dtype=np.int64)
    means = np.full(len(sensors), np.nan)
    impacts = np.full(len(sensors), np.nan)
    maxima = np.full(len(sensors), np.nan)
    departure_stats = {}
    required = ('ombg', 'oman', 'EffectiveError1', 'EffectiveQC1')
    for index, sensor in enumerate(sensors):
        filename = Path(input_dir) / f'jdiag_{sensor}.nc'
        if not filename.is_file():
            print(f'[WARN] Cycle {cycle}: missing {filename}', flush=True)
            continue
        print(f'[READ] Cycle {cycle}: {filename}', flush=True)
        with nc.Dataset(filename) as dataset:
            missing = [name for name in required if name not in dataset.groups]
            if missing:
                raise ValueError(f'{filename}: missing groups {missing}')
            common = set.intersection(*(set(dataset.groups[g].variables) for g in required))
            if group == 'sate':
                if 'brightnessTemperature' not in common:
                    raise ValueError(f'{filename}: brightnessTemperature absent from required groups')
                variables = ['brightnessTemperature']
            else:
                # JEDI/ IODA files use either naming convention, depending on version.
                pairs = [('windEastward', 'windNorthward'),
                         ('eastwardWind', 'northwardWind')]
                available = [pair for pair in pairs if set(pair) <= common]
                if len(available) != 1:
                    raise ValueError(f'{filename}: expected one U/V pair across {required}; '
                                     f'found common variables {sorted(common)}')
                variables = list(available[0])
            values, errors, ombs, omas = [], [], [], []
            for variable in variables:
                arrays = []
                for group_name in required:
                    raw = dataset.groups[group_name].variables[variable][:]
                    arrays.append(np.ma.asarray(raw, dtype=np.float64).filled(np.nan))
                omb, oma, error, qc = arrays
                if len({array.shape for array in arrays}) != 1:
                    raise ValueError(f'{filename}: {variable} has inconsistent shapes '
                                     f'{[a.shape for a in arrays]}')
                valid = ((qc == 0) & np.isfinite(omb) & np.isfinite(oma)
                         & np.isfinite(error) & (error > 0))
                with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                    diff = (oma[valid] ** 2 - omb[valid] ** 2) / error[valid] ** 2
                if not np.all(np.isfinite(diff)):
                    raise ValueError(f'{filename}: {variable} produced non-finite Jo differences')
                totals[index] += omb.size
                ombs.append(omb[valid].ravel())
                omas.append(oma[valid].ravel())
                values.append(diff.ravel())
                errors.append(error[valid].ravel())
                print(f'[STATS] {sensor}/{variable}: total={omb.size} '
                      f'accepted={diff.size} impact={np.sum(diff):.10g}', flush=True)
            departure_stats[sensor] = departure_statistics(np.concatenate(ombs), np.concatenate(omas))
            print_departure_statistics(sensor, departure_stats[sensor])
            diff = np.concatenate(values)
            error = np.concatenate(errors)
            counts[index] = diff.size
            impacts[index] = np.sum(diff)
            if not np.isfinite(impacts[index]):
                raise ValueError(f'{filename}: summed impact is non-finite')
            if diff.size:
                means[index] = np.mean(diff)
                maxima[index] = np.max(np.abs(diff))
                if plots:
                    plot_jo_histogram(sensor, cycle, diff, error, int(totals[index]),
                                      int(counts[index]), int(np.sum(np.abs(diff) > 25)),
                                      int(np.sum(diff == 0)), output_dir=str(figure_path))
            print(f'[SUMMARY] {sensor}: count={counts[index]} '
                  f'impact={impacts[index]:.10g}', flush=True)
    destination = pickle_path / f'{cycle}_{group}.pkl'
    save_legacy_pickle(sensors, totals, counts, means, impacts, maxima,
                       cycle, label=group, output_dir=str(pickle_path), departure_stats=departure_stats)
    print("\n====================================================", flush=True)
    print(f"Final Summary ({group}) - {cycle}", flush=True)
    print("====================================================", flush=True)
    for index, sensor in enumerate(sensors):
        print(
            f"{sensor:20s} "
            f"total={totals[index]:10d} "
            f"assim={counts[index]:10d} "
            f"mean={means[index]:12.5f} "
            f"sum={impacts[index]:12.5f} "
            f"maxabs={maxima[index]:12.5f}",
            flush=True,
        )
    return destination


def run_group_cli(group):
    """CLI shared by the satellite and wind entry points."""
    import argparse
    from datetime import datetime
    parser = argparse.ArgumentParser(description=(
        f'JEDI {group} observation impact; count is accepted scalar components '
        '(wind) or location/channel elements (satellite).'))
    parser.add_argument('cycle', help='UTC YYYYMMDDHH')
    parser.add_argument('--data-types', required=True, help='Comma-separated checkDA types')
    parser.add_argument('--input-dir', default='.', help='Directory containing jdiag_*.nc')
    parser.add_argument('--output-dir', default='.', help='Text output directory')
    parser.add_argument('--figures-dir', help='Independent figure directory')
    parser.add_argument('--pickle-dir', help='Independent summary pickle directory')
    parser.add_argument('--plots', action='store_true')
    parser.add_argument('--pickle', action='store_true')
    args = parser.parse_args()
    try:
        if len(args.cycle) != 10 or not args.cycle.isdigit():
            raise ValueError('cycle must be YYYYMMDDHH')
        datetime.strptime(args.cycle, '%Y%m%d%H')
        folder = Path(args.input_dir)
        if not folder.is_dir():
            raise ValueError(f'Cycle {args.cycle}: input directory does not exist: {folder.resolve()}')
        if not any(folder.glob('jdiag_*.nc')):
            raise ValueError(f'Cycle {args.cycle}: no jdiag_*.nc directly in {folder.resolve()}')
        analyze_jedi_group(args.cycle, args.data_types, folder, args.output_dir, group,
                           args.figures_dir, args.pickle_dir, args.plots, args.pickle)
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')


DEPARTURE_FIELDS = ('omb_min', 'omb_mean', 'omb_max',
                    'oma_min', 'oma_mean', 'oma_max')


def departure_statistics(omb, oma):
    """Raw min/mean/max for the exact impact-valid subset."""
    result = {}
    for prefix, values in [('omb', omb), ('oma', oma)]:
        values = np.asarray(values, dtype=np.float64).ravel()
        if values.size and not np.isfinite(values).all():
            raise ValueError('Departure statistics require finite input')
        stats = (np.min(values), np.mean(values), np.max(values)) if values.size else (np.nan,) * 3
        for name, value in zip(('min', 'mean', 'max'), stats):
            result[f'{prefix}_{name}'] = float(value)
    return result


def print_departure_statistics(sensor, stats):
    print(f'[OMB/OMA] {sensor}: ' + ' '.join(f'{key}={stats[key]:.6f}'
          for key in DEPARTURE_FIELDS), flush=True)
