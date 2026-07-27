import { useEffect, useRef, useState } from 'react'
import { createConductorFrame, describeCoordinateAction, makeInferenceLog } from '../data/conductorData'

const BACKEND_REST_DEFAULT = 'http://localhost:5000'
const REST_POLL_INTERVAL_MS = 250
const TRANSPORT_FETCH_TIMEOUT_MS = 1200
const CAMERA_STREAM_ENV = import.meta.env.VITE_CAMERA_STREAM_URL || ''
const CAMERA_FRAME_ENV = import.meta.env.VITE_CAMERA_FRAME_URL || ''
const PLAY_ACTIONS = new Set(['start', 'resume', 'play', 'reset', 'next', 'previous', 'prev'])
const PAUSE_ACTIONS = new Set(['pause', 'stop', 'cutoff'])
// A coordinate action stays "current" for this long after it fires.
const COORD_ACTION_FRESH_SECONDS = 12

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

function readString(...values) {
  return values.find((value) => typeof value === 'string' && value.trim()) || ''
}

function normalizeLandmarkPoint(point, index) {
  if (Array.isArray(point)) {
    const [x, y, z = 0] = point
    if (!Number.isFinite(Number(x)) || !Number.isFinite(Number(y))) return null
    return {
      id: index,
      x: Number(x),
      y: Number(y),
      z: Number.isFinite(Number(z)) ? Number(z) : 0,
    }
  }

  if (!point || typeof point !== 'object') return null
  const x = Number(point.x)
  const y = Number(point.y)
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null

  return {
    id: Number.isFinite(Number(point.id)) ? Number(point.id) : index,
    x,
    y,
    z: Number.isFinite(Number(point.z)) ? Number(point.z) : 0,
  }
}

function normalizeLandmarks(hand = {}) {
  const source =
    hand.landmarks_normalized ||
    hand.image_landmarks ||
    hand.landmarks ||
    hand.world_landmarks ||
    []

  if (!Array.isArray(source)) return []
  return source
    .map((point, index) => normalizeLandmarkPoint(point, index))
    .filter(Boolean)
}

function normalizeCameraHands(camera = {}) {
  const hands = Array.isArray(camera.hands) ? camera.hands : []
  return hands
    .map((hand, index) => {
      if (!hand || typeof hand !== 'object') return null
      const handedness = String(
        hand.hand ||
        hand.handedness ||
        hand.hand_label ||
        hand.hand_id ||
        `hand-${index}`,
      ).toLowerCase()
      const features = hand.features && typeof hand.features === 'object' ? hand.features : {}

      return {
        handId: String(hand.hand_id || hand.id || `${handedness}-${index}`),
        handedness,
        valid: hand.valid ?? hand.detection_valid ?? true,
        confidence: toPercent(Number(hand.confidence ?? hand.score ?? hand.handedness_score), 0),
        landmarks: normalizeLandmarks(hand),
        features,
      }
    })
    .filter(Boolean)
}

function readCameraMedia(camera = {}, sensors = {}) {
  const media = camera.media && typeof camera.media === 'object' ? camera.media : {}
  const streamUrl = readString(
    camera.stream_url,
    camera.streamUrl,
    camera.mjpeg_url,
    camera.mjpegUrl,
    camera.video_url,
    camera.videoUrl,
    media.stream_url,
    media.streamUrl,
    sensors.camera_stream_url,
    sensors.cameraStreamUrl,
    CAMERA_STREAM_ENV,
  )
  const frameUrl = readString(
    camera.frame_url,
    camera.frameUrl,
    camera.image_url,
    camera.imageUrl,
    media.frame_url,
    media.frameUrl,
    sensors.camera_frame_url,
    sensors.cameraFrameUrl,
    CAMERA_FRAME_ENV,
  )

  return { streamUrl, frameUrl }
}

// The Pi fusion pipeline serves an in-process MJPEG preview
// (hardware/fusion_pipeline/preview_server.py, config preview.port 8790)
// whenever pi-fusion runs, independently of the TCP downlink. Deriving the
// URL from the connected gateway client address keeps the Pi's hotspot IP
// out of the frontend; the backend-provided fields / VITE_CAMERA_STREAM_URL
// remain the fallback for the disconnected case (see readCameraMedia).
const PI_PREVIEW_PORT = 8790

