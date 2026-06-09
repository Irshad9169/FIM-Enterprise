#!/bin/bash

cd /opt/fim/frontend

# Create necessary directories
mkdir -p lib/queries types components/{layout,ui,charts}

# Create .env.local
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_APP_NAME=FIM Dashboard
NEXT_PUBLIC_APP_VERSION=1.0.0
EOF

# Install dependencies
npm install

echo "✅ Setup complete! Run 'npm run dev' to start the development server."
