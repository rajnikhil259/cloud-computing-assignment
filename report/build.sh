#!/usr/bin/env bash
# Build report/report.pdf from report/report.md: pandoc (Markdown -> HTML) + headless Chrome (HTML -> PDF).
#   CHROME=google-chrome report/build.sh
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-google-chrome}"
pandoc report.md -f markdown+pipe_tables+yaml_metadata_block+smart -t html5 -s \
  --css style.css --embed-resources --standalone -o report.html
"$CHROME" --headless=new --no-sandbox --disable-gpu --no-pdf-header-footer --print-to-pdf-no-header \
  --print-to-pdf="$PWD/report.pdf" "file://$PWD/report.html" 2>/dev/null
rm -f report.html
pdfinfo report.pdf | grep -E "Pages|Page size"
