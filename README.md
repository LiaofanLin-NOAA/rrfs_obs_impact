# RRFS Observation Impact Monitor

View hourly RRFS observation impact and OMB/OMA time series on the [live monitor](https://liaofanlin-noaa.github.io/rrfs_obs_impact/).

## Configuration

In `config.yaml`, set the experiment name, observation types, and path to the JEDI diagnostics. Choose one mode:

| Mode | Time settings (UTC) |
| --- | --- |
| `mode: realtime` | Set `realtime.lookback_hours` for the number of hourly cycles and `realtime.lag_hours` for the delay from the current UTC hour to the end of the window. |
| `mode: retro` | Set `retro.start_time` and `retro.end_time` as quoted `YYYYMMDDHH` values. Both hours are included. |

## Run on Gaea C6

From the repository root:

```bash
MACHINE=gaeac6 bash run.sh config.yaml
```


