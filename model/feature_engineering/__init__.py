"""
Feature Engineering Module
==========================
Extracts feature vectors from raw camera landmarks and micro:bit accelerometer data.

Pipeline:
  raw data → SlidingWindow → CameraFeatures + AccelFeatures → combined vector
"""
