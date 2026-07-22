import { useEffect, useState } from 'react'
import { createConductorFrame, gestureCatalog, makeInferenceLog } from '../data/conductorData'

const BACKEND_REST_DEFAULT = 'http://localhost:5000'

const gestureResponses = {
  idle: 'Maintain current playback state',
  downbeat: 'Start playback, trigger beat',
  crescendo: 'Increase volume',
  decrescendo: 'Decrease volume',
  cutoff: 'Pause playback',
  style_switch: 'Switch style preset',
  tempo_up: 'Increase BPM',
  tempo_down: 'Decrease BPM',
  left_wrist_strike: 'Trigger left-hand beat cue',
  right_wrist_strike: 'Trigger right-hand downbeat cue',
  bilateral_strike: 'Trigger synchronized accent',
  gesture_start: 'Enter active gesture window',
  gesture_end: 'Close gesture window',
  stop: 'Pause playback',
  resume: 'Resume playback',
}

const gestureSubtitles = {
  idle: 'Hold state',
  downbeat: 'Primary beat',
  crescendo: 'Build intensity',
  decrescendo: 'Reduce intensity',
  cutoff: 'Stop the performance',
  style_switch: 'Change timbre preset',
  tempo_up: 'Accelerate tempo',
  tempo_down: 'Slow down tempo',
  left_wrist_strike: 'Left wrist strike',
  right_wrist_strike: 'Right wrist strike',
  bilateral_strike: 'Bilateral accent',
  gesture_start: 'Gesture started',
  gesture_end: 'Gesture ended',
  stop: 'Stop playback',
  resume: 'Resume playback',
}

function toCamelGestureKey(gesture = 'idle') {
  return gesture.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())
}

function toGestureLabel(gesture = 'idle') {
  return gesture.replaceAll('_', ' ').toUpperCase()
}

function toTitleCase(value = '') {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function toPercent(value, fallback = 0) {
  if (typeof value !== 'number' || Number.isNaN(value)) return fallback
  return Math.round(value <= 1 ? value * 100 : value)
}

function toNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value))
}

function normalizeAcceleration(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0
  const normalized = Math.abs(value) > 16 ? value / 1000 : value
  return Number(normalized.toFixed(2))
}

function normalizeMilligravity(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0
  return Number((value / 1000).toFixed(2))
}

const axisIndex = { x: 0, y: 1, z: 2 }

function readAccelerationArray(source = {}, field, axis, normalize) {
  const values = source[field]
  const value = Array.isArray(values) ? values[axisIndex[axis]] : undefined
  if (typeof value !== 'number' || Number.isNaN(value)) return null
  return normalize(value)
}

function readAccelerationField(source = {}, axis = 'x') {
  const mgKey = `a${axis}_mg`
  const accKey = `acc_${axis}`
  const directKey = axis

  if (typeof source[mgKey] === 'number') return normalizeMilligravity(source[mgKey])
  if (typeof source[accKey] === 'number') return normalizeAcceleration(source[accKey])
  if (typeof source[directKey] === 'number') return normalizeAcceleration(source[directKey])
  return null
}

function readAcceleration(sample = {}, axis = 'x') {
  const sources = [
    sample,
    sample.raw_interpolated,
    sample.instant_features,
  ].filter(Boolean)

  for (const source of sources) {
    const arrayMg = readAccelerationArray(source, 'acceleration_mg', axis, normalizeMilligravity)
    if (arrayMg !== null) return arrayMg

    const arrayG = readAccelerationArray(source, 'acceleration_g', axis, normalizeAcceleration)
    if (arrayG !== null) return arrayG

    const fieldValue = readAccelerationField(source, axis)
    if (fieldValue !== null) return fieldValue
  }

  return 0
}

function formatPiGateway(gateway = {}) {
  if (!gateway.enabled) return 'Disabled'
  if (gateway.connected) return 'Pi Connected'
  if (gateway.running) return `Listening ${gateway.listen_port || 9000}`
  return 'Gateway Pending'
}

function formatPiLastMessage(runtime = {}) {
  if (!runtime.last_message_type) return 'No Pi message yet'
  return toTitleCase(String(runtime.last_message_type))
}

function getLastControlPayload(runtime = {}) {
  const payload = runtime.last_control_event?.payload
  return payload && typeof payload === 'object' ? payload : {}
}

function getMeaningfulGesture(value) {
  if (typeof value !== 'string') return null
  const gesture = value.trim()
  if (!gesture || gesture === 'idle') return null
  return gesture
}

function selectCurrentGesture({ prediction = {}, music = {}, controlPayload = {} }) {
  const eventGesture = getMeaningfulGesture(controlPayload.event?.type)
  const musicGesture = getMeaningfulGesture(music.current_gesture)
  const predictionGesture = getMeaningfulGesture(prediction.gesture)

  return musicGesture || eventGesture || predictionGesture || prediction.gesture || music.current_gesture || 'idle'
}

