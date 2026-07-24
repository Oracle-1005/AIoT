# AIoT Smart Conducting Performance System

Roadshow frontend for an AIoT smart conducting project. The app presents the full system concept:

- Camera hand tracking
- Dual Micro:bit motion sensing
- Raspberry Pi 5 edge processing
- Pi-side gesture and event recognition
- Real-time music control
- Database logging and historical analytics

The interface is built for course demos, roadshows, and final presentations. It uses realistic mock data by default, connects to the Flask REST backend, and keeps an optional WebSocket frontend feed hook for later expansion.

## Tech Stack

- React + Vite
- Tailwind CSS
- Framer Motion
- Recharts
- Lucide React icons

## Run Locally

```bash
npm install
npm run dev
```

Then open the local URL printed in the terminal.

## Build

```bash
npm run build
```

The production files will be generated in `dist/`.

## Backend Data

The app currently supports the Flask backend in `../backend` through REST polling.
If the backend is not running, the frontend automatically falls back to mock data.

Create `.env.local`:

```bash
VITE_BACKEND_BASE_URL=http://localhost:5000
VITE_CAMERA_STREAM_URL=
VITE_CAMERA_FRAME_URL=
```

The current backend endpoints are:

```text
GET /api/status
GET /api/gesture/current
GET /api/gesture/history?limit=20
GET /api/sensors/live
GET /api/music/state
GET /api/pi/status
```

The frontend adapter polls `/api/status`, `/api/gesture/current`,
`/api/sensors/live`, `/api/music/state`, and `/api/pi/status`, then
normalizes them into the display frame used by the roadshow UI.

Current backend shapes:

```json
{
  "status": {
    "status": "ok",
    "camera_connected": false,
    "microbit_left": false,
    "microbit_right": false,
    "model_loaded": false,
    "pi_gateway": {
      "enabled": true,
      "running": true,
      "connected": false,
      "listen_host": "0.0.0.0",
      "listen_port": 9000
    },
    "uptime_seconds": 1
  },
  "gesture_current": {
    "gesture": "idle",
    "confidence": 0.0,
    "gesture_id": 0,
    "timestamp": 0.0,
    "features_used": 0,
    "all_probs": {
      "idle": 1.0,
      "downbeat": 0.0
    }
  },
  "sensors_live": {
    "microbit_left": {
      "device_id": "MB_LEFT",
      "hand": "left",
      "raw_interpolated": {
        "acceleration_mg": [84, 1164, -362],
        "pitch_deg": 18,
        "roll_deg": -7
      }
    },
    "microbit_right": {
      "device_id": "MB_RIGHT",
      "hand": "right",
      "raw_interpolated": {
        "acceleration_mg": [-102, 1388, -418],
        "pitch_deg": 21,
        "roll_deg": 6
      }
    },
    "hand_detected": false,
    "hand_count": 0,
    "timestamp": 0.0
  },
  "pi_status": {
    "gateway": {
      "enabled": true,
      "running": true,
      "connected": false,
      "listen_host": "0.0.0.0",
      "listen_port": 9000,
      "received_messages": 0,
      "sent_messages": 0,
      "last_error": null
    },
    "runtime": {
      "last_message_type": null,
      "last_message_at": null,
      "message_counts": {
        "fused_frame": 0,
        "control_event": 0,
        "status": 0
      },
      "last_control_event": null
    }
  },
  "music_state": {
    "playing": false,
    "bpm": 120,
    "volume": 0.8,
    "style": "piano",
    "current_gesture": "idle"
  }
}
```

Micro:bit acceleration values can use either frontend-friendly `acc_x`,
`acc_y`, `acc_z` fields in g, or Pi uplink fields `ax_mg`, `ay_mg`, `az_mg`
in mg. The current Pi schema also supports `raw_interpolated.acceleration_mg`
and `instant_features.acceleration_g` arrays. The adapter converts all supported
formats to g before rendering.

For live hardware, the Pi sends three uplink message types to the PC backend:
`fused_frame`, `control_event`, and `status`. `window_features` is internal to
the Pi-side pipeline and is not expected by the frontend.

