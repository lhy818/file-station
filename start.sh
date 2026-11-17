#!/bin/bash
set -e
mkdir -p files
exec updog -d files -p "${PORT:-9090}" --password "$FILE_PASSWORD"
