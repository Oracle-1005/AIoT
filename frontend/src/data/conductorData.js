export const navItems = [
  { id: 'home', label: 'Home', short: 'Home' },
  { id: 'experience-gateway', label: 'Experience', short: 'Try' },
  { id: 'live-stage', label: 'Workflow View', short: 'Workflow' },
  { id: 'ai-flow', label: 'AI Flow', short: 'AI' },
  { id: 'validation', label: 'Highlights', short: 'Value' },
  { id: 'analytics', label: 'Analytics', short: 'Data' },
  { id: 'architecture', label: 'Architecture', short: 'Arch' },
  { id: 'training', label: 'Calibration', short: 'Train' },
  { id: 'about', label: 'About', short: 'About' },
]

export const teamMembers = [
  {
    name: 'WANG YIZHE',
    id: 't0939395',
    role: 'Team Lead / AI Model',
    focus: 'MediaPipe and Random Forest gesture inference pipeline',
  },
  {
    name: 'WANG XIDA',
    id: 't0939390',
    role: 'Frontend',
    focus: 'Roadshow homepage, live dashboard, and visitor interaction display',
  },
  {
    name: 'LUO ZICHAO',
    id: 't0939291',
    role: 'Backend',
    focus: 'Flask API, SQLite logging, and Sonic Pi control bridge',
  },
  {
    name: 'WANG JUNZHI',
    id: 't0939382',
    role: 'Hardware',
    focus: 'Micro:bit firmware, ESP32 gateway, and wearable sensing',
  },
  {
    name: 'WANG QINGYUAN',
    id: 't0939384',
    role: 'Hardware',
    focus: 'Raspberry Pi 5, Pi Camera, fusion pipeline, and LED matrix',
  },
]

export const gestureCatalog = [
  {
    key: 'idle',
    label: 'IDLE',
    zh: 'Hold state',
    response: 'Maintain current playback state',
    color: '#94a3b8',
  },
  {
    key: 'crescendo',
    label: 'CRESCENDO',
    zh: 'Build intensity',
    response: 'Volume +14%, Energy +28%',
    color: '#f4c76b',
  },
  {
    key: 'downbeat',
    label: 'DOWNBEAT',
    zh: 'Primary beat',
    response: 'Trigger Beat, BPM Sync',
    color: '#38bdf8',
  },
  {
    key: 'tempoUp',
    label: 'TEMPO UP',
    zh: 'Accelerate tempo',
    response: 'BPM +6',
    color: '#22c55e',
  },
  {
    key: 'decrescendo',
    label: 'DECRESCENDO',
    zh: 'Reduce intensity',
    response: 'Volume -10%, Energy -18%',
    color: '#8b5cf6',
  },
  {
    key: 'cutoff',
    label: 'CUTOFF',
    zh: 'Stop the performance',
    response: 'Pause Audio, Save Session',
    color: '#fb7185',
  },
  {
    key: 'style_switch',
    label: 'STYLE SWITCH',
    zh: 'Change timbre preset',
    response: 'Switch style preset',
    color: '#f97316',
  },
  {
    key: 'tempoDown',
    label: 'TEMPO DOWN',
    zh: 'Slow down tempo',
    response: 'BPM -6',
    color: '#a78bfa',
  },
  {
    key: 'left_wrist_strike',
    label: 'LEFT WRIST STRIKE',
    zh: 'Left wrist strike',
    response: 'Trigger left-hand beat cue',
    color: '#38bdf8',
  },
  {
    key: 'right_wrist_strike',
    label: 'RIGHT WRIST STRIKE',
    zh: 'Right wrist strike',
    response: 'Trigger right-hand downbeat cue',
    color: '#f4c76b',
  },
  {
    key: 'bilateral_strike',
    label: 'BILATERAL STRIKE',
    zh: 'Bilateral accent',
    response: 'Trigger synchronized accent',
    color: '#22c55e',
  },
]

export const assetSlots = [
  {
    title: 'Main roadshow video',
    path: '/media/roadshow-demo.mp4',
    type: 'video',
    note: '建议录制 20-40 秒横屏视频：同学双手指挥，屏幕音乐参数同步变化。',
  },
  {
    title: 'Camera recognition capture',
    path: '/media/live-camera-demo.mp4',
    type: 'video',
    note: '建议录制带手部关键点叠加的屏幕片段，替换实时舞台中的占位画面。',
  },
  {
    title: 'Micro:bit wrist photo',
    path: '/media/microbit-wrist.jpg',
    type: 'image',
    note: '建议拍摄左右手佩戴 Micro:bit 或固定在手腕上的清晰照片。',
  },
  {
    title: 'Team or setup photo',
    path: '/media/team-roadshow.jpg',
    type: 'image',
    note: '建议拍摄答辩现场、设备连接或小组调试照片，用于项目介绍页。',
  },
  {
    title: 'Guest experience recording',
    path: '/media/guest-experience-demo.mp4',
    type: 'video',
    note: '建议录制路人体验片段：体验者挥手、前端显示轨迹、Sonic Pi 音乐参数同步变化。',
  },
  {
    title: 'Full setup wide photo',
    path: '/media/stage-setup-wide.jpg',
    type: 'image',
    note: '建议拍摄完整设备布置：电脑、树莓派、摄像头、Micro:bit、音响或 LED 装置同框。',
  },
]

