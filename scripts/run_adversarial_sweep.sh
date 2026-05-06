#!/usr/bin/env bash
# Adversarial false-positive sweep — Phase 4 launch decision gate.
#
# Runs the LLM scanner against every repo under SWEEP_DIR (default
# ~/clouddev/asp-demo-targets/sweep/) and reports any Tool /
# PromptTemplate / RAGIndex / MemoryStore nodes that get extracted.
#
# Per ADR-0005 / docs/launch-roadmap.md:
#   0 false positives across all repos = PASS = ship Option C as headline
#   1-3 false positives                  = tune prompts, re-run
#   4+ persistent false positives        = ADR-0005 fallback (preview)
#
# Usage:
#   ANTHROPIC_API_KEY=sk-ant-... ./scripts/run_adversarial_sweep.sh
#   ANTHROPIC_API_KEY=sk-ant-... SWEEP_DIR=/path/to/repos ./scripts/run_adversarial_sweep.sh
#
# Exit codes:
#   0 — zero false positives (PASS)
#   1 — at least one false positive
#   2 — setup error (missing key, missing dir, no repos)

set -uo pipefail

SWEEP_DIR="${SWEEP_DIR:-$HOME/clouddev/asp-demo-targets/sweep}"
OUT_DIR="${OUT_DIR:-/tmp/asp-sweep}"
MAX_TOKENS="${MAX_TOKENS:-100000}"

# ---- Setup ----------------------------------------------------------

if [[ -z "${ANTHROPIC_API_KEY:-}${OPENAI_API_KEY:-}${ASP_LLM_API_KEY:-}" ]]; then
  echo "ERROR: no LLM API key set. Export ANTHROPIC_API_KEY, OPENAI_API_KEY, or ASP_LLM_API_KEY." >&2
  exit 2
fi

if [[ ! -d "$SWEEP_DIR" ]]; then
  echo "ERROR: sweep directory not found: $SWEEP_DIR" >&2
  echo "Hint: clone target repos under that directory first." >&2
  exit 2
fi

# Use nullglob so an empty directory doesn't expand to a literal '*/'.
shopt -s nullglob
repos=("$SWEEP_DIR"/*/)
shopt -u nullglob

if (( ${#repos[@]} == 0 )); then
  echo "ERROR: no repos found under $SWEEP_DIR/" >&2
  echo "Clone some target repos first, e.g.:" >&2
  echo "  cd $SWEEP_DIR && git clone https://github.com/pallets/click click" >&2
  exit 2
fi

rm -rf "$OUT_DIR" && mkdir -p "$OUT_DIR"
results_log="$OUT_DIR/results.log"
stderr_log="$OUT_DIR/stderr.log"
: > "$results_log"
: > "$stderr_log"

# Move into the platform repo so `uv run` picks the right venv + sees prompts/.
cd "$(dirname "$(realpath "$0")")/.."

# ---- Sweep ----------------------------------------------------------

echo "Adversarial sweep over ${#repos[@]} repos under $SWEEP_DIR/"
echo "Max tokens per scan: $MAX_TOKENS"
echo "Logs:"
echo "  results: $results_log"
echo "  stderr:  $stderr_log"
echo

count_total=0
count_with_findings=0

for repo in "${repos[@]}"; do
  name=$(basename "$repo")
  count_total=$((count_total + 1))
  echo "=== [$count_total/${#repos[@]}] $name ===" | tee -a "$results_log"

  # Capture only stdout (clean JSON) for jq.
  # stderr goes to stderr_log so logs and rate-limit retries are auditable.
  findings=$(
    uv run python3 -m connectors.github.src \
        --repo-path "$repo" \
        --enable-llm \
        --max-llm-tokens "$MAX_TOKENS" \
        2>>"$stderr_log" \
      | jq -r '.nodes[]
        | select(.node_type | IN("Tool", "PromptTemplate", "RAGIndex", "MemoryStore"))
        | "  \(.node_type): \(.id)"'
  )

  if [[ -n "$findings" ]]; then
    count_with_findings=$((count_with_findings + 1))
    echo "$findings" | tee -a "$results_log"
  else
    echo "  (clean)" | tee -a "$results_log"
  fi
done

# ---- Summary --------------------------------------------------------

echo | tee -a "$results_log"
echo "=== Summary ===" | tee -a "$results_log"

# Count false positive nodes (lines that match the indented "<NodeType>: ..." pattern).
fp_count=$(grep -cE "^  (Tool|PromptTemplate|RAGIndex|MemoryStore):" "$results_log" || true)
echo "Repos scanned:        $count_total" | tee -a "$results_log"
echo "Repos with findings:  $count_with_findings" | tee -a "$results_log"
echo "Total false positives: $fp_count" | tee -a "$results_log"
echo | tee -a "$results_log"

if (( fp_count == 0 )); then
  echo "PASS — zero LLM-scope false positives across $count_total repos." | tee -a "$results_log"
  echo "Cleared to ship Option C (LLM scanner) as launch headline."  | tee -a "$results_log"
  exit 0
fi

echo "FAIL — $fp_count false positives across $count_with_findings of $count_total repos." | tee -a "$results_log"
echo "Review $results_log for the specific extractions." | tee -a "$results_log"
echo "Most likely fixes:" | tee -a "$results_log"
echo "  • Tighten the relevant prompt's 'What NOT to extract' section." | tee -a "$results_log"
echo "  • Bump SCANNER_VERSION (cache invalidates cleanly)." | tee -a "$results_log"
echo "  • Re-run the sweep." | tee -a "$results_log"
echo | tee -a "$results_log"
echo "If false positives don't tune away after 2 prompt-tuning rounds," | tee -a "$results_log"
echo "ADR-0005's fallback applies: ship LLM scanner as 'preview' framing"  | tee -a "$results_log"
echo "and the deterministic multi-stack manifest scanner as the launch headline." | tee -a "$results_log"
exit 1