function derivePiPreviewUrl(gateway = {}) {
  const raw = gateway.client_address
  const host = Array.isArray(raw) ? raw[0] : String(raw || '').split(':')[0]
  return host ? `http://${host}:${PI_PREVIEW_PORT}/stream` : ''
}

function vectorMagnitude(values) {
  if (!Array.isArray(values)) return 0
  return Math.sqrt(
    values.reduce((total, value) => {
      const number = Number(value)
      return Number.isFinite(number) ? total + number * number : total
    }, 0),
  )
}

function firstWristPoint(hand) {
  return hand?.landmarks?.find((point) => point.id === 0) || hand?.landmarks?.[0] || null
}

function deriveCameraMetrics(rawCamera = {}, baseCamera = {}, hands = []) {
  const cameraWidth = Number(rawCamera.width) || 640
  const cameraHeight = Number(rawCamera.height) || 480
  const normalizeAxis = (value, size) => {
    const number = Number(value)
    if (!Number.isFinite(number)) return null
    return number > 1 && size > 1 ? number / size : number
  }
  const leftHand = hands.find((hand) => hand.handedness.includes('left'))
  const rightHand = hands.find((hand) => hand.handedness.includes('right'))
  const leftWrist = firstWristPoint(leftHand)
  const rightWrist = firstWristPoint(rightHand)
  const leftWristX = normalizeAxis(leftWrist?.x, cameraWidth)
  const leftWristY = normalizeAxis(leftWrist?.y, cameraHeight)
  const rightWristX = normalizeAxis(rightWrist?.x, cameraWidth)
  const rightWristY = normalizeAxis(rightWrist?.y, cameraHeight)
  const leftVelocity = leftHand?.features?.wrist_velocity
  const rightVelocity = rightHand?.features?.wrist_velocity
  const dominantVelocity = vectorMagnitude(rightVelocity) ? rightVelocity : leftVelocity
  const motionSpeed = Math.max(vectorMagnitude(leftVelocity), vectorMagnitude(rightVelocity))
  const handDistance = leftWristX !== null && leftWristY !== null && rightWristX !== null && rightWristY !== null
    ? Math.sqrt((leftWristX - rightWristX) ** 2 + (leftWristY - rightWristY) ** 2)
    : baseCamera.handDistance
  const trajectoryAngle = Array.isArray(dominantVelocity) && dominantVelocity.length >= 2
    ? Math.round((Math.atan2(-Number(dominantVelocity[1]), Number(dominantVelocity[0])) * 180) / Math.PI)
    : baseCamera.trajectoryAngle

  return {
    leftHandY: Number((leftWristY ?? baseCamera.leftHandY).toFixed(2)),
    rightHandX: Number((rightWristX ?? baseCamera.rightHandX).toFixed(2)),
    handDistance: Number((handDistance ?? baseCamera.handDistance).toFixed(2)),
    movementSpeed: Number((motionSpeed || baseCamera.movementSpeed || 0).toFixed(2)),
    trajectoryAngle,
  }
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

function normalizeCoordinateHand(hand = {}) {
  return {
    present: Boolean(hand.present),
    label: typeof hand.label === 'string' ? hand.label : 'unknown',
    openness: clamp(toNumber(hand.openness, 0), 0, 1),
    y: clamp(toNumber(hand.y, 0.5), 0, 1),
    vy: clamp(toNumber(hand.vy, 0), -5, 5),
    zone: Number.isInteger(hand.zone) ? hand.zone : null,
  }
}

function normalizeCoordinateState(coordinate = {}) {
  const zones = coordinate.zones && typeof coordinate.zones === 'object' ? coordinate.zones : {}
  const hands = coordinate.hands && typeof coordinate.hands === 'object' ? coordinate.hands : {}
  return {
    enabled: Boolean(coordinate.enabled),
    fps: toNumber(coordinate.fps, 0),
    swapHands: Boolean(coordinate.swap_hands),
    hands: {
      left: normalizeCoordinateHand(hands.left),
      right: normalizeCoordinateHand(hands.right),
    },
    zones: {
      bands: Array.isArray(zones.bands) && zones.bands.length === 4
        ? zones.bands
        : [[0.03, 0.22], [0.28, 0.47], [0.53, 0.72], [0.78, 0.97]],
      layers: Array.isArray(zones.layers) && zones.layers.length === 4
        ? zones.layers
        : ['melody', 'harmony', 'bass', 'drums'],
    },
    progress: coordinate.progress && typeof coordinate.progress === 'object' ? coordinate.progress : {},
    lastActions: Array.isArray(coordinate.last_actions) ? coordinate.last_actions : [],
    updatedAt: toNumber(coordinate.updated_at, 0),
    anchor: coordinate.anchor && typeof coordinate.anchor === 'object'
      ? coordinate.anchor
      : { active: true, mode: 'off', left_live: false, right_live: false },
  }
}

function normalizeRestFrame({ status = {}, prediction = {}, sensors = {}, music = {}, piStatus = {}, coordinate = {} }, tick = 0) {
  const base = createConductorFrame(tick)
  const leftSensor = sensors.microbit_left || {}
  const rightSensor = sensors.microbit_right || {}
  const rawCamera = sensors.camera || {}
  const cameraHands = normalizeCameraHands(rawCamera)
  const cameraMedia = readCameraMedia(rawCamera, sensors)
  const cameraMetrics = deriveCameraMetrics(rawCamera, base.camera, cameraHands)
  const volume = toPercent(Number(music.volume), base.music.volume)
  const handCount = Number(sensors.hand_count || 0)
  const gateway = piStatus.gateway || status.pi_gateway || {}
  const piPreviewUrl = derivePiPreviewUrl(gateway)
  const sonicPi = status.sonic_pi || {}
  const sonicPiConnected = typeof sonicPi.connected === 'boolean'
    ? sonicPi.connected
    : Boolean(music.sonic_pi_connected)
  const runtime = piStatus.runtime || {}
  const controlPayload = getLastControlPayload(runtime)
  const coordinateNorm = normalizeCoordinateState(coordinate)
  // Prediction panel is driven by the coordinate recognizer's action log:
  // the most recent action (within a freshness window) is the "current
  // gesture", and the last few actions form the top-3 strip.
  const lastCoordAction = coordinateNorm.lastActions.length
    ? coordinateNorm.lastActions[coordinateNorm.lastActions.length - 1]
    : null
  const coordActionFresh = Boolean(
    lastCoordAction
    && Number.isFinite(Number(lastCoordAction.at))
    && (Date.now() / 1000 - Number(lastCoordAction.at)) < COORD_ACTION_FRESH_SECONDS,
  )
  const coordAction = coordActionFresh ? describeCoordinateAction(lastCoordAction.name) : null
  const confidence = coordAction ? 100 : 0
  const predictionTop3 = coordinateNorm.lastActions
    .slice(-3)
    .reverse()
    .map((action) => ({
      label: describeCoordinateAction(action?.name)[0],
      value: 100,
    }))

  return {
    ...base,
    timestamp: prediction.timestamp
      ? new Date(Number(prediction.timestamp) * 1000).toISOString()
      : new Date().toISOString(),
    connection: {
      camera: status.camera_connected ? 'Connected' : 'Waiting',
      hands: sensors.hand_detected ? `${handCount || 1} Hand${handCount === 1 ? '' : 's'} Detected` : 'No Hands Detected',
      tracking: sensors.hand_detected ? 'Stable' : 'Standby',
      fps: Number(rawCamera.fps || status.camera?.fps || base.connection.fps),
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
    camera: {
      ...base.camera,
      ...cameraMetrics,
      source: rawCamera.source || 'camera',
      frameId: rawCamera.frame_id ?? rawCamera.frameId ?? null,
      width: Number(rawCamera.width || base.camera.width || 640),
      height: Number(rawCamera.height || base.camera.height || 480),
      fps: Number(rawCamera.fps || base.connection.fps),
      hands: cameraHands,
      streamUrl: piPreviewUrl || cameraMedia.streamUrl,
      frameUrl: cameraMedia.frameUrl,
      hasLiveVideo: Boolean(piPreviewUrl || cameraMedia.streamUrl || cameraMedia.frameUrl),
      hasLiveLandmarks: cameraHands.some((hand) => hand.landmarks.length > 0),
      raw: rawCamera,
    },
    prediction: {
      gesture: coordActionFresh ? lastCoordAction.name : 'idle',
      label: coordAction ? coordAction[0].toUpperCase() : 'STANDBY',
      zh: coordAction ? coordAction[0] : 'Hands in view, waiting for a gesture',
      confidence,
      response: coordAction ? coordAction[1] : 'Waiting for a gesture action',
      top3: predictionTop3.length ? predictionTop3 : [{ label: 'Standby', value: 100 }],
    },
    actuation: {
      ...base.actuation,
      event: controlPayload.event || {},
      led: controlPayload.led_control || base.actuation.led,
      databaseSaved: Boolean(runtime.last_control_event || status.status === 'ok'),
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
      uiReceivedAt: Date.now() / 1000,
      playing: Boolean(music.playing),
      engine: music.engine ? toTitleCase(String(music.engine)) : 'Sonic Pi',
      section: music.section ? toTitleCase(String(music.section)) : base.music.section,
      lastBar: Number.isFinite(Number(music.last_bar)) ? Number(music.last_bar) : base.music.lastBar,
      lastBeat: Number.isFinite(Number(music.last_beat)) ? Number(music.last_beat) : base.music.lastBeat,
      beatStrength: toPercent(Number(music.beat_strength), base.music.beatStrength),
      sonicPiConnected,
      layers: music.layers && typeof music.layers === 'object'
        ? {
            melody: Boolean(music.layers.melody),
            harmony: Boolean(music.layers.harmony),
            bass: Boolean(music.layers.bass),
            drums: Boolean(music.layers.drums),
          }
        : base.music.layers,
      trackId: readString(music.track_id, base.music.trackId),
      trackIndex: toNumber(music.track_index, base.music.trackIndex),
      trackCount: toNumber(music.track_count, base.music.trackCount),
    },
    coordinate: coordinateNorm,
  }
}

function normalizeRemoteFrame(payload) {
  const base = createConductorFrame(0)
  const rawCamera = payload.camera || {}
  const cameraHands = normalizeCameraHands(rawCamera)
  const cameraMedia = readCameraMedia(rawCamera, payload.sensors || {})
  const cameraBase = {
    ...base.camera,
    ...rawCamera,
  }
  const cameraMetrics = deriveCameraMetrics(rawCamera, cameraBase, cameraHands)

  return {
    ...base,
    ...payload,
    timestamp: payload.timestamp || new Date().toISOString(),
    connection: {
      ...base.connection,
      ...payload.connection,
    },
    actuation: {
      ...base.actuation,
      ...payload.actuation,
    },
    camera: {
      ...cameraBase,
      ...cameraMetrics,
      hands: cameraHands.length ? cameraHands : (Array.isArray(rawCamera.hands) ? rawCamera.hands : []),
      streamUrl: cameraMedia.streamUrl || rawCamera.streamUrl || '',
      frameUrl: cameraMedia.frameUrl || rawCamera.frameUrl || '',
      hasLiveVideo: Boolean(cameraMedia.streamUrl || cameraMedia.frameUrl || rawCamera.streamUrl || rawCamera.frameUrl),
      hasLiveLandmarks: cameraHands.some((hand) => hand.landmarks.length > 0),
      raw: rawCamera,
    },
  }
}

function createTransportOverride(action, currentMusic = {}, status = 'sending', error = '') {
  const actionText = String(action).trim().toLowerCase()
  const requestedAt = Date.now() / 1000
  const currentPlaying = Boolean(currentMusic.playing)

  return {
    action: actionText,
    playing: PAUSE_ACTIONS.has(actionText) ? false : PLAY_ACTIONS.has(actionText) ? true : currentPlaying,
    requestedAt,
    status,
    error,
  }
}

function applyTransportOverride(nextFrame, override) {
  if (!override || !nextFrame?.music) return nextFrame

  const resetMusic = ['reset', 'next', 'previous', 'prev'].includes(override.action)

  return {
    ...nextFrame,
    music: {
      ...nextFrame.music,
      playing: override.playing,
      progress: resetMusic ? 0 : nextFrame.music.progress,
      elapsedSeconds: resetMusic ? 0 : nextFrame.music.elapsedSeconds,
      uiReceivedAt: override.requestedAt,
      transportAction: override.action,
      transportStatus: override.status,
      transportError: override.error,
    },
  }
}

async function fetchJsonWithTimeout(url, options = {}, timeoutMs = TRANSPORT_FETCH_TIMEOUT_MS) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    })
  } finally {
    window.clearTimeout(timeout)
  }
}

