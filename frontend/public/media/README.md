# Media Replacement Guide

Place real project media in this folder.

- `roadshow-demo.mp4`: hero page roadshow video.
- `live-camera-demo.mp4`: camera recognition or screen-recorded hand tracking video.
- `microbit-wrist.jpg`: Micro:bit wrist mounting photo.
- `team-roadshow.jpg`: team, setup, or presentation photo.
- `guest-experience-demo.mp4`: visitor interaction recording for Guest Mode.
- `stage-setup-wide.jpg`: wide photo of the full hardware and presentation setup.

The current UI shows designed placeholders until these files are added.

Live Raspberry Pi camera streams do not need to be copied into this folder. The frontend does not use the laptop or PC webcam. Put the Pi camera URL in:

- Backend field: `GET /api/sensors/live -> camera.stream_url`
- Or local frontend env: `VITE_CAMERA_STREAM_URL`

Single-frame camera snapshots can use:

- Backend field: `GET /api/sensors/live -> camera.frame_url`
- Or local frontend env: `VITE_CAMERA_FRAME_URL`
