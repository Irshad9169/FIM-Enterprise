#!/bin/bash
# FIM Agent Installation Script

set -e

INSTALL_DIR="/opt/fim-agent"
SERVICE_USER="secauto"
SERVICE_NAME="fim-agent"

echo "=========================================="
echo "FIM Agent Installation"
echo "=========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
   echo "ERROR: Please run as root"
   exit 1
fi

# Create installation directory
echo "[1/6] Creating installation directory..."
mkdir -p $INSTALL_DIR/{config,logs}

# Copy files
echo "[2/6] Copying agent files..."
cp fim_agent.py $INSTALL_DIR/
cp config/agent_config.yaml $INSTALL_DIR/config/
chmod +x $INSTALL_DIR/fim_agent.py

# Install Python dependencies
echo "[3/6] Installing Python dependencies..."
if command -v python3 &> /dev/null; then
    python3 -m pip install --quiet pyyaml requests || {
        echo "WARNING: pip install failed. Install manually: pip3 install pyyaml requests"
    }
    # watchdog enables real-time change detection (in addition to the
    # scheduled scan) — optional: fim_agent.py falls back to scheduled-scan-
    # only if this isn't installed, so a failure here doesn't block install.
    python3 -m pip install --quiet watchdog || {
        echo "WARNING: watchdog install failed — real-time detection will be disabled, scheduled scans still work. Install manually: pip3 install watchdog"
    }
else
    echo "ERROR: Python 3 not found. Please install Python 3.6+"
    exit 1
fi

# Create systemd service
echo "[4/6] Creating systemd service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << SERVICE_EOF
[Unit]
Description=FIM Agent - File Integrity Monitoring
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/fim_agent.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/fim_agent.log
StandardError=append:$INSTALL_DIR/logs/fim_agent.log

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# Set permissions
echo "[5/6] Setting permissions..."
chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR

# Reload systemd
echo "[6/6] Reloading systemd..."
systemctl daemon-reload

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit configuration: $INSTALL_DIR/config/agent_config.yaml"
echo "2. Update server URL to point to your FIM server"
echo "3. Register agent: cd $INSTALL_DIR && python3 fim_agent.py --register"
echo "4. Start service: systemctl start $SERVICE_NAME"
echo "5. Enable on boot: systemctl enable $SERVICE_NAME"
echo "6. Check status: systemctl status $SERVICE_NAME"
echo "7. View logs: tail -f $INSTALL_DIR/logs/fim_agent.log"
echo ""
