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

function normalizeAcceleration(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0
  const normalized = Math.abs(value) > 16 ? value / 1000 : value
  return Number(normalized.toFixed(2))
}

function normalizeMilligravity(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0
  return Number((value / 1000).toFixed(2))
}

function readAcceleration(sample = {}, axis = 'x') {
  const mgKey = `a${axis}_mg`
  const accKey = `acc_${axis}`
  const directKey = axis

  if (typeof sample[mgKey] === 'number') return normalizeMilligravity(sample[mgKey])
  if (typeof sample[accKey] === 'number') return normalizeAcceleration(sample[accKey])
  if (typeof sample[directKey] === 'number') return normalizeAcceleration(sample[directKey])
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

function topPredictionsFromAllProbs(allProbs = {}, fallbackGesture = 'idle', fallbackConfidence = 0) {
  const entries = Object.entries(allProbs)
  const source = entries.length ? entries : [[fallbackGesture, fallbackConfidence / 100]]

  return source
    .map(([label, value]) => ({
      label: toTitleCase(label),
      value: toPercent(Number(value), 0),
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 3)
}

function normalizeRestFrame({ status = {}, prediction = {}, sensors = {}, music = {}, piStatus = {} }, tick = 0) {
  const base = createConductorFrame(tick)
  const gesture = prediction.gesture || music.current_gesture || 'idle'
  const gestureKey = toCamelGestureKey(gesture)
  const catalogMatch = gestureCatalog.find((item) => item.key === gestureKey || item.key === gesture)
  const confidence = toPercent(Number(prediction.confidence), base.prediction.confidence)
  const leftSensor = sensors.microbit_left || {}
  const rightSensor = sensors.microbit_right || {}
  const volume = toPercent(Number(music.volume), base.music.volume)
  const handCount = Number(sensors.hand_count || 0)
  const gateway = piStatus.gateway || status.pi_gateway || {}
  const runtime = piStatus.runtime || {}

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
      top3: topPredictionsFromAllProbs(prediction.all_probs, gesture, confidence),
    },
    music: {
      ...base.music,
      bpm: Number(music.bpm || base.music.bpm),
      volume,
      energy: Math.round(Math.max(20, Math.min(100, volume * 0.8 + confidence * 0.2))),
      density: music.playing ? base.music.density : 20,
      style: music.style ? toTitleCase(String(music.style)) : base.music.style,
      progress: music.playing ? base.music.progress : 0,
      playing: Boolean(music.playing),
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
  }
}
