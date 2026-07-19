# AIoT Smart Conducting Performance System

Roadshow frontend for an AIoT smart conducting project. The app presents the full system concept:

- Camera hand tracking
- Dual Micro:bit motion sensing
- Raspberry Pi 5 edge processing
- Local AI gesture recognition
- Real-time music control
- Database logging and historical analytics

The interface is built for course demos, roadshows, and final presentations. It uses realistic mock data by default and is ready to connect to a WebSocket feed later.

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
    "microbit_left": { "acc_x": 0.0, "acc_y": 0.0, "acc_z": 0.0 },
    "microbit_right": { "acc_x": 0.0, "acc_y": 0.0, "acc_z": 0.0 },
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
        "window_features": 0,
        "control_event": 0,
        "status": 0
      }
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
in mg. The adapter converts both formats to g before rendering.

Optional future WebSocket mode is still supported:

```bash
VITE_CONDUCTOR_WS_URL=ws://localhost:8000/ws/frontend
```

The data adapter is in `src/hooks/useConductorFeed.js`.

## Real Media Slots

The UI intentionally reserves space for real project video and photos. Add final media files under `public/media/`.

| Slot | Suggested file | Where it appears |
|---|---|---|
| Main roadshow video | `public/media/roadshow-demo.mp4` | Hero section |
| Camera recognition capture | `public/media/live-camera-demo.mp4` | Live Conducting Stage |
| Micro:bit wrist photo | `public/media/microbit-wrist.jpg` | Dual Micro:bit cards |
| Team / site photo | `public/media/team-roadshow.jpg` | About section |

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
