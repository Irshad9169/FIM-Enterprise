#!/bin/bash
# Automatically trigger FIM report generation for yesterday
YESTERDAY=$(date -d "yesterday" '+%Y-%m-%d')
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | jq -r '.access_token')

curl -X POST http://localhost:8000/api/v1/reports/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"report_date\": \"$YESTERDAY\"}"

echo "Report generated for $YESTERDAY at $(date)"
