#!/usr/bin/env bash
# Build report/report.pdf from report/report.md: pandoc (Markdown -> HTML) + headless Chrome (HTML -> PDF).
#   CHROME=google-chrome STUDENT_NAME="..." ROLL_NUMBER="..." report/build.sh
# STUDENT_NAME / ROLL_NUMBER replace NAME_PLACEHOLDER / ROLL_PLACEHOLDER in the title block.
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-google-chrome}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp/report.md" <<'EOF'
import os, sys
s = open("report.md", encoding="utf-8").read()
s = s.replace("NAME_PLACEHOLDER", os.environ.get("STUDENT_NAME") or "NAME_PLACEHOLDER")
s = s.replace("ROLL_PLACEHOLDER", os.environ.get("ROLL_NUMBER") or "ROLL_PLACEHOLDER")
open(sys.argv[1], "w", encoding="utf-8").write(s)
EOF
cp style.css "$tmp/"
pandoc "$tmp/report.md" -f markdown+pipe_tables+yaml_metadata_block+smart -t html5 -s \
  --css "$tmp/style.css" --embed-resources --standalone -o "$tmp/report.html"
"$CHROME" --headless=new --no-sandbox --disable-gpu --no-pdf-header-footer --print-to-pdf-no-header \
  --print-to-pdf="$PWD/report.pdf" "file://$tmp/report.html" 2>/dev/null
pdfinfo report.pdf | grep -E "Pages|Page size"
