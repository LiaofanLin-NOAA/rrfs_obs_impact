#!/usr/bin/env bash


set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

MACHINE="${MACHINE:-local}"
BASEDIR=""
case "${MACHINE}" in
  hera)
    BASEDIR=/scratch3/BMC/wrfruc/hera/Miniforge3
    ;;
  ursa)
    BASEDIR=/scratch3/BMC/wrfruc/gge/Miniforge3
    ;;
  derecho)
    BASEDIR=/glade/work/geguo/Miniforge3
    ;;
  orion)
    BASEDIR=/work/noaa/zrtrr/gge/Miniforge3
    ;;
  hercules)
    BASEDIR=/work/noaa/zrtrr/gge/hercules/Miniforge3
    ;;
  gaeac?)
    if [[ -d /gpfs/f6 ]]; then
      BASEDIR=/gpfs/f6/bil-fire10-oar/world-shared/gge/Miniforge3
    elif [[ -d /gpfs/f7 ]]; then
      BASEDIR=/gpfs/f7/wrfruc/world-shared/gge/Miniforge3
    else
      echo "ERROR: unsupported gaea cluster: ${MACHINE}" >&2
      exit 1
    fi
    ;;
  local)
    ;;
  *)
    echo "ERROR: unsupported MACHINE=${MACHINE}" >&2
    exit 1
    ;;
esac

if [[ -n "${PYDAMONITOR_PYTHON:-}" ]]; then
  PYTHON_BIN="${PYDAMONITOR_PYTHON}"
elif [[ -n "${BASEDIR}" && -x "${BASEDIR}/envs/pyDAmonitor/bin/python3" ]]; then
  PYTHON_BIN="${BASEDIR}/envs/pyDAmonitor/bin/python3"
elif [[ "${MACHINE}" == local ]]; then
  PYTHON_BIN=python3
else
  echo "ERROR: pyDAmonitor python3 not found at ${BASEDIR}/envs/pyDAmonitor/bin/python3 (MACHINE=${MACHINE})" >&2
  exit 1
fi

export MACHINE
export DRIVER_PYTHON="${PYTHON_BIN}"
exec bash "${SCRIPT_DIR}/scripts/driver.sh" "$@"
