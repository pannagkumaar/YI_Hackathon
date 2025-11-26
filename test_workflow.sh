#!/bin/bash

API="mysecretapikey"

echo ""
echo "============================================"
echo "🔥 SHIVA FULL WORKFLOW TEST STARTING"
echo "============================================"
echo ""

# 1) Invoke a new task
echo "→ Invoking Manager task..."
RESP=$(curl -s -X POST http://127.0.0.1:8001/invoke \
  -H "X-SHIVA-SECRET: $API" \
  -H "Content-Type: application/json" \
  -d '{"goal":"Check connectivity to 8.8.8.8","context":{}}')

echo "$RESP" | jq

TASK_ID=$(echo "$RESP" | jq -r '.task_id')

if [[ "$TASK_ID" == "null" || "$TASK_ID" == "" ]]; then
  echo "❌ ERROR: Could not extract task_id"
  exit 1
fi

echo ""
echo "→ Extracted task_id: $TASK_ID"
echo ""

# 2) Poll manager until WAITING_APPROVAL / COMPLETED / FAILED
STATUS="PENDING"

echo "→ Polling Manager for status..."
for i in {1..15}; do
    STATUS_JSON=$(curl -s -H "X-SHIVA-SECRET: $API" \
      http://127.0.0.1:8001/task/$TASK_ID/status)

    STATUS=$(echo "$STATUS_JSON" | jq -r '.status')
    echo "   [$i] Status = $STATUS"

    if [[ "$STATUS" == "WAITING_APPROVAL" ]]; then
        echo ""
        echo "🔶 Guardian returned AMBIGUOUS — waiting approval."
        break
    fi

    if [[ "$STATUS" == "COMPLETED" ]]; then
        echo ""
        echo "🟢 Workflow already completed! "
        break
    fi

    if [[ "$STATUS" == "REJECTED" || "$STATUS" == "FAILED" ]]; then
        echo ""
        echo "❌ ERROR: Task ended in bad state!"
        echo "$STATUS_JSON" | jq
        exit 1
    fi

    sleep 1
done

# 3) Approve if required
if [[ "$STATUS" == "WAITING_APPROVAL" ]]; then
    echo "→ Approving task..."
    curl -s -X POST \
      -H "X-SHIVA-SECRET: $API" \
      http://127.0.0.1:8001/task/$TASK_ID/approve | jq

    echo ""
    echo "→ Polling post-approval..."
    for i in {1..15}; do
        STATUS_JSON=$(curl -s -H "X-SHIVA-SECRET: $API" \
            http://127.0.0.1:8001/task/$TASK_ID/status)
        STATUS=$(echo "$STATUS_JSON" | jq -r '.status')

        echo "   [$i] Status = $STATUS"

        if [[ "$STATUS" == "COMPLETED" ]]; then
            echo ""
            echo "🟢 Task COMPLETED successfully!"
            break
        fi

        if [[ "$STATUS" == "FAILED" || "$STATUS" == "REJECTED" ]]; then
            echo ""
            echo "❌ Task failed:"
            echo "$STATUS_JSON" | jq
            break
        fi

        if [[ "$STATUS" == "PAUSED_DEVIATION" ]]; then
            echo ""
            echo "🟡 Deviation detected:"
            echo "$STATUS_JSON" | jq
            break
        fi

        sleep 1
    done
fi

# 4) Fetch logs from overseer
echo ""
echo "→ Fetching Overseer logs (last 30)..."
curl -s -H "X-SHIVA-SECRET: $API" \
  "http://127.0.0.1:8004/logs?limit=30" | jq

echo ""
echo "============================================"
echo "🔥 SHIVA FULL WORKFLOW TEST FINISHED"
echo "============================================"
echo ""

