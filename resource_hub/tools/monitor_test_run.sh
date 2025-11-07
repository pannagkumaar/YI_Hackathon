#!/usr/bin/env bash
OUTDIR=./tools/test_logs
mkdir -p "$OUTDIR"
LOG="$OUTDIR/run_$(date +%Y%m%d_%H%M%S).log"

echo "Logging to $LOG"
echo "==== START $(date) ====" >> "$LOG"
echo "Env: OMP_NUM_THREADS=$OMP_NUM_THREADS, MKL_NUM_THREADS=$MKL_NUM_THREADS, CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES" >> "$LOG"

# Start background sensors watch if available
if command -v sensors >/dev/null 2>&1; then
  ( while true; do date +%H:%M:%S >> "$LOG"; sensors >> "$LOG"; sleep 1; done ) & SENS_PID=$!
  echo "sensors logging PID $SENS_PID" >> "$LOG"
fi

# Log top-like snapshot every 2 seconds
( while true; do echo "---- top snapshot --- $(date +%H:%M:%S)" >> "$LOG"; top -b -n1 | head -n 20 >> "$LOG"; free -h >> "$LOG"; sleep 2; done ) &
TOP_PID=$!
echo "top logging PID $TOP_PID" >> "$LOG"

# Run pytest (single-shot). Adjust test selection if you want to isolate a test file.
pytest "$@" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}

# cleanup
if [ -n "$SENS_PID" ]; then kill $SENS_PID || true; fi
kill $TOP_PID || true

echo "==== END $(date) RC=$RC ====" >> "$LOG"
echo "Log saved to $LOG"
exit $RC
