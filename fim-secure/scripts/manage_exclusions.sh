#!/bin/bash

EXCLUSIONS_FILE="/opt/fim/config/exclusions.txt"
VENV_PATH="/opt/fim/venv"

case "$1" in
    edit)
        ${EDITOR:-nano} "$EXCLUSIONS_FILE"
        ;;
    sync)
        source "$VENV_PATH/bin/activate"
        python /opt/fim/scripts/sync_exclusions.py
        ;;
    list)
        echo "Current Exclusions:"
        grep -v '^#' "$EXCLUSIONS_FILE" | grep -v '^$' | nl
        ;;
    add)
        if [ -z "$2" ]; then
            echo "Usage: $0 add <path>"
            exit 1
        fi
        echo "$2" >> "$EXCLUSIONS_FILE"
        echo "✅ Added: $2"
        echo "Run '$0 sync' to apply changes"
        ;;
    remove)
        if [ -z "$2" ]; then
            echo "Usage: $0 remove <path>"
            exit 1
        fi
        sed -i "\|^$2$|d" "$EXCLUSIONS_FILE"
        echo "✅ Removed: $2"
        echo "Run '$0 sync' to apply changes"
        ;;
    check)
        source "$VENV_PATH/bin/activate"
        psql -h localhost -U fim_app -d fim_db -c "
        SELECT 
            rule_name, 
            rule_type, 
            match_value, 
            is_active,
            match_count
        FROM fim.whitelist_rules 
        WHERE reason LIKE 'Auto-synced from exclusions.txt%'
        ORDER BY rule_type, match_value;
        "
        ;;
    *)
        echo "FIM Exclusion Management Tool"
        echo ""
        echo "Usage: $0 {edit|sync|list|add|remove|check}"
        echo ""
        echo "Commands:"
        echo "  edit          - Edit exclusions file"
        echo "  sync          - Sync exclusions to database"
        echo "  list          - List current exclusions"
        echo "  add <path>    - Add new exclusion"
        echo "  remove <path> - Remove exclusion"
        echo "  check         - Check database rules"
        echo ""
        echo "Examples:"
        echo "  $0 add /var/cache/*"
        echo "  $0 sync"
        echo "  $0 list"
        exit 1
        ;;
esac
