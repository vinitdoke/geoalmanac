#!/bin/bash
# Update GeoAlmanac Data
# Processes both Hiking (trails/) and Skiing (ski_tracks/) data

# Ensure we are in the project root (where this script should be)
cd "$(dirname "$0")"

# Run the processing script using the virtual environment
if [ -d ".venv" ]; then
    echo "Using virtual environment..."
    .venv/bin/python3 src/geoalmanac/process_gpx.py
else
    echo "Virtual environment not found, trying system python..."
    python3 src/geoalmanac/process_gpx.py
fi
