#!/bin/bash
# ============================================================
# SHIVA Full Integration Test Script
# Tests Directory, Manager, Partner, Guardian, Overseer, and Resource Hub
# ============================================================

SECRET="mysecretapikey"
HUB_URL="http://localhost:8007"
MANAGER_URL="http://localhost:8001"
GUARDIAN_URL="http://localhost:8003"

echo "=============================================="
echo "🚀 Starting SHIVA Integration Validation"
echo "=============================================="

# 1️⃣ Health check
echo "[1] Checking Resource Hub health..."
curl -s -H "X-SHIVA-SECRET: $SECRET" $HUB_URL/healthz | jq .

# 2️⃣ Tools list
echo -e "\n[2] Fetching registered tools..."
curl -s -H "X-SHIVA-SECRET: $SECRET" $HUB_URL/tools/list | jq .

# 3️⃣ Guardian policies
echo -e "\n[3] Fetching Guardian policies..."
curl -s -H "X-SHIVA-SECRET: $SECRET" $HUB_URL/policy/list | jq .

# 4️⃣ Memory operations
echo -e "\n[4] Writing and retrieving short-term memory..."
curl -s -X POST $HUB_URL/memory/task-auto \
  -H "X-SHIVA-SECRET: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"thought":"verify connection","action":"ping","observation":"pong"}' | jq .

sleep 1
curl -s -H "X-SHIVA-SECRET: $SECRET" $HUB_URL/memory/task-auto | jq .

# 5️⃣ RAG Retrieval (non-composed)
echo -e "\n[5] Testing retrieval (RAG)..."
curl -s -X POST $HUB_URL/rag/query \
  -H "X-SHIVA-SECRET: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"task_id":"task-demo","query":"what does ping do?","compose":false}' | jq .

# 6️⃣ RAG + Gemini (composed)
echo -e "\n[6] Testing Gemini reasoning (compose=true)..."
curl -s -X POST $HUB_URL/rag/query \
  -H "X-SHIVA-SECRET: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"task_id":"task-demo","query":"which guardian policy prevents deletion?","compose":true}' | jq .

# 7️⃣ Manager → Resource Hub end-to-end task
echo -e "\n[7] Invoking task via Manager Service..."
TASK_ID=$(curl -s -X POST $MANAGER_URL/invoke \
  -H "Content-Type: application/json" \
  -H "X-SHIVA-SECRET: $SECRET" \
  -d '{"goal": "Fetch and analyze system status"}' | jq -r '.task_id')

echo "Task created: $TASK_ID"
sleep 3
curl -s $MANAGER_URL/task/$TASK_ID/status | jq .

# 8️⃣ Check overall Directory registry
echo -e "\n[8] Checking Directory registered services..."
curl -s -H "X-SHIVA-SECRET: $SECRET" http://localhost:8005/list | jq .

echo -e "\n✅ All tests executed. Review outputs for anomalies."
