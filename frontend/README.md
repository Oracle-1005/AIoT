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

## WebSocket Data

The app uses mock data unless a WebSocket URL is configured.

Create `.env.local`:

```bash
VITE_CONDUCTOR_WS_URL=ws://localhost:8000/ws/conductor
```

Expected payload shape:

```json
{
  "timestamp": "2026-07-12T20:16:31.774Z",
  "camera": {
    "leftHandY": 0.72,
    "rightHandX": 0.61,
    "handDistance": 0.54,
    "movementSpeed": 1.86,
    "trajectoryAngle": 82
  },
  "microbit": {
    "left": {
      "id": "Device A",
      "battery": 86,
      "signal": "Excellent",
      "motion": "Rising",
      "x": 0.13,
      "y": 1.42,
      "z": 0.29
    },
    "right": {
      "id": "Device B",
      "battery": 81,
      "signal": "Good",
      "motion": "Downbeat",
      "x": 0.86,
      "y": 2.18,
      "z": 0.71
    }
  },
  "prediction": {
    "gesture": "crescendo",
    "label": "CRESCENDO",
    "zh": "Build intensity",
    "confidence": 94,
    "response": "Volume +14%, Energy +28%",
    "top3": [
      { "label": "Crescendo", "value": 94 },
      { "label": "Tempo Up", "value": 4 },
      { "label": "Idle", "value": 2 }
    ]
  },
  "music": {
    "title": "Demo Symphony No.1",
    "bpm": 108,
    "volume": 72,
    "energy": 68,
    "density": 45,
    "key": "C Major",
    "style": "Cinematic",
    "progress": 42
  },
  "latency": 84
}
```

The WebSocket-ready adapter is in `src/hooks/useConductorFeed.js`.

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
