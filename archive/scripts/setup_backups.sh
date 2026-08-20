#!/bin/bash
set -e

echo "🗄️  Setting up FIM Database Backups"
echo "===================================="
echo ""

# Create backup directory if not exists
mkdir -p /opt/fim/fim-backups/{dumps,logs}
mkdir -p /opt/fim/fim-backups/scripts

# Create .pgpass file for passwordless backup
cat > ~/.pgpass << 'PGPASS_EOF'
localhost:5432:fim_db:fim_app:your_password_here
PGPASS_EOF

chmod 600 ~/.pgpass

echo "⚠️  IMPORTANT: Edit ~/.pgpass and replace 'your_password_here' with actual fim_app password"
echo "Press Enter after updating the password..."
read

# Test database connection
echo "Testing database connection..."
if psql -h localhost -U fim_app -d fim_db -c "SELECT 1;" > /dev/null 2>&1; then
    echo "✅ Database connection successful"
else
    echo "❌ Database connection failed. Check ~/.pgpass password"
    exit 1
fi

# Create backup script
cat > /opt/fim/fim-backups/scripts/backup_fim.sh << 'BACKUP_EOF'
#!/bin/bash
set -e

BACKUP_DIR="/opt/fim/fim-backups/dumps"
LOG_FILE="/opt/fim/fim-backups/logs/backup.log"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="fim_db_${TIMESTAMP}.sql.gz"
RETENTION_DAYS=30

echo "[$(date)] Starting backup..." >> "$LOG_FILE"

# Create backup using fim_app user
PGPASSFILE=~/.pgpass pg_dump -h localhost -U fim_app fim_db | gzip > "${BACKUP_DIR}/${BACKUP_FILE}"

if [ $? -eq 0 ]; then
    echo "[$(date)] Backup successful: ${BACKUP_FILE}" >> "$LOG_FILE"
    
    # Delete old backups
    find "${BACKUP_DIR}" -name "fim_db_*.sql.gz" -mtime +${RETENTION_DAYS} -delete
    echo "[$(date)] Old backups cleaned (retention: ${RETENTION_DAYS} days)" >> "$LOG_FILE"
else
    echo "[$(date)] Backup FAILED" >> "$LOG_FILE"
    exit 1
fi
BACKUP_EOF

chmod +x /opt/fim/fim-backups/scripts/backup_fim.sh

# Create restore script
cat > /opt/fim/fim-backups/scripts/restore_fim.sh << 'RESTORE_EOF'
#!/bin/bash
set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    echo ""
    echo "Available backups:"
    ls -lh /opt/fim/fim-backups/dumps/fim_db_*.sql.gz 2>/dev/null || echo "No backups found"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "⚠️  WARNING: This will restore database from backup!"
echo "Backup file: $BACKUP_FILE"
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled"
    exit 0
fi

echo "Stopping FIM server..."
systemctl stop fim-server

echo "Restoring database..."
gunzip -c "$BACKUP_FILE" | PGPASSFILE=~/.pgpass psql -h localhost -U fim_app fim_db

echo "Starting FIM server..."
systemctl start fim-server

echo "✅ Restore complete!"
RESTORE_EOF

chmod +x /opt/fim/fim-backups/scripts/restore_fim.sh

echo ""
echo "✅ Backup scripts created!"
echo ""
echo "Next steps:"
echo "1. Edit ~/.pgpass and add your fim_app password"
echo "2. Run the backup script manually to test"
echo ""