function readControlConfidence(controlPayload = {}) {
  const confidence = Number(controlPayload.event?.confidence)
  return Number.isFinite(confidence) ? confidence : null
}

function topPredictionsFromAllProbs(allProbs = {}, fallbackGesture = 'idle', fallbackConfidence = 0) {
  const entries = Object.entries(allProbs)

  if (!entries.length) {
    const fallback = [
      {
        label: toTitleCase(fallbackGesture),
        value: fallbackConfidence,
      },
    ]

    if (fallbackGesture !== 'idle') {
      fallback.push({
        label: 'Idle',
        value: Math.max(0, 100 - fallbackConfidence),
      })
    }

    return fallback.slice(0, 3)
  }

  return entries
    .map(([label, value]) => ({
      label: toTitleCase(label),
      value: toPercent(Number(value), 0),
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 3)
}

function normalizeRestFrame({ status = {}, prediction = {}, sensors = {}, music = {}, piStatus = {} }, tick = 0) {
  const base = createConductorFrame(tick)
  const leftSensor = sensors.microbit_left || {}
  const rightSensor = sensors.microbit_right || {}
  const volume = toPercent(Number(music.volume), base.music.volume)
  const handCount = Number(sensors.hand_count || 0)
  const gateway = piStatus.gateway || status.pi_gateway || {}
  const sonicPi = status.sonic_pi || {}
  const runtime = piStatus.runtime || {}
  const controlPayload = getLastControlPayload(runtime)
  const gesture = selectCurrentGesture({ prediction, music, controlPayload })
  const gestureKey = toCamelGestureKey(gesture)
  const catalogMatch = gestureCatalog.find((item) => item.key === gestureKey || item.key === gesture)
  const predictionConfidence = Number(prediction.confidence)
  const eventConfidence = readControlConfidence(controlPayload)
  const confidence = Number.isFinite(predictionConfidence) && predictionConfidence > 0
    ? toPercent(predictionConfidence, 0)
    : toPercent(eventConfidence ?? predictionConfidence, 0)
  const useEventTop3 = Boolean(getMeaningfulGesture(gesture)) && gesture !== prediction.gesture

  return {
    ...base,
    timestamp: prediction.timestamp
      ? new Date(Number(prediction.timestamp) * 1000).toISOString()
      : new Date().toISOString(),
    connection: {
      camera: status.camera_connected ? 'Connected' : 'Waiting',
      hands: sensors.hand_detected ? `${handCount || 1} Hand${handCount === 1 ? '' : 's'} Detected` : 'No Hands Detected',
      tracking: sensors.hand_detected ? 'Stable' : 'Standby',
      fps: base.connection.fps,
      latency: Number(prediction.latency_ms || base.connection.latency),
      model: status.model_loaded ? 'Model Loaded' : 'Model Pending',
      backend: status.status === 'ok' ? 'REST Online' : 'REST Pending',
      uptime: Number(status.uptime_seconds || 0),
      piGateway: formatPiGateway(gateway),
      piGatewayConnected: Boolean(gateway.connected),
      piGatewayRunning: Boolean(gateway.running),
      piGatewayHost: `${gateway.listen_host || '0.0.0.0'}:${gateway.listen_port || 9000}`,
      piLastMessage: formatPiLastMessage(runtime),
      piMessageCounts: runtime.message_counts || {},
      piLastError: gateway.last_error || null,
    },
    microbit: {
      left: {
        ...base.microbit.left,
        id: 'Micro:bit L',
        signal: status.microbit_left ? 'Online' : 'Waiting',
        motion: status.microbit_left ? 'Live sensor' : 'No live packet',
        x: readAcceleration(leftSensor, 'x'),
        y: readAcceleration(leftSensor, 'y'),
        z: readAcceleration(leftSensor, 'z'),
      },
      right: {
        ...base.microbit.right,
        id: 'Micro:bit R',
        signal: status.microbit_right ? 'Online' : 'Waiting',
        motion: status.microbit_right ? 'Live sensor' : 'No live packet',
        x: readAcceleration(rightSensor, 'x'),
        y: readAcceleration(rightSensor, 'y'),
        z: readAcceleration(rightSensor, 'z'),
      },
    },
    prediction: {
      gesture,
      label: catalogMatch?.label || toGestureLabel(gesture),
      zh: catalogMatch?.zh || gestureSubtitles[gesture] || toTitleCase(gesture),
      confidence,
      response: catalogMatch?.response || gestureResponses[gesture] || 'Update live state',
      top3: topPredictionsFromAllProbs(useEventTop3 ? {} : prediction.all_probs, gesture, confidence),
    },
    music: {
      ...base.music,
      title: music.title || base.music.title,
      key: music.key || base.music.key,
      bpm: Number(music.bpm || base.music.bpm),
      volume,
      energy: toPercent(
        Number(music.energy),
        Math.round(Math.max(20, Math.min(100, volume * 0.8 + confidence * 0.2))),
      ),
      density: music.playing ? base.music.density : 20,
      style: music.style ? toTitleCase(String(music.style)) : base.music.style,
      progress: clamp(toNumber(music.progress, music.playing ? base.music.progress : 0), 0, 100),
      elapsedSeconds: toNumber(music.elapsed_seconds, base.music.elapsedSeconds),
      durationSeconds: toNumber(music.duration_seconds, base.music.durationSeconds),
      performanceElapsedSeconds: toNumber(
        music.performance_elapsed_seconds,
        base.music.performanceElapsedSeconds,
      ),
      playing: Boolean(music.playing),
      engine: music.engine ? toTitleCase(String(music.engine)) : 'Sonic Pi',
      section: music.section ? toTitleCase(String(music.section)) : base.music.section,
      lastBar: Number.isFinite(Number(music.last_bar)) ? Number(music.last_bar) : base.music.lastBar,
      lastBeat: Number.isFinite(Number(music.last_beat)) ? Number(music.last_beat) : base.music.lastBeat,
      beatStrength: toPercent(Number(music.beat_strength), base.music.beatStrength),
      sonicPiConnected: Boolean(music.sonic_pi_connected || sonicPi.connected),
    },
  }
}

function normalizeRemoteFrame(payload) {
  return {
    ...createConductorFrame(0),
    ...payload,
    timestamp: payload.timestamp || new Date().toISOString(),
  }
}

export function useConductorFeed(options = {}) {
  const wsUrl = options.wsUrl || import.meta.env.VITE_CONDUCTOR_WS_URL
  const restBaseUrl = options.restBaseUrl || import.meta.env.VITE_BACKEND_BASE_URL || BACKEND_REST_DEFAULT
  const [tick, setTick] = useState(0)
  const [frame, setFrame] = useState(() => createConductorFrame(0))
  const [connectionState, setConnectionState] = useState(wsUrl ? 'connecting websocket' : 'connecting rest')
  const sendSonicPiTransport = async (action) => {
    const response = await fetch(`${restBaseUrl}/api/sonic-pi/transport`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    if (!response.ok) throw new Error(`Sonic Pi transport returned ${response.status}`)
    return response.json()
  }

  useEffect(() => {
    let restTimer
    let mockTimer
    let socket
    let cancelled = false
    let feedTick = 0
    let mockStarted = false
    let restStarted = false

    const startMockFeed = () => {
      if (mockStarted || cancelled) return
      mockStarted = true
      setConnectionState('mock fallback')
      if (restTimer) window.clearInterval(restTimer)
      mockTimer = window.setInterval(() => {
        feedTick += 1
        setTick(feedTick)
        setFrame(createConductorFrame(feedTick))
      }, 1800)
    }

    const fetchBackendState = async () => {
      const fetchJson = async (path) => {
        const response = await fetch(`${restBaseUrl}${path}`)
        if (!response.ok) throw new Error(`${path} returned ${response.status}`)
        return response.json()
      }
      const fetchOptionalJson = async (path, fallback) => {
        try {
          return await fetchJson(path)
        } catch {
          return fallback
        }
      }

      const [status, prediction, sensors, music] = await Promise.all(
        ['/api/status', '/api/gesture/current', '/api/sensors/live', '/api/music/state'].map(fetchJson),
      )
      const piStatus = await fetchOptionalJson('/api/pi/status', {
        gateway: status.pi_gateway || {},
        runtime: {},
      })
      feedTick += 1
      setTick(feedTick)
      setFrame(normalizeRestFrame({ status, prediction, sensors, music, piStatus }, feedTick))
      setConnectionState('rest polling')
    }

    const startRestPolling = () => {
      if (restStarted || cancelled) return
      restStarted = true
      fetchBackendState()
        .then(() => {
          if (cancelled) return
          restTimer = window.setInterval(() => {
            fetchBackendState().catch(() => {
              if (!cancelled) startMockFeed()
            })
          }, 750)
        })
        .catch(() => {
          if (!cancelled) startMockFeed()
        })
    }

    if (wsUrl) {
      try {
        socket = new WebSocket(wsUrl)
        socket.onopen = () => !cancelled && setConnectionState('live websocket')
        socket.onmessage = (event) => {
          if (cancelled) return
          try {
            feedTick += 1
            setTick(feedTick)
            setFrame(normalizeRemoteFrame(JSON.parse(event.data)))
          } catch {
            setConnectionState('invalid payload')
          }
        }
        socket.onerror = () => !cancelled && startRestPolling()
        socket.onclose = () => !cancelled && startRestPolling()
      } catch {
        startRestPolling()
      }
    } else {
      startRestPolling()
    }

    return () => {
      cancelled = true
      if (restTimer) window.clearInterval(restTimer)
      if (mockTimer) window.clearInterval(mockTimer)
      if (socket && socket.readyState < 2) socket.close()
    }
  }, [wsUrl, restBaseUrl])

  return {
    frame,
    tick,
    connectionState,
    logs: makeInferenceLog(frame),
    sendSonicPiTransport,
  }
}
