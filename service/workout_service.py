"""Foreground service to keep the app alive during workouts.

This service does nothing except exist as a foreground process with a
persistent notification, which prevents Android from killing audio playback
when the screen is off.
"""
import time
from os import environ

# Keep the service process alive
while True:
    time.sleep(60)
