#!/usr/bin/env bash
# TF-4: configure Daytona provider in TrueForge using the user-provided key (file or inline).
# Key is stored 0600 at .daytona_key and exported to the python config script only.
set -e
KEY="${DAYTONA_KEY_INLINE:-}"
KEYFILE=/root/workspace/redrive-spike/.daytona_key
if [ -z "$KEY" ] && [ -f "$KEYFILE" ]; then KEY=$(cat "$KEYFILE"); fi
if [ -z "$KEY" ]; then echo "no key"; exit 2; fi
mkdir -p /root/workspace/redrive-spike/tf/logs
cd /root/workspace/redrive-spike/tf
DAYTONA_API_KEY="$KEY" /usr/local/lib/hermes-agent/venv/bin/python3 tf4_configure_daytona.py