export const reservedInterfaceSlots = [
  {
    title: 'Raspberry Pi camera live stream',
    field: 'sensors_live.camera.stream_url',
    fallback: 'VITE_CAMERA_STREAM_URL',
    note: '预留给树莓派摄像头实时画面，不是电脑本地摄像头；推荐 MJPEG 图片流或可直接访问的视频流 URL。',
  },
  {
    title: 'Single camera frame',
    field: 'sensors_live.camera.frame_url',
    fallback: 'VITE_CAMERA_FRAME_URL',
    note: '如果暂时没有连续视频流，可以先提供不断更新的单帧图片地址。',
  },
  {
    title: 'Hand landmarks',
    field: 'sensors_live.camera.hands[].landmarks_normalized',
    fallback: 'image_landmarks / landmarks',
    note: '预留 21 个手部关键点，坐标可为 0-1 归一化值，也可为像素坐标。',
  },
  {
    title: 'Gesture control event',
    field: 'pi_status.runtime.last_control_event.payload.event',
    fallback: 'music_state.current_gesture',
    note: '预留真实手势控制音乐的事件入口，前端会优先显示后端最新控制事件。',
  },
]

export const experienceScenarios = [
  {
    gesture: 'downbeat',
    label: 'Downbeat',
    subtitle: 'Right-hand beat cue',
    effect: 'Accent pulse + tempo lock',
    bpmOffset: 0,
    volume: 82,
    energy: 78,
    color: '#38bdf8',
  },
  {
    gesture: 'crescendo',
    label: 'Crescendo',
    subtitle: 'Build intensity',
    effect: 'Volume and energy rise',
    bpmOffset: 2,
    volume: 92,
    energy: 90,
    color: '#f4c76b',
  },
  {
    gesture: 'tempo_up',
    label: 'Tempo Up',
    subtitle: 'Accelerate motion',
    effect: 'BPM increases',
    bpmOffset: 12,
    volume: 78,
    energy: 84,
    color: '#22c55e',
  },
  {
    gesture: 'cutoff',
    label: 'Cutoff',
    subtitle: 'Stop gesture',
    effect: 'Performance pauses',
    bpmOffset: -4,
    volume: 42,
    energy: 28,
    color: '#fb7185',
  },
]

export const flowSteps = [
  { name: 'Camera', detail: 'Hand landmarks / trajectories', layer: 'Sensing' },
  { name: 'Micro:bit L/R', detail: '3-axis acceleration / peaks', layer: 'Sensing' },
  { name: 'Raspberry Pi 5', detail: 'TCP JSON Lines / edge processing', layer: 'Edge' },
  { name: 'Feature Engine', detail: 'Speed / angle / time window', layer: 'AI' },
  { name: 'Gesture Event Engine', detail: 'Control events / confidence', layer: 'AI' },
  { name: 'Music Mapping', detail: 'BPM / volume / style', layer: 'Logic' },
  { name: 'Audio + LED', detail: 'Browser audio / lighting feedback', layer: 'Output' },
  { name: 'Database', detail: 'Raw data / predictions / actions', layer: 'Data' },
]

export const historicalRows = [
  {
    time: '20:16:31',
    source: 'Camera + IMU',
    gesture: 'Crescendo',
    confidence: '94%',
    response: 'Volume 58% -> 72%',
    latency: '84 ms',
  },
  {
    time: '20:16:28',
    source: 'Camera',
    gesture: 'Downbeat',
    confidence: '91%',
    response: 'Trigger Beat',
    latency: '79 ms',
  },
  {
    time: '20:16:22',
    source: 'IMU',
    gesture: 'Tempo Up',
    confidence: '88%',
    response: 'BPM 102 -> 108',
    latency: '96 ms',
  },
  {
    time: '20:16:15',
    source: 'Camera + IMU',
    gesture: 'Cutoff',
    confidence: '90%',
    response: 'Audio Paused',
    latency: '82 ms',
  },
]

