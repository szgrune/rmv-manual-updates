#!/usr/bin/env bash
set -euo pipefail

echo "=== Driver's Manual Updates — Full Build ==="
echo ""

# ── Dependencies ──────────────────────────────────────────────────────────────
echo "[1/4] Installing dependencies..."
pip install -q -r scripts/requirements.txt

BACKEND="${ANALYZER_BACKEND:-claude}"
if [ "$BACKEND" = "claude" ]; then
  pip install -q -r scripts/requirements-claude.txt
elif [ "$BACKEND" = "openai" ]; then
  pip install -q -r scripts/requirements-openai.txt
elif [ "$BACKEND" = "local" ]; then
  pip install -q -r scripts/requirements-local.txt
else
  echo "ERROR: Unknown ANALYZER_BACKEND: $BACKEND"
  exit 1
fi

# ── Extract PDFs ──────────────────────────────────────────────────────────────
echo ""
echo "[2/4] Extracting PDFs..."
python3 scripts/extract_pdfs.py

# ── Analyze changes ───────────────────────────────────────────────────────────
echo ""
echo "[3/4] Analyzing changes (backend: $BACKEND)..."
if [ "$BACKEND" = "claude" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set."
  echo "Set it before running: ANTHROPIC_API_KEY=sk-... ./build.sh"
  exit 1
fi
if [ "$BACKEND" = "openai" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is not set."
  exit 1
fi
python3 scripts/analyze_changes.py

# ── Export JSON ───────────────────────────────────────────────────────────────
echo ""
echo "[4/4] Exporting JSON files..."
python3 scripts/export_json.py

echo ""
echo "=== Build complete! ==="
echo ""
echo "To view the app:"
echo "  cd web && python3 -m http.server 8080"
echo "  Then open http://localhost:8080 in your browser."
echo ""
echo "To add a new manual year:"
echo "  python3 scripts/update_manual.py Manuals/Drivers_Manual_2028.pdf"
