#!/usr/bin/env bash
# Build the React frontend (run once, or after frontend changes)
set -e
cd "$(dirname "$0")/frontend"
npm install
npm run build
echo "Frontend built to frontend/dist/"