export const analyticsSeries = Array.from({ length: 16 }, (_, index) => {
  const phase = index / 2
  return {
    tick: `${index * 5}s`,
    confidence: Math.round(84 + Math.sin(phase) * 8 + index * 0.5),
    latency: Math.round(92 - Math.cos(phase) * 9),
    bpm: Math.round(98 + Math.sin(phase / 1.4) * 12 + index * 0.8),
    volume: Math.round(58 + Math.sin(phase / 1.1) * 18),
    acceleration: Number((1.2 + Math.abs(Math.sin(phase)) * 1.4).toFixed(2)),
  }
})

export const gestureDistribution = [
  { name: 'Downbeat', value: 32, color: '#38bdf8' },
  { name: 'Crescendo', value: 21, color: '#f4c76b' },
  { name: 'Tempo Up', value: 16, color: '#22c55e' },
  { name: 'Tempo Down', value: 12, color: '#8b5cf6' },
  { name: 'Cutoff', value: 9, color: '#fb7185' },
  { name: 'Others', value: 10, color: '#94a3b8' },
]

export const trainingSteps = [
  { label: 'Camera Position', done: true },
  { label: 'Left Hand Range', done: true },
  { label: 'Right Hand Range', done: true },
  { label: 'IMU Zero Point', done: true },
  { label: 'Gesture Baseline', done: false },
]

export const validationCards = [
  {
    title: 'AI Recognition Process',
    claim: 'The system makes the recognition process visible by combining hand landmarks, time-window features, and acceleration peaks.',
    evidence: 'Confidence scores, event payloads, inference logs, and live feature panels show how the Pi-side decision is formed.',
    demo: 'During wrist strikes and downbeat gestures, watch confidence, event type, BPM, and volume update together.',
  },
  {
    title: 'Sensor Fusion Value',
    claim: 'The camera captures spatial movement while Micro:bit devices capture fast drops and intensity peaks, so the two inputs complement each other.',
    evidence: 'Right-hand downbeats can be reinforced by IMU peaks, while left-hand height maps naturally to volume and energy.',
    demo: 'During fast movements or partial occlusion, compare the camera stream and IMU values for a stable response.',
  },
  {
    title: 'Real-time Performance',
    claim: 'Pi-side event detection and REST polling keep interaction latency within the range needed for a live demonstration.',
    evidence: 'The live stage continuously displays FPS, response latency, BPM, and music parameter changes.',
    demo: 'Perform one downbeat and observe whether the visual pulse, BPM, and volume feedback stay synchronized.',
  },
  {
    title: 'Data Loop',
    claim: 'The system demonstrates real-time control while preserving raw sensor data, AI predictions, and executed actions.',
    evidence: 'The analytics view shows recognition count, average confidence, latency, gesture distribution, and event records.',
    demo: 'After a performance, store the session and replay the key interaction events.',
  },
  {
    title: 'Performance Readiness',
    claim: 'Calibration, training samples, and prepared media help the audience see both the designed experience and the live interaction.',
    evidence: 'The calibration view tracks camera position, IMU zero point, gesture baseline, and related checks.',
    demo: 'Start with the recorded overview, then move into the live performance when the conductor is ready.',
  },
]

const predictionSets = [
  [
    { label: 'Crescendo', value: 94 },
    { label: 'Tempo Up', value: 4 },
    { label: 'Idle', value: 2 },
  ],
  [
    { label: 'Downbeat', value: 91 },
    { label: 'Crescendo', value: 6 },
    { label: 'Cutoff', value: 3 },
  ],
  [
    { label: 'Tempo Up', value: 88 },
    { label: 'Downbeat', value: 8 },
    { label: 'Idle', value: 4 },
  ],
  [
    { label: 'Cutoff', value: 90 },
    { label: 'Idle', value: 7 },
    { label: 'Tempo Down', value: 3 },
  ],
]

