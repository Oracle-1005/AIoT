import { useEffect, useState } from 'react'
import { createConductorFrame, makeInferenceLog } from '../data/conductorData'

function normalizeRemoteFrame(payload) {
  return {
    ...createConductorFrame(0),
    ...payload,
    timestamp: payload.timestamp || new Date().toISOString(),
  }
}

export function useConductorFeed(options = {}) {
  const wsUrl = options.wsUrl || import.meta.env.VITE_CONDUCTOR_WS_URL
  const [tick, setTick] = useState(0)
  const [frame, setFrame] = useState(() => createConductorFrame(0))
  const [connectionState, setConnectionState] = useState(wsUrl ? 'connecting' : 'mock')

  useEffect(() => {
    let timer
    let socket
    let cancelled = false

    const startMockFeed = () => {
      setConnectionState(wsUrl ? 'mock fallback' : 'mock')
      timer = window.setInterval(() => {
        setTick((current) => {
          const next = current + 1
          setFrame(createConductorFrame(next))
          return next
        })
      }, 1800)
    }

    if (wsUrl) {
      try {
        socket = new WebSocket(wsUrl)
        socket.onopen = () => !cancelled && setConnectionState('live websocket')
        socket.onmessage = (event) => {
          if (cancelled) return
          try {
            setFrame(normalizeRemoteFrame(JSON.parse(event.data)))
          } catch {
            setConnectionState('invalid payload')
          }
        }
        socket.onerror = () => !cancelled && startMockFeed()
        socket.onclose = () => !cancelled && startMockFeed()
      } catch {
        startMockFeed()
      }
    } else {
      startMockFeed()
    }

    return () => {
      cancelled = true
      if (timer) window.clearInterval(timer)
      if (socket && socket.readyState < 2) socket.close()
    }
  }, [wsUrl])

  return {
    frame,
    tick,
    connectionState,
    logs: makeInferenceLog(frame),
  }
}
