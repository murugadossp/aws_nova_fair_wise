#!/bin/bash

# Navigate to the backend directory
cd "$(dirname "$0")"

echo "Restarting FareWise Backend Server..."

./stop.sh
sleep 1
./start.sh