The UI treats `/api/music/state.current_gesture` and
`/api/pi/status.runtime.last_control_event.payload.event` as the live gesture
source when the PC-side prediction endpoint is still idle.

Optional future WebSocket mode is still supported:

```bash
VITE_CONDUCTOR_WS_URL=ws://localhost:8000/ws/frontend
```

The data adapter is in `src/hooks/useConductorFeed.js`.

## Reserved Real Camera / Hand Tracking Inputs

These fields are already reserved in the frontend. The backend can add them later without changing the page structure.
The camera source is the Raspberry Pi camera feed, not the laptop or PC webcam. The frontend does not call `getUserMedia`; it only renders the URL supplied by the backend or `.env.local`.

```json
{
  "sensors_live": {
    "camera": {
      "stream_url": "http://<pi-or-backend-host>:<port>/camera.mjpg",
      "frame_url": "http://<pi-or-backend-host>:<port>/camera/latest.jpg",
      "frame_id": 4821,
      "width": 640,
      "height": 480,
      "fps": 30,
      "hands": [
        {
          "handedness": "left",
          "confidence": 0.97,
          "landmarks_normalized": [
            [0.514, 0.742, -0.012]
          ],
          "features": {
            "wrist_velocity": [0.18, -0.43, 0.02]
          }
        }
      ]
    }
  }
}
```

Frontend behavior:

- If `camera.stream_url` or `VITE_CAMERA_STREAM_URL` exists, the camera area shows the real Raspberry Pi camera stream.
- If `camera.frame_url` or `VITE_CAMERA_FRAME_URL` exists, the camera area can show a repeatedly updated single-frame image.
- If `camera.hands[].landmarks_normalized`, `image_landmarks`, or `landmarks` exists, the frontend overlays a 21-point hand skeleton and motion trail.
- If these fields are missing, the UI keeps the reserved slot visible and falls back to the designed mock visualization.
- Gesture-to-music control still comes from `/api/pi/status.runtime.last_control_event.payload.event` or `/api/music/state.current_gesture`.
- LED feedback is reserved through `/api/pi/status.runtime.last_control_event.payload.led_control`.

Recommended `control_event` addition:

```json
{
  "event": {
    "type": "downbeat",
    "hand": "right",
    "confidence": 0.94,
    "strength": 0.83
  },
  "music_control": {
    "estimated_bpm": 118,
    "volume": 0.73,
    "intensity": 0.81
  },
  "led_control": {
    "pattern": "right_pulse",
    "brightness": 0.55,
    "duration_ms": 120
  }
}
```

## Real Media Slots

The UI intentionally reserves space for real project video and photos. Add final media files under `public/media/`.

| Slot | Suggested file | Where it appears |
|---|---|---|
| Main roadshow video | `public/media/roadshow-demo.mp4` | Hero section |
| Camera recognition capture | `public/media/live-camera-demo.mp4` | Live Conducting Stage |
| Micro:bit wrist photo | `public/media/microbit-wrist.jpg` | Dual Micro:bit cards |
| Team / site photo | `public/media/team-roadshow.jpg` | About section |
| Guest experience recording | `public/media/guest-experience-demo.mp4` | Visitor / Guest Mode notes |
| Full setup wide photo | `public/media/stage-setup-wide.jpg` | About / setup documentation |

Recommended shots:

- 20-40 second horizontal video showing a student conducting and the music parameters changing.
- Screen capture of hand landmarks, skeleton lines, and gesture prediction labels.
- Close-up photo of the Micro:bit fixed to the left and right wrist.
- One team or final roadshow photo showing the complete setup.

## Page Structure

- Hero page
- Live Conducting Stage
- Camera / gesture panel
- AI prediction card with confidence and Top-3 results
- Dual Micro:bit sensor cards
- Music control center
- AI decision-flow visualization
- Key proof points for technical validation and roadshow defense
- Historical analytics dashboard
- Architecture view
- Calibration and training page
- Project / about section
- Full-screen presentation mode

## Source Notes

The app follows the project framework from the referenced conversation and preserves the core concept: Camera + Micro:bit + local AI + Raspberry Pi + real-time music control + database logging.
