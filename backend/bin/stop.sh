#!/bin/bash

cd "$(dirname "$0")/.."

echo "Stopping FareWise Backend Server..."

if [ -f "bin/.server.pid" ]; then
  PID=$(cat bin/.server.pid)
  if ps -p $PID > /dev/null; then
    echo "Killing process $PID..."
    kill -9 $PID
    rm bin/.server.pid
    echo "Server stopped."
  else
    echo "Process $PID not found. Cleaning up pid file."
    rm bin/.server.pid
  fi
else
  # Fallback to checking port 8000
  PID=$(lsof -ti:8000)
  if [ ! -z "$PID" ]; then
    echo "Found process running on port 8000 (PID: $PID). Killing it..."
    kill -9 $PID
    echo "Server stopped."
  else
    echo "No server process found running on port 8000 or in bin/.server.pid."
  fi
fi
