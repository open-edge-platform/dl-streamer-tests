#!/bin/bash
set -e

arguments=$@

SCRIPTDIR="$(dirname "$(readlink -fm "$0")")"

if [[ -z "$MODEL_PROCS_PATH" ]]; then
    echo "ERROR: MODEL_PROCS_PATH environment variable is not set"
    exit -1
fi

if [[ -z "$LABELS_PATH" ]]; then
    echo "WARNING: LABELS_PATH environment variable is not set"
fi

if command -v uv >/dev/null 2>&1; then
    VENV_DIR="/tmp/dlstreamer-pipeline-test-venv"
    uv venv --allow-existing --system-site-packages "$VENV_DIR"
    uv pip install --python "$VENV_DIR/bin/python" -r "$SCRIPTDIR/requirements.txt"
    PYTHON_BIN="$VENV_DIR/bin/python"
else
    pip3 install -r $SCRIPTDIR/requirements.txt
    PYTHON_BIN="python3"
fi

# Some configs require working dir be set to level of regression_tests dir location
WORK_DIR="$(dirname "$(dirname "${SCRIPTDIR}" )" )"
pushd $WORK_DIR

echo "Working dir is: `pwd`"
PYTHONPATH=$SCRIPTDIR:$PYTHONPATH "$PYTHON_BIN" -u -m regression_test ${arguments}

popd
