export const navItems = [
  { id: 'hero', label: '首页', short: 'Hero' },
  { id: 'live-stage', label: '实时舞台', short: 'Live' },
  { id: 'ai-flow', label: 'AI 决策', short: 'AI' },
  { id: 'validation', label: '关键验证', short: 'Proof' },
  { id: 'analytics', label: '历史分析', short: 'Data' },
  { id: 'architecture', label: '系统架构', short: 'Arch' },
  { id: 'training', label: '校准训练', short: 'Train' },
  { id: 'about', label: '项目介绍', short: 'About' },
]

export const gestureCatalog = [
  {
    key: 'crescendo',
    label: 'CRESCENDO',
    zh: '渐强',
    response: 'Volume +14%, Energy +28%',
    color: '#f4c76b',
  },
  {
    key: 'downbeat',
    label: 'DOWNBEAT',
    zh: '强拍 / 落拍',
    response: 'Trigger Beat, BPM Sync',
    color: '#38bdf8',
  },
  {
    key: 'tempoUp',
    label: 'TEMPO UP',
    zh: '加快节奏',
    response: 'BPM +6',
    color: '#22c55e',
  },
  {
    key: 'cutoff',
    label: 'CUTOFF',
    zh: '收拍 / 停止',
    response: 'Pause Audio, Save Session',
    color: '#fb7185',
  },
]

export const assetSlots = [
  {
    title: '路演主视频',
    path: '/media/roadshow-demo.mp4',
    note: '建议录制 20-40 秒横屏视频：同学双手指挥，屏幕音乐参数同步变化。',
  },
  {
    title: '摄像头识别画面',
    path: '/media/live-camera-demo.mp4',
    note: '建议录制带手部关键点叠加的屏幕片段，替换实时舞台中的占位画面。',
  },
  {
    title: 'Micro:bit 佩戴照片',
    path: '/media/microbit-wrist.jpg',
    note: '建议拍摄左右手佩戴 Micro:bit 或固定在手腕上的清晰照片。',
  },
  {
    title: '团队/现场照片',
    path: '/media/team-roadshow.jpg',
    note: '建议拍摄答辩现场、设备连接或小组调试照片，用于项目介绍页。',
  },
]

export const flowSteps = [
  { name: 'Camera', detail: '双手关键点 / 轨迹', layer: '感知层' },
  { name: 'Micro:bit L/R', detail: '三轴加速度 / 峰值', layer: '感知层' },
  { name: 'Raspberry Pi 5', detail: 'WebSocket / Serial', layer: '边缘层' },
  { name: 'Feature Engine', detail: '速度 / 角度 / 时窗', layer: 'AI 层' },
  { name: 'Gesture Model', detail: '8 类指挥意图', layer: 'AI 层' },
  { name: 'Music Mapping', detail: 'BPM / 音量 / 风格', layer: '业务层' },
  { name: 'Audio + LED', detail: '浏览器音频 / 灯光反馈', layer: '执行层' },
  { name: 'Database', detail: '原始数据 / 预测 / 动作', layer: '数据层' },
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
    title: 'AI 识别依据',
    claim: '不是单一阈值判断，而是将手部轨迹、速度、角度、动作时窗和加速度峰值组合成特征向量。',
    evidence: 'Top-3 预测、置信度、推断日志和特征面板会同步展示模型判断过程。',
    demo: '演示渐强和强拍时，观察置信度与 Top-3 结果随动作变化。',
  },
  {
    title: '多传感器融合价值',
    claim: 'Camera 擅长空间轨迹，Micro:bit 擅长捕捉快速下落和力度峰值，两者互补。',
    evidence: '右手落拍可由 IMU 峰值增强识别，左手高度可由摄像头映射到音量和能量。',
    demo: '遮挡或快速动作时，对比 Camera 与 IMU 数据仍能形成稳定响应。',
  },
  {
    title: '实时性验证',
    claim: '本地推断和 WebSocket 数据通道让交互延迟控制在路演可感知范围内。',
    evidence: '实时舞台持续显示 FPS、响应延迟、BPM 和音乐参数变化。',
    demo: '现场做一次落拍动作，观察视觉冲击波、BPM 与音量反馈是否同步。',
  },
  {
    title: '数据闭环',
    claim: '系统不仅演示实时效果，也保留原始传感器数据、AI 预测和执行动作。',
    evidence: '历史分析页展示识别次数、平均置信度、延迟、手势分布和事件表。',
    demo: '完成一次演示后，可把记录写入数据库并回放关键事件。',
  },
  {
    title: '演示稳定性',
    claim: '校准、训练采样和预留视频位能降低现场硬件波动对路演结果的影响。',
    evidence: '校准页展示 Camera Position、IMU Zero Point、Gesture Baseline 等检查项。',
    demo: '真实硬件可用时走实时模式，信号不稳时可切换预录素材或 mock 数据。',
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
    },
    camera: {
      leftHandY: Number((0.62 + Math.sin(phase) * 0.16).toFixed(2)),
      rightHandX: Number((0.58 + Math.cos(phase / 1.2) * 0.18).toFixed(2)),
      handDistance: Number((0.48 + Math.sin(phase / 1.7) * 0.11).toFixed(2)),
      movementSpeed: Number((1.2 + Math.abs(Math.cos(phase)) * 0.9).toFixed(2)),
      trajectoryAngle: Math.round(72 + Math.sin(phase) * 18),
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
    music: {
      title: 'Demo Symphony No.1',
      bpm,
      volume: Math.max(0, Math.min(100, volume)),
      energy: Math.round(48 + Math.abs(Math.sin(phase)) * 36),
      density: Math.round(38 + Math.abs(Math.cos(phase / 1.4)) * 24),
      key: 'C Major',
      style: tick % 2 === 0 ? 'Cinematic' : 'Classical',
      progress: Math.round(38 + Math.sin(phase / 2) * 15),
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
