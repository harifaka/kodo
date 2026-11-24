#!/bin/sh
# Link the pre-warmed dependency cache into the staged workspace when the project has no
# node_modules of its own. The workspace here is a disposable snapshot, never the user's files.
set -eu

if [ ! -e /workspace/node_modules ] && [ -d /opt/kodo-node-cache/node_modules ]; then
    ln -s /opt/kodo-node-cache/node_modules /workspace/node_modules
fi

exec "$@"
