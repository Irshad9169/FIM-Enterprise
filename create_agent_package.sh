#!/bin/bash
# Create FIM Agent Distribution Package

PACKAGE_NAME="fim-agent-1.0"
PACKAGE_DIR="/tmp/$PACKAGE_NAME"

echo "Creating FIM Agent package..."

# Clean previous package
rm -rf $PACKAGE_DIR
rm -f /tmp/${PACKAGE_NAME}.tar.gz

# Create package structure
mkdir -p $PACKAGE_DIR

# Copy agent files
cp -r agent/fim_agent.py $PACKAGE_DIR/
cp -r agent/config $PACKAGE_DIR/
cp agent/install.sh $PACKAGE_DIR/

# Create README
cat > $PACKAGE_DIR/README.md << 'README_EOF'
# FIM Agent Installation

## Quick Install
tar -xzf fim-agent-1.0.tar.gz
cd fim-agent-1.0
sudo ./install.sh

## Configuration
Edit /opt/fim-agent/config/agent_config.yaml

## Start Service
sudo systemctl start fim-agent
sudo systemctl status fim-agent
README_EOF

# Create tarball
cd /tmp
tar -czf ${PACKAGE_NAME}.tar.gz $PACKAGE_NAME/

echo "Package created: /tmp/${PACKAGE_NAME}.tar.gz"
ls -lh /tmp/${PACKAGE_NAME}.tar.gz
