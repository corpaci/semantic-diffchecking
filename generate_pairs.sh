#!/bin/bash
# Wrapper script for generate_oracle_pairs_v2.py
# Automatically sets ETP_EQUATIONS environment variable

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ETP_EQUATIONS="$SCRIPT_DIR/oracle/equations.txt"

# Check if equations.txt exists
if [ ! -f "$ETP_EQUATIONS" ]; then
    echo "⚠️  equations.txt not found. Downloading..."
    wget -q -O "$ETP_EQUATIONS" https://raw.githubusercontent.com/teorth/equational_theories/main/data/equations.txt
    if [ $? -eq 0 ]; then
        echo "✅ Downloaded equations.txt"
    else
        echo "❌ Failed to download equations.txt"
        exit 1
    fi
fi

# Run the Python script with all arguments passed through
python3 "$SCRIPT_DIR/generate_oracle_pairs_v2.py" "$@"
