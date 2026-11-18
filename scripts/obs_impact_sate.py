#!/usr/bin/env python3
"""RRFS JEDI observation impact for satellite radiances.

Uses the PR #66 normalized Jo-difference convention (no 1/2 factor).
Accepts checkDA --data-types and resolves matching cycle jdiag files.
See obs_impact_functions.py for shared processing and CLI implementation.
"""
from obs_impact_functions import analyze_jedi_group, run_group_cli


def analyze_sate(cycle, data_types, input_dir='.', output_dir='.',
                    figures_dir=None, pickle_dir=None, plots=False,
                    pickle_output=False):
    """Write hourly text, optionally histograms and a legacy summary pickle."""
    return analyze_jedi_group(cycle, data_types, input_dir, output_dir, 'sate',
                              figures_dir, pickle_dir, plots, pickle_output)


if __name__ == '__main__':
    run_group_cli('sate')
