#!/bin/bash
set -e
mkdir -p files .parts
exec waitress-serve --host=0.0.0.0 --port="${PORT:-9090}" app:app
