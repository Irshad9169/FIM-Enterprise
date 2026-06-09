#!/bin/bash
set -e

echo "Building FIM Frontend..."
cd /opt/fim/frontend

# Install dependencies
npm install

# Build production
npm run build

echo "✅ Frontend built to /opt/fim/web"
ls -lh /opt/fim/web/
