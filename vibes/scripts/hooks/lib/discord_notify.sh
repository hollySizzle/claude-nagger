#!/bin/bash

# Enable safer bash execution
set -u

# Load environment variables from vibes/scripts/.env
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ENV_FILE="$SCRIPT_DIR/../../.env"

if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

# Check if Discord webhook URL is set
if [ -z "${DISCORD_WEBHOOK_URL:-}" ]; then
    echo "Discord webhook not configured, skipping notification" >&2
    exit 0  # Don't block hook execution if webhook is not configured
fi

# Message to send (use first argument if provided, otherwise default)
MESSAGE="${1:-hello}"

# Generate a friendly agent name based on session ID
generate_agent_name() {
    local session_id="$1"
    
    # Array of agent names
    names=("キヨマツ" "ヤギヌマ" "イタバ" "キタハシ" "イワモリ" "ロッカク" "シモヤマ" "ウニスガ" "タカミチ" "ミサカ" "ダンノ" "コレマツ" "ノナミ" "キリウ" "ユタカ" "マイグマ" "モリミツ" "サカガワ" "キマタ")
    
    # Generate numeric hash from session_id for consistent name selection
    if command -v cksum >/dev/null 2>&1; then
        # Use cksum for hash generation (more portable)
        hash_value=$(echo -n "$session_id" | cksum | cut -d' ' -f1)
    else
        # Fallback: use string length and ASCII values
        hash_value=0
        for (( i=0; i<${#session_id}; i++ )); do
            ascii=$(printf '%d' "'${session_id:$i:1}")
            hash_value=$((hash_value + ascii))
        done
    fi
    
    name_index=$((hash_value % ${#names[@]}))
    
    # Generate short identifier from last 8 characters of session_id
    short_id="${session_id: -8}"
    
    echo "${names[$name_index]}-${short_id}"
}

# Try to get session_id from stdin JSON, fallback to PID
SESSION_ID=""
if [ -t 0 ]; then
    # No input from stdin, use PID as fallback
    SESSION_ID="$$"
else
    # Try to extract session_id from JSON input
    if command -v jq >/dev/null 2>&1; then
        # Read stdin once and store it
        input_data=$(cat)
        SESSION_ID=$(echo "$input_data" | jq -r '.session_id // empty' 2>/dev/null)
        # If session_id extraction failed or is empty, use PID
        if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
            SESSION_ID="$$"
        fi
    else
        # Fallback to PID if jq is not available
        SESSION_ID="$$"
        # Consume stdin to avoid broken pipe
        cat >/dev/null 2>&1
    fi
fi

# Generate agent name
AGENT_NAME=$(generate_agent_name "$SESSION_ID")

# Create formatted message with agent name and timestamp
TIMESTAMP=$(date "+%H:%M:%S")
FORMATTED_MESSAGE="🤖 **$AGENT_NAME** [$TIMESTAMP] $MESSAGE"

# Send message to Discord
if curl -s -H "Content-Type: application/json" \
        -X POST \
        -d "{\"content\":\"$FORMATTED_MESSAGE\"}" \
        "$DISCORD_WEBHOOK_URL" >/dev/null 2>&1; then
    echo "Message sent to Discord [$AGENT_NAME]: $MESSAGE" >&2
else
    echo "Failed to send Discord message [$AGENT_NAME]: $MESSAGE" >&2
    exit 0  # Don't block hook execution on Discord API failure
fi