#!/bin/bash

# Navigate to the backend directory
cd "$(dirname "$0")/.."

echo "Starting FareWise Backend Server in background..."

# Check if .venv exists and activate it
if [ -d ".venv" ]; then
    echo "Activating .venv virtual environment..."
    source .venv/bin/activate
elif [ -d "venv" ]; then
    echo "Activating venv virtual environment..."
    source venv/bin/activate
else
    echo "WARNING: Virtual environment not found (.venv or venv). Attempting to run anyway."
fi

# Need to kill any existing process on port 8000 first
PID=$(lsof -ti:8000)
if [ ! -z "$PID" ]; then
  echo "Found process running on port 8000 (PID: $PID). Killing it..."
  kill -9 $PID
  sleep 1
fi

# Start the uvicorn server in the background and save its PID
if [ -d ".venv" ]; then
    nohup .venv/bin/python -m uvicorn main:app --reload --port 8000 > logs/server.log 2>&1 &
elif [ -d "venv" ]; then
    nohup venv/bin/python -m uvicorn main:app --reload --port 8000 > logs/server.log 2>&1 &
else
    nohup python -m uvicorn main:app --reload --port 8000 > logs/server.log 2>&1 &
fi
SERVER_PID=$!

# Ensure logs directory exists
mkdir -p logs

echo $SERVER_PID > bin/.server.pid
echo "Server started with PID: $SERVER_PID. Logs at logs/server.log"
echo "Running on http://127.0.0.1:8000"
