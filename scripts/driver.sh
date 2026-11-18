#!/usr/bin/env bash
# Process one UTC cycle at a time.
# Usage: bash scripts/driver.sh [config.yaml] [--dry-run] [--publish]
# YAML parsing requires PyYAML in DRIVER_PYTHON (or PYTHON_BIN / python3).
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
exec "${DRIVER_PYTHON:-${PYTHON_BIN:-python3}}" - "$REPO_ROOT" "$@" <<'PY'
import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone

try:
    import yaml
except ImportError:
    sys.exit('ERROR: PyYAML is required; set DRIVER_PYTHON to your pyDAmonitor Python.')

root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
from obs_impact_functions import split_data_types
parser = argparse.ArgumentParser(description='Process observation impact one UTC cycle at a time.')
parser.add_argument('config', nargs='?', default=str(root / 'config.yaml'))
parser.add_argument('--dry-run', action='store_true')
parser.add_argument('--publish', action='store_true', help='Commit new cycle summaries and push main to origin')
args = parser.parse_args(sys.argv[2:])

def positive_int(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value

def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{10}', value):
        raise ValueError('Retro times must be quoted YYYYMMDDHH strings')
    return datetime.strptime(value, '%Y%m%d%H').replace(tzinfo=timezone.utc)

def path(value):
    p = Path(value).expanduser()
    return p if p.is_absolute() else root / p

def git(*args, capture=False):
    result = subprocess.run(
        ['git', *args], cwd=root, check=True, text=True,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
        stdout=subprocess.PIPE if capture else None)
    return result.stdout

def publish_summaries(text_dir, name):
    relative_dir = text_dir.relative_to(root)
    tracked = set(git('ls-tree', '-r', '--name-only', '-z', 'HEAD', '--',
                      str(relative_dir), capture=True).split('\0'))
    new_files = sorted(
        str(file.relative_to(root)) for file in text_dir.glob('*.txt')
        if re.fullmatch(r'[0-9]{10}\.txt', file.name)
        and file.is_file() and file.stat().st_size > 0
        and str(file.relative_to(root)) not in tracked
    )
    if new_files:
        git('add', '--', *new_files)
        git('commit', '--only', '-m', f'Update observation impact summaries for {name}', '--', *new_files)
    # A prior push may have failed after the summaries were committed.
    git('push', 'origin', 'HEAD:refs/heads/main')


try:
    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError('Configuration must be a YAML mapping')
    mode = cfg['mode']
    if mode == 'realtime':
        rt = cfg['realtime']
        hours = positive_int(rt['lookback_hours'], 'lookback_hours')
        lag = positive_int(rt.get('lag_hours', 0), 'lag_hours', 0)
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=lag)
        start = end - timedelta(hours=hours - 1)
    elif mode == 'retro':
        start = timestamp(cfg['retro']['start_time'])
        end = timestamp(cfg['retro']['end_time'])
    else:
        raise ValueError('mode must be realtime or retro')
    if start > end:
        raise ValueError('start_time must not be later than end_time')
    exp, proc = cfg['experiment'], cfg['processing']
    name = str(exp['name'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('experiment.name may contain only letters, digits, underscores and hyphens')
    if type(proc.get('skip_missing_cycle_directory', True)) is not bool:
        raise ValueError('skip_missing_cycle_directory must be true or false')
    groups = split_data_types(exp['data_types'])
    processor_map = proc['processors']
    if not isinstance(processor_map, dict):
        raise ValueError('processing.processors must map conv, conv_uv, sate to script paths or null')
    scripts = []
    for group, selected in groups.items():
        print(f"{group}: {','.join(selected) or '(none)'}", flush=True)
        script_name = processor_map.get(group)
        if not selected:
            continue
        if not script_name:
            print(f"DISABLED {group}: {len(selected)} types selected, but no processor configured", flush=True)
            continue
        script = path(script_name).resolve()
        if not script.is_file():
            raise ValueError(f'Missing {group} processor: {script}')
        scripts.append((group, script))
    if not scripts:
        raise ValueError('No enabled processors with selected data types')
    work = root.resolve()
    text_dir = (path(proc.get('text_root', 'data')) / name).resolve()
    figures_dir = (path(proc.get('figures_root', 'figures')) / name).resolve()
    pickle_dir = (path(proc.get('pickle_root', 'pickle')) / name).resolve()
    for key in ('save_figures', 'save_pickle'):
        if type(proc.get(key, False)) is not bool:
            raise ValueError(f'{key} must be true or false')
    for other in (figures_dir, pickle_dir):
        if other == text_dir or text_dir in other.parents:
            raise ValueError('Figure/pickle directories must be outside the text directory')
    if str(exp.get('domain', 'True')) != 'True':
        raise ValueError('Subdomain filtering is not supported by obs_impact_conv.py yet')
    if args.publish:
        if root / 'data' not in text_dir.parents:
            raise ValueError('--publish requires the summary directory to be under repo/data')
        if not args.dry_run and git('branch', '--show-current', capture=True).strip() != 'main':
            raise ValueError('--publish requires the local main branch')
    print(f'Mode: {mode}; UTC cycles: {start:%Y%m%d%H} through {end:%Y%m%d%H}', flush=True)
    if not args.dry_run:
        text_dir.mkdir(parents=True, exist_ok=True)
    processed = skipped = failed = 0
    cycle = start
    while cycle <= end:
        stamp = cycle.strftime('%Y%m%d%H')
        summary = text_dir / f'{stamp}.txt'
        if summary.is_file() and summary.stat().st_size > 0:
            print(f'SKIP {stamp}: summary already exists at {summary}', flush=True)
            skipped += 1
            cycle += timedelta(hours=1)
            continue
        data = exp['cycle_path_pattern'].format(
            data_path=str(path(exp['data_path'])), cycle=stamp,
            ymd=stamp[:8], year=stamp[:4], month=stamp[4:6], day=stamp[6:8], hour=stamp[8:10])
        if (not args.dry_run and proc.get('skip_missing_cycle_directory', True)
                and not Path(data).is_dir()):
            print(f'SKIP {stamp}: missing directory {data}', flush=True)
            skipped += 1
            cycle += timedelta(hours=1)
            continue
        if not args.dry_run and not any(Path(data).glob('jdiag_*.nc')):
            print(f'SKIP {stamp}: no diagnostic files in {data}', flush=True)
            skipped += 1
            cycle += timedelta(hours=1)
            continue
        commands = []
        print(f"Cycle {stamp}: input={data}", flush=True)
        for group, script in scripts:
            processor_cmd = [sys.executable, str(script), stamp,
                             '--data-types', ','.join(groups[group]),
                             '--input-dir', data, '--output-dir', str(text_dir),
                             '--figures-dir', str(figures_dir), '--pickle-dir', str(pickle_dir)]
            if proc.get('save_figures', False):
                processor_cmd.append('--plots')
            processor_cmd.append('--pickle')  # Required summary intermediate
            commands.append(processor_cmd)
        commands.append([
            sys.executable, str(root / 'scripts' / 'obs_impact_summary.py'), stamp,
            '--pickle-dir', str(pickle_dir), '--output-dir', str(text_dir),
            '--groups', ','.join(group for group, _ in scripts)])
        try:
            for command in commands:
                if args.dry_run:
                    print(shlex.join(command), flush=True)
                else:
                    subprocess.run(command, cwd=work, check=True)
        except subprocess.CalledProcessError as exc:
            print(f'ERROR: cycle {stamp}: {Path(exc.cmd[1]).name} exited with status {exc.returncode}',
                  file=sys.stderr, flush=True)
            failed += 1
        else:
            if not args.dry_run:
                print(f'PROCESSED {stamp}', flush=True)
            processed += 1
        cycle += timedelta(hours=1)
    print(f'{"Planned" if args.dry_run else "Processed"}: {processed}; skipped: {skipped}; failed: {failed}',
          flush=True)
    if args.publish and not args.dry_run:
        publish_summaries(text_dir, name)
    if failed:
        sys.exit(1)
except subprocess.CalledProcessError as exc:
    sys.exit(f'ERROR: Git {exc.cmd[1]} exited with status {exc.returncode}')
except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError) as exc:
    sys.exit(f'ERROR: {exc}')
PY
