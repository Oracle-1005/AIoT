#!/usr/bin/env bash
set -euo pipefail
mkdir -p models
URL='https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'
curl -fL "$URL" -o models/hand_landmarker.task
printf 'Downloaded: %s\n' "$(realpath models/hand_landmarker.task)"