export function useConductorFeed(options = {}) {
  const wsUrl = options.wsUrl || import.meta.env.VITE_CONDUCTOR_WS_URL
  const restBaseUrl = options.restBaseUrl || import.meta.env.VITE_BACKEND_BASE_URL || BACKEND_REST_DEFAULT
  const [tick, setTick] = useState(0)
  const [frame, setFrame] = useState(() => createConductorFrame(0))
  const [connectionState, setConnectionState] = useState(wsUrl ? 'connecting websocket' : 'demo preview')
  const transportOverrideRef = useRef(null)
  const sendSonicPiTransport = async (action) => {
    const actionText = String(action).trim().toLowerCase()
    const optimisticOverride = createTransportOverride(actionText, frame.music)
    transportOverrideRef.current = optimisticOverride
    setFrame((current) => applyTransportOverride(current, optimisticOverride))

    try {
      const response = await fetchJsonWithTimeout(`${restBaseUrl}/api/sonic-pi/transport`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: actionText }),
      })
      if (!response.ok) throw new Error(`Sonic Pi transport returned ${response.status}`)
      const payload = await response.json()

      if (payload.music) {
        const music = payload.music
        const syncedOverride = {
          ...optimisticOverride,
          playing: Boolean(music.playing),
          requestedAt: Date.now() / 1000,
          status: 'synced',
          error: '',
        }
        transportOverrideRef.current = syncedOverride
        setFrame((current) => applyTransportOverride(
          {
            ...current,
            music: {
              ...current.music,
              title: music.title || current.music.title,
              key: music.key || current.music.key,
              bpm: Number(music.bpm || current.music.bpm),
              volume: toPercent(Number(music.volume), current.music.volume),
              energy: toPercent(Number(music.energy), current.music.energy),
              style: music.style ? toTitleCase(String(music.style)) : current.music.style,
              progress: clamp(toNumber(music.progress, current.music.progress), 0, 100),
              elapsedSeconds: toNumber(music.elapsed_seconds, current.music.elapsedSeconds),
              durationSeconds: toNumber(music.duration_seconds, current.music.durationSeconds),
              performanceElapsedSeconds: toNumber(
                music.performance_elapsed_seconds,
                current.music.performanceElapsedSeconds,
              ),
              playing: Boolean(music.playing),
              engine: music.engine ? toTitleCase(String(music.engine)) : current.music.engine,
              section: music.section ? toTitleCase(String(music.section)) : current.music.section,
              lastBar: Number.isFinite(Number(music.last_bar)) ? Number(music.last_bar) : current.music.lastBar,
              lastBeat: Number.isFinite(Number(music.last_beat)) ? Number(music.last_beat) : current.music.lastBeat,
              beatStrength: toPercent(Number(music.beat_strength), current.music.beatStrength),
              sonicPiConnected: typeof payload.sonic_pi?.connected === 'boolean'
                ? payload.sonic_pi.connected
                : Boolean(music.sonic_pi_connected || current.music.sonicPiConnected),
              uiReceivedAt: Date.now() / 1000,
            },
          },
          syncedOverride,
        ))
      } else {
        const syncedOverride = {
          ...optimisticOverride,
          requestedAt: Date.now() / 1000,
          status: 'synced',
          error: '',
        }
        transportOverrideRef.current = syncedOverride
        setFrame((current) => applyTransportOverride(current, syncedOverride))
      }

      return payload
    } catch (error) {
      const localOverride = {
        ...optimisticOverride,
        requestedAt: Date.now() / 1000,
        status: 'local preview',
        error: error.name === 'AbortError' ? 'Backend timeout' : error.message,
      }
      transportOverrideRef.current = localOverride
      setFrame((current) => applyTransportOverride(current, localOverride))
      return { sent: false, local: true, error: localOverride.error }
    }
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
      setConnectionState('demo preview')
      if (restTimer) window.clearInterval(restTimer)
      mockTimer = window.setInterval(() => {
        feedTick += 1
        setTick(feedTick)
        setFrame(applyTransportOverride(createConductorFrame(feedTick), transportOverrideRef.current))
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
      const coordinate = await fetchOptionalJson('/api/coordinate/state', {})
      feedTick += 1
      setTick(feedTick)
      setFrame(applyTransportOverride(
        normalizeRestFrame({ status, prediction, sensors, music, piStatus, coordinate }, feedTick),
        transportOverrideRef.current,
      ))
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
          }, REST_POLL_INTERVAL_MS)
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
            setFrame(applyTransportOverride(normalizeRemoteFrame(JSON.parse(event.data)), transportOverrideRef.current))
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
