#!/usr/bin/env python3
"""RRFS JEDI observation impact for conventional U/V wind components.

Uses the PR #66 normalized Jo-difference convention (no 1/2 factor).
Accepts checkDA --data-types and resolves matching cycle jdiag files.
See obs_impact_functions.py for shared processing and CLI implementation.
"""
from obs_impact_functions import analyze_jedi_group, run_group_cli


def analyze_conv_uv(cycle, data_types, input_dir='.', output_dir='.',
                    figures_dir=None, pickle_dir=None, plots=False,
                    pickle_output=False):
    """Write hourly text, optionally histograms and a legacy summary pickle."""
    return analyze_jedi_group(cycle, data_types, input_dir, output_dir, 'conv_uv',
                              figures_dir, pickle_dir, plots, pickle_output)


if __name__ == '__main__':
    run_group_cli('conv_uv')