export function createConductorFrame(tick = 0) {
  const gesture = gestureCatalog[tick % gestureCatalog.length]
  const phase = tick / 3
  const bpm = Math.round(104 + Math.sin(phase) * 10 + (gesture.key === 'tempoUp' ? 8 : 0))
  const volume = Math.round(58 + Math.sin(phase / 1.5) * 12 + (gesture.key === 'crescendo' ? 14 : 0))
  const confidence = predictionSets[tick % predictionSets.length][0].value
  const latency = Math.round(84 + Math.sin(phase * 1.4) * 12)

  return {
    timestamp: new Date().toISOString(),
    connection: {
      camera: 'Connected',
      hands: 'Two Hands Detected',
      tracking: 'Stable',
      fps: 30,
      latency,
      piGateway: 'Pi Preview',
      piGatewayConnected: false,
      piGatewayRunning: false,
      piGatewayHost: '0.0.0.0:9000',
      piLastMessage: 'Preview fused frame',
      piMessageCounts: {
        fused_frame: tick + 12,
        control_event: Math.floor(tick / 3),
        status: Math.floor(tick / 5) + 1,
      },
      piLastError: null,
    },
    camera: {
      source: 'mock',
      frameId: null,
      width: 640,
      height: 480,
      fps: 30,
      leftHandY: Number((0.62 + Math.sin(phase) * 0.16).toFixed(2)),
      rightHandX: Number((0.58 + Math.cos(phase / 1.2) * 0.18).toFixed(2)),
      handDistance: Number((0.48 + Math.sin(phase / 1.7) * 0.11).toFixed(2)),
      movementSpeed: Number((1.2 + Math.abs(Math.cos(phase)) * 0.9).toFixed(2)),
      trajectoryAngle: Math.round(72 + Math.sin(phase) * 18),
      hands: [],
      streamUrl: '',
      frameUrl: '',
      hasLiveVideo: false,
      hasLiveLandmarks: false,
      raw: {},
    },
    microbit: {
      left: {
        id: 'Device A',
        battery: 86,
        signal: 'Excellent',
        motion: gesture.key === 'crescendo' ? 'Rising' : 'Stable',
        x: Number((0.12 + Math.sin(phase) * 0.24).toFixed(2)),
        y: Number((1.25 + Math.abs(Math.sin(phase)) * 0.58).toFixed(2)),
        z: Number((0.3 + Math.cos(phase) * 0.22).toFixed(2)),
      },
      right: {
        id: 'Device B',
        battery: 81,
        signal: 'Good',
        motion: gesture.key === 'downbeat' ? 'Downbeat' : 'Expressive',
        x: Number((0.76 + Math.sin(phase / 1.3) * 0.32).toFixed(2)),
        y: Number((1.72 + Math.abs(Math.cos(phase)) * 0.62).toFixed(2)),
        z: Number((0.58 + Math.sin(phase / 1.8) * 0.2).toFixed(2)),
      },
    },
    prediction: {
      gesture: gesture.key,
      label: gesture.label,
      zh: gesture.zh,
      confidence,
      response: gesture.response,
      top3: predictionSets[tick % predictionSets.length],
    },
    actuation: {
      led: {
        pattern: gesture.key === 'cutoff' ? 'red_cutoff_flash' : 'beat_pulse',
        brightness: gesture.key === 'crescendo' ? 0.85 : 0.55,
        durationMs: 120,
      },
      databaseSaved: tick > 0,
    },
    music: {
      title: 'Ode to Joy Conductor Mix',
      bpm,
      volume: Math.max(0, Math.min(100, volume)),
      energy: Math.round(48 + Math.abs(Math.sin(phase)) * 36),
      density: Math.round(38 + Math.abs(Math.cos(phase / 1.4)) * 24),
      key: 'C Major',
      style: tick % 2 === 0 ? 'Cinematic' : 'Classical',
      progress: Math.round((tick % 24) * (100 / 24)),
      elapsedSeconds: Math.round((tick % 24) * 2.2),
      durationSeconds: 53,
      performanceElapsedSeconds: Math.round(tick * 1.8),
      uiReceivedAt: Date.now() / 1000,
      engine: 'Sonic Pi',
      section: 'Main',
      lastBar: Math.floor(tick / 4) + 1,
      lastBeat: (tick % 4) + 1,
      beatStrength: tick % 4 === 0 ? 100 : 45,
      sonicPiConnected: false,
      layers: { melody: true, harmony: true, bass: true, drums: true },
      trackId: 'shape_of_you',
      trackIndex: 0,
      trackCount: 2,
    },
    coordinate: {
      enabled: false,
      fps: 0,
      swapHands: false,
      hands: {
        left: { present: false, label: 'unknown', openness: 0, y: 0.5, vy: 0, zone: null },
        right: { present: false, label: 'unknown', openness: 0, y: 0.5, vy: 0, zone: null },
      },
      zones: {
        bands: [[0.03, 0.22], [0.28, 0.47], [0.53, 0.72], [0.78, 0.97]],
        layers: ['melody', 'harmony', 'bass', 'drums'],
      },
      progress: {},
      lastActions: [],
      updatedAt: 0,
    },
  }
}

export function makeInferenceLog(frame) {
  const time = new Date(frame.timestamp).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  return [
    `${time}.180  Two-hand tracking started`,
    `${time}.420  Acceleration peak detected`,
    `${time}.690  Feature vector generated`,
    `${time}.774  Prediction: ${frame.prediction.label}`,
    `${time}.790  ${frame.prediction.response}`,
  ]
}
