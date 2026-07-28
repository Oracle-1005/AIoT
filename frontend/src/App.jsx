import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Activity,
  Brain,
  Camera,
  Check,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  Gauge,
  Hand,
  Home,
  Layers,
  Maximize2,
  Monitor,
  Music2,
  Network,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Server,
  Settings,
  ShieldCheck,
  SkipBack,
  SkipForward,
  SlidersHorizontal,
  Sparkles,
  Upload,
  Users,
  Video,
  Volume2,
  Wifi,
  X,
  Zap,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  analyticsSeries,
  assetSlots,
  describeCoordinateAction,
  experienceScenarios,
  flowSteps,
  gestureCatalog,
  navItems,
  reservedInterfaceSlots,
  teamMembers,
  trainingSteps,
} from './data/conductorData'
import { useConductorFeed } from './hooks/useConductorFeed'

const chartTooltipStyle = {
  background: 'rgba(6, 7, 13, 0.92)',
  border: '1px solid rgba(255,255,255,0.14)',
  borderRadius: 8,
  color: '#e5edf6',
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function SectionHeader({ eyebrow, title, description, icon: Icon }) {
  return (
    <div className="mb-7 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="max-w-3xl">
        <span className="eyebrow">
          {Icon ? <Icon size={14} /> : null}
          {eyebrow}
        </span>
        <h2 className="mt-4 font-display text-3xl font-semibold text-white sm:text-4xl">
          {title}
        </h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
          {description}
        </p>
      </div>
    </div>
  )
}

function StatusDot({ tone = 'cyan' }) {
  const colors = {
    cyan: 'bg-cyan shadow-[0_0_18px_rgba(56,189,248,0.75)]',
    green: 'bg-mint shadow-[0_0_18px_rgba(34,197,94,0.75)]',
    gold: 'bg-gold shadow-[0_0_18px_rgba(244,199,107,0.65)]',
    red: 'bg-coral shadow-[0_0_18px_rgba(251,113,133,0.7)]',
  }
  return <span className={`h-2 w-2 rounded-full ${colors[tone]}`} />
}

function formatDuration(seconds = 0) {
  const safeSeconds = Number.isFinite(Number(seconds)) ? Math.max(0, Math.floor(Number(seconds))) : 0
  const minutes = Math.floor(safeSeconds / 60)
  const remainder = safeSeconds % 60
  return `${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`
}

function getSonicPiDisplayState(music = {}) {
  if (music.sonicPiConnected && music.sonicPiCommandReady === false) {
    return {
      label: 'Command Channel Dead',
      pillClass: 'status-pill border-coral/40 text-rose-200',
      hint: 'Feedback is alive but Sonic Pi is not receiving commands. Fully quit Sonic Pi and Run aiot_loader.rb once.',
    }
  }

  if (music.transportStatus === 'disabled') {
    return {
      label: 'Safe Mode: Single Track',
      pillClass: 'status-pill border-gold/40 text-gold',
      hint: music.transportError || 'Track switching is disabled in safe Sonic Pi mode.',
    }
  }

  if (music.sonicPiConnected) {
    return {
      label: 'Sonic Pi Live',
      pillClass: 'status-pill border-emerald-400/40 text-emerald-200',
      hint: '',
    }
  }

  if (music.transportStatus === 'backend error') {
    return {
      label: 'Backend Offline',
      pillClass: 'status-pill border-coral/40 text-rose-200',
      hint: 'Start the backend before controlling Sonic Pi.',
    }
  }

  if (music.transportStatus === 'synced' || music.transportStatus === 'sending') {
    return {
      label: 'Awaiting Sonic Pi',
      pillClass: 'status-pill border-gold/40 text-gold',
      hint: 'Run the Sonic Pi buffer to hear web playback control.',
    }
  }

  return {
    label: 'Run Sonic Pi Buffer',
    pillClass: 'status-pill border-gold/40 text-gold',
    hint: 'Open Sonic Pi and Run the prepared music script first.',
  }
}

const handConnections = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
]

function isVideoSource(src = '') {
  return /\.(mp4|webm|mov)(\?.*)?$/i.test(src)
}

function AssetPlaceholder({ title, path, note, type = 'video' }) {
  const Icon = type === 'video' ? Video : Upload
  return (
    <div className="relative overflow-hidden rounded-lg border border-dashed border-cyan/35 bg-cyan/5 p-5">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan/70 to-transparent" />
      <div className="flex items-start gap-4">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md border border-cyan/30 bg-cyan/10 text-cyan">
          <Icon size={21} />
        </div>
        <div>
          <p className="text-sm font-semibold text-white">{title}</p>
          <p className="mt-1 font-mono text-xs text-cyan">{path}</p>
          <p className="mt-2 text-xs leading-5 text-slate-300">{note}</p>
        </div>
      </div>
    </div>
  )
}

function TopNav({ onPresentation, onExperience, connectionState }) {
  const lowerState = connectionState.toLowerCase()
  const offline = lowerState.includes('unavailable') || lowerState.includes('timeout') || lowerState.includes('error')
  const statusTone = offline ? 'red' : lowerState.includes('connecting') ? 'gold' : 'green'
  const statusLabel = lowerState.includes('websocket')
    ? 'Live Connected'
    : lowerState.includes('rest')
      ? 'Backend Connected'
      : offline
        ? 'Backend Offline'
        : 'Connecting'

  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-void/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <button
          type="button"
          className="flex items-center gap-3 text-left"
          onClick={() => scrollToSection('home')}
          aria-label="Go to homepage"
        >
          <div className="grid h-10 w-10 place-items-center rounded-md border border-gold/35 bg-gold/10 text-gold">
            <Music2 size={20} />
          </div>
          <div>
            <p className="font-display text-sm font-semibold text-white">AIoT Conductor</p>
            <p className="text-xs text-slate-400">Camera + Micro:bit + Edge AI</p>
          </div>
        </button>

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary navigation">
          {navItems.map((item) => (
            <button key={item.id} type="button" className="nav-link" onClick={() => scrollToSection(item.id)}>
              {item.short}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <span className="hidden items-center gap-2 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-slate-200 sm:inline-flex">
            <StatusDot tone={statusTone} />
            {statusLabel}
          </span>
          <button type="button" className="secondary-button hidden sm:inline-flex" onClick={onExperience}>
            <Sparkles size={16} />
            Experience
          </button>
          <button type="button" className="primary-button" onClick={onPresentation}>
            <Maximize2 size={16} />
            Presentation Mode
          </button>
        </div>
      </div>
      <div className="flex gap-1 overflow-x-auto px-4 pb-3 lg:hidden">
        {navItems.map((item) => (
          <button key={item.id} type="button" className="nav-link shrink-0" onClick={() => scrollToSection(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
    </header>
  )
}

function HeroSection({ frame, onPresentation, onExperience, onVideo }) {
  const heroStats = [
    ['Live Input', 'Camera + 2x Micro:bit'],
    ['AI Layer', 'Pi-side gesture events'],
    ['Music Engine', 'Sonic Pi OSC'],
    ['Current Latency', `${frame.connection.latency} ms`],
  ]
  const actionChain = [
    ['Detected Gesture', frame.prediction.label],
    ['AI Confidence', `${frame.prediction.confidence}%`],
    ['Music Action', frame.prediction.response],
    ['Database', frame.connection.backend === 'REST Online' ? 'Saved' : 'Ready'],
  ]
  // Synthesized 16x32 dual-panel music waveform, mirroring the Pi-side
  // led_consumer layout (two 32x8 panels stacked into a 16-row x 32-col
  // canvas). Driven only by live music state so the preview tracks the
  // real beat/energy instead of showing static decoration.
  const ledWaveLevels = Array.from({ length: 32 }, (_, column) => {
    const barPhase = Number(frame.music.lastBar || 0) * 1.7 + Number(frame.music.lastBeat || 0) * 0.9
    const shape = Math.abs(Math.sin(column * 0.52 + barPhase)) * 0.65
      + Math.abs(Math.sin(column * 0.19 - barPhase * 0.7)) * 0.35
    const energy = Math.max(0.15, Math.min(1, Number(frame.music.energy || 45) / 100))
    const beat = Math.max(0, Math.min(1, Number(frame.music.beatStrength || 0) / 100))
    if (!frame.music.playing) return 0.05
    return Math.min(1, shape * (0.35 + energy * 0.65) * (0.55 + beat * 0.45) + beat * 0.18)
  })
  const ledWaveCells = []
  for (let row = 15; row >= 0; row -= 1) {
    for (let column = 0; column < 32; column += 1) {
      const level = ledWaveLevels[column]
      const lit = level * 16 > row + 0.5
      ledWaveCells.push(
        <span
          key={`${row}-${column}`}
          className="h-[5px] rounded-[1px]"
          style={{ backgroundColor: lit ? `rgba(56,189,248,${0.35 + level * 0.65})` : 'rgba(255,255,255,0.07)' }}
        />,
      )
    }
  }
  const roadshowEntries = [
    {
      title: 'Prepared Demo Video',
      description: 'Watch the complete interaction: gesture input, AI recognition, and musical response.',
      action: 'Open Video',
      icon: Video,
      onClick: onVideo,
    },
    {
      title: 'Live Hardware Demo',
      description: 'Use Raspberry Pi Camera, Micro:bit, AI recognition, and Sonic Pi together.',
      action: 'Roadshow Mode',
      icon: Maximize2,
      onClick: onPresentation,
    },
    {
      title: 'Guest Experience',
      description: 'Let visitors conduct the music themselves with guided gestures.',
      action: 'Launch',
      icon: Sparkles,
      onClick: onExperience,
    },
    {
      title: 'Tech Stack & Workflow',
      description: 'See how sensing, AI, music, lighting, and records connect in one loop.',
      action: 'View Workflow',
      icon: Monitor,
      onClick: () => scrollToSection('live-stage'),
    },
  ]

  return (
    <section id="home" className="relative overflow-hidden border-b border-white/10">
      <div className="absolute inset-0 stage-grid opacity-40" />
      <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(6,7,13,0.22),rgba(6,7,13,0.98)_74%)]" />
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan/60 to-transparent" />
      <div className="section-shell relative min-h-[calc(100svh-92px)] content-end pb-8 pt-14">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65 }}
          className="max-w-5xl py-12"
        >
          <span className="eyebrow">
            <Sparkles size={14} />
            AIoT Smart Conducting Performance System
          </span>
          <h1 className="hero-title mt-6 max-w-5xl font-display text-5xl font-semibold leading-tight sm:text-6xl lg:text-7xl">
            Conduct Music with Motion
          </h1>
          <p className="mt-6 max-w-3xl text-lg leading-8 text-slate-200">
            Raise your hands and the system reads conducting intention through a Raspberry Pi camera and Micro:bit sensors, then changes Sonic Pi music, LED feedback, and interaction records in real time.
          </p>
          <div className="mt-6 rounded-lg border border-white/10 bg-white/[0.045] p-4">
            <p className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase text-cyan">
              <Users size={14} />
              Project Team
            </p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {teamMembers.map((member) => (
                <div key={member.id} className="rounded-md border border-white/10 bg-black/20 px-3 py-2">
                  <p className="font-display text-sm font-semibold text-white">{member.name}</p>
                  <p className="mt-1 text-[11px] uppercase text-slate-500">{member.role}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-8 flex flex-wrap gap-3">
            <button type="button" className="primary-button" onClick={onVideo}>
              <Video size={16} />
              Prepared Video
            </button>
            <button type="button" className="secondary-button" onClick={onPresentation}>
              <Maximize2 size={16} />
              Live Roadshow
            </button>
            <button type="button" className="primary-button" onClick={onExperience}>
              <Sparkles size={16} />
              Guest Experience
            </button>
            <button type="button" className="secondary-button" onClick={() => scrollToSection('live-stage')}>
              <Monitor size={16} />
              Workflow View
            </button>
          </div>
          <div className="mt-6 grid max-w-5xl gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {roadshowEntries.map((entry, index) => {
              const EntryIcon = entry.icon
              return (
                <button
                  key={entry.title}
                  type="button"
                  className="rounded-lg border border-white/10 bg-white/[0.045] p-4 text-left transition hover:border-cyan/40 hover:bg-cyan/10"
                  onClick={entry.onClick}
                >
                  <div className="mb-4 flex items-center justify-between">
                    <div className="grid h-10 w-10 place-items-center rounded-md border border-cyan/25 bg-cyan/10 text-cyan">
                      <EntryIcon size={18} />
                    </div>
                    <span className="font-mono text-xs text-slate-500">0{index + 1}</span>
                  </div>
                  <p className="text-sm font-semibold text-white">{entry.title}</p>
                  <p className="mt-2 min-h-10 text-xs leading-5 text-slate-400">{entry.description}</p>
                  <p className="mt-4 text-xs font-semibold uppercase text-gold">{entry.action}</p>
                </button>
              )
            })}
          </div>
          <div className="mt-8 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {heroStats.map(([label, value]) => (
              <div key={label} className="hero-stat">
                <p className="text-[11px] uppercase text-slate-500">{label}</p>
                <p className="mt-1 text-sm font-semibold text-slate-100">{value}</p>
              </div>
            ))}
          </div>
        </motion.div>

        <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="glass-panel screen-frame flex flex-col overflow-hidden p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <Activity size={16} className="text-cyan" />
                Live Gesture Signal
              </div>
              <span className="status-pill">
                <StatusDot tone="gold" />
                {frame.prediction.label} · {frame.prediction.confidence}%
              </span>
            </div>
            <ConductorSignalScene frame={frame} compact heightClass="flex-1 min-h-52" />
          </div>
          <div className="glass-panel p-5">
            <p className="flex items-center gap-2 text-sm font-semibold text-white">
              <ShieldCheck size={16} className="text-mint" />
              AIoT Action Chain
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Every recognised gesture is translated into visible music, light, and database feedback.
            </p>
            <div className="mt-5 grid gap-2">
              {actionChain.map(([label, value]) => (
                <div key={label} className="rounded-md border border-white/10 bg-white/[0.045] px-3 py-2">
                  <p className="text-[11px] uppercase text-slate-500">{label}</p>
                  <p className="mt-1 text-sm font-semibold text-white">{value}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 rounded-lg border border-white/10 bg-black/25 p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs uppercase text-slate-500">LED Matrix Preview</p>
                <p className="font-mono text-[10px] text-slate-500">16 × 32 dual panel</p>
              </div>
              <div className="mt-3 grid gap-[2px]" style={{ gridTemplateColumns: 'repeat(32, minmax(0, 1fr))' }}>
                {ledWaveCells}
              </div>
              <p className="mt-3 text-xs text-slate-300">{frame.music.playing ? 'Live music waveform' : 'Standby — music paused'}</p>
            </div>
          </div>
        </div>

        <div className="mt-8">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="flex items-center gap-2 text-sm font-semibold uppercase text-slate-300">
                <Users size={16} className="text-cyan" />
                Project Team
              </p>
              <p className="mt-1 text-sm text-slate-400">Five roles building the full AIoT conducting system.</p>
            </div>
            <span className="status-pill">5 Members</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {teamMembers.map((member) => (
              <div key={member.id} className="hero-stat min-h-[148px]">
                <p className="text-[11px] uppercase text-cyan">{member.role}</p>
                <p className="mt-2 font-display text-lg font-semibold text-white">{member.name}</p>
                <p className="mt-1 font-mono text-[11px] text-slate-500">{member.id}</p>
                <p className="mt-3 text-xs leading-5 text-slate-300">{member.focus}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function ExperienceGateway({ frame, onExperience }) {
  return (
    <section id="experience-gateway" className="section-shell">
      <div className="grid items-center gap-5 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <span className="eyebrow">
            <Sparkles size={14} />
            Visitor Experience
          </span>
          <h2 className="mt-4 font-display text-3xl font-semibold text-white sm:text-4xl">
            Open Interaction Mode
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
            Visitors can stand in front of the Raspberry Pi camera, follow simple gesture cues, and watch the music respond through sound and live visual feedback.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <button type="button" className="primary-button" onClick={onExperience}>
              <Play size={16} />
              Launch Experience
            </button>
            <button type="button" className="secondary-button" onClick={() => scrollToSection('live-stage')}>
              <Server size={16} />
              Workflow View
            </button>
          </div>
        </div>

        <div className="glass-panel p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-white">
              <Hand size={16} className="text-gold" />
              Gesture Scenarios
            </p>
            <span className="status-pill">{frame.music.bpm} BPM</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {experienceScenarios.map((scenario) => (
              <button
                key={scenario.gesture}
                type="button"
                className="rounded-lg border border-white/10 bg-white/[0.045] p-4 text-left transition hover:border-cyan/40 hover:bg-cyan/10"
                onClick={onExperience}
              >
                <span className="mb-3 block h-1.5 w-14 rounded-full" style={{ backgroundColor: scenario.color }} />
                <p className="text-sm font-semibold text-white">{scenario.label}</p>
                <p className="mt-1 text-xs text-slate-400">{scenario.effect}</p>
              </button>
            ))}
          </div>
          <div className="mt-4 rounded-lg border border-dashed border-cyan/25 bg-cyan/5 p-4">
            <p className="mb-3 text-xs font-semibold uppercase text-cyan">Real Hardware Slots</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {reservedInterfaceSlots.map((slot) => (
                <div key={slot.field} className="rounded-md border border-white/10 bg-black/20 px-3 py-2">
                  <p className="text-xs font-semibold text-white">{slot.title}</p>
                  <p className="mt-1 truncate font-mono text-[11px] text-cyan">{slot.field}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-300">这里是后续真实树莓派摄像头、手部关键点和控制事件的接入口；素材替换说明保留中文，-演主界面仍保持英文。</p>
          </div>
        </div>
      </div>
    </section>
  )
}

function ConductorSignalScene({ frame, compact = false, heightClass = '' }) {
  const cameraWidth = Number(frame.camera?.width) || 640
  const cameraHeight = Number(frame.camera?.height) || 480
  const mediaSource = frame.camera?.streamUrl || frame.camera?.frameUrl || ''
  // Micro:bit anchor gate: when the backend anchor gate is on and no live
  // micro:bit is present, hand skeletons are hidden (same rule as gesture
  // recognition — no anchor, no tracking display).
  const anchor = frame.coordinate?.anchor
  const anchorBlocks = Boolean(anchor && anchor.mode && anchor.mode !== 'off' && !anchor.active)
  const liveHands = useMemo(
    () => {
      if (anchorBlocks) return []
      return (Array.isArray(frame.camera?.hands) ? frame.camera.hands : []).filter((hand) => hand?.landmarks?.length)
    },
    [frame.camera?.hands, anchorBlocks],
  )
  const hasLiveLandmarks = liveHands.length > 0
  const lastSceneAction = frame.coordinate?.lastActions?.length
    ? frame.coordinate.lastActions[frame.coordinate.lastActions.length - 1]
    : null
  const sceneIntention = lastSceneAction && (Date.now() / 1000 - Number(lastSceneAction.at || 0)) < 12
    ? describeCoordinateAction(lastSceneAction.name)[0]
    : null
  const waveBars = useMemo(
    () =>
      Array.from({ length: compact ? 34 : 52 }, (_, index) => ({
        height: 22 + Math.abs(Math.sin(index / 2 + frame.music.bpm / 30)) * 76,
        delay: `${index * 0.035}s`,
      })),
    [compact, frame.music.bpm],
  )

  const toScenePoint = useCallback((point) => {
    const rawX = Number(point?.x)
    const rawY = Number(point?.y)
    if (!Number.isFinite(rawX) || !Number.isFinite(rawY)) return null
    const normalizedX = rawX > 1 ? rawX / cameraWidth : rawX
    const normalizedY = rawY > 1 ? rawY / cameraHeight : rawY

    return {
      x: Math.max(0, Math.min(1, normalizedX)) * 900,
      y: Math.max(0, Math.min(1, normalizedY)) * 360,
    }
  }, [cameraWidth, cameraHeight])

  const sceneHeight = heightClass || (compact ? 'h-52' : 'h-80')

  return (
    <div className={`relative overflow-hidden rounded-lg border border-white/10 bg-void/75 ${sceneHeight}`}>
      {mediaSource ? (
        isVideoSource(mediaSource) ? (
          <video
            className="absolute inset-0 h-full w-full object-cover opacity-70"
            src={mediaSource}
            autoPlay
            muted
            loop
            playsInline
          />
        ) : (
          <img
            className="absolute inset-0 h-full w-full object-cover opacity-70"
            src={mediaSource}
            alt=""
          />
        )
      ) : (
        <div className="absolute inset-0 stage-grid opacity-50" />
      )}
      <div className="absolute inset-0 bg-black/25" />
      <div className="signal-ribbon absolute inset-x-0 top-0 h-16" />
      {!mediaSource && !hasLiveLandmarks ? (
        <>
          <motion.div
            className="absolute left-[22%] top-[26%] h-5 w-5 rounded-full bg-cyan shadow-[0_0_28px_rgba(56,189,248,0.8)]"
            animate={{ x: [0, 42, 18, 64, 0], y: [0, -18, 32, 14, 0] }}
            transition={{ duration: 4.2, repeat: Infinity, ease: 'easeInOut' }}
          />
          <motion.div
            className="absolute right-[24%] top-[34%] h-5 w-5 rounded-full bg-gold shadow-[0_0_28px_rgba(244,199,107,0.8)]"
            animate={{ x: [0, -28, -64, -24, 0], y: [0, 40, 18, -20, 0] }}
            transition={{ duration: 3.6, repeat: Infinity, ease: 'easeInOut' }}
          />
        </>
      ) : null}
      {(
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 900 360" preserveAspectRatio="none" role="presentation" aria-hidden="true">
        {(frame.coordinate?.zones?.bands || []).map(([lo, hi], idx) => (
          <g key={`zone-${idx}`}>
            <rect
              x="0"
              y={Number(lo) * 360}
              width="900"
              height={(Number(hi) - Number(lo)) * 360}
              fill={idx % 2 === 0 ? 'rgba(56,189,248,0.05)' : 'rgba(244,199,107,0.05)'}
              stroke="rgba(148,163,184,0.35)"
              strokeWidth="1"
              strokeDasharray="6 6"
            />
            <text
              x="8"
              y={((Number(lo) + Number(hi)) / 2) * 360 + 4}
              fill="rgba(226,232,240,0.75)"
              fontSize="13"
              fontFamily="monospace"
            >
              {(frame.coordinate?.zones?.layers || [])[idx] || `zone ${idx + 1}`}
            </text>
          </g>
        ))}
      </svg>
      )}
      {!mediaSource && !hasLiveLandmarks && !compact ? (
        <div className="absolute left-1/2 top-1/2 w-[min(480px,calc(100%-48px))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-dashed border-cyan/30 bg-black/35 p-4 text-center backdrop-blur">
          <p className="text-sm font-semibold text-white">Raspberry Pi Camera Preview</p>
          <p className="mt-2 text-xs font-semibold uppercase text-cyan">Live hand tracking area</p>
          <p className="mt-2 text-xs leading-5 text-slate-300">{frame.connection.piGatewayConnected
            ? '链路已连接：把双手放进树莓派摄像头画面，关键点、骨架和运动轨迹会实时叠加在这里。'
            : '等待树莓派链路接入：这里显示 Pi 摄像头实时画面（MJPEG，不调用电脑本地摄像头），手部关键点和运动轨迹会叠加在画面上。'}</p>
        </div>
      ) : null}
      {!mediaSource ? (
      <div className="absolute inset-x-6 bottom-5 flex h-20 items-end justify-center gap-1.5">
        {waveBars.map((bar, index) => (
          <span
            key={`${bar.height}-${index}`}
            className="waveform-bar w-1 rounded-full bg-gradient-to-t from-cyan/20 via-cyan to-gold"
            style={{ height: `${bar.height}%`, animationDelay: bar.delay }}
          />
        ))}
      </div>
      ) : null}
      <div className="absolute left-5 top-5 grid gap-2 text-xs">
        <span className="status-pill">
          <StatusDot tone={frame.connection.camera === 'Connected' ? 'green' : 'gold'} />
          {frame.connection.camera}
        </span>
        <span className="status-pill">
          <StatusDot tone={hasLiveLandmarks ? 'cyan' : 'gold'} />
          {hasLiveLandmarks ? `${liveHands.length} Live Hand${liveHands.length > 1 ? 's' : ''}` : frame.connection.hands}
        </span>
      </div>
      <div className="absolute right-5 top-5">
        <span className="status-pill">
          <StatusDot tone={hasLiveLandmarks || mediaSource ? 'green' : 'gold'} />
          {hasLiveLandmarks ? 'Hand Tracking Live' : mediaSource ? 'Pi Camera Live' : 'Pi Camera Preview'}
        </span>
      </div>
      <div className="absolute bottom-5 right-5 rounded-md border border-white/10 bg-black/35 px-3 py-2 text-right backdrop-blur">
        <p className="text-xs text-slate-400">Current Intention</p>
        <p className="font-display text-xl font-semibold text-white">{sceneIntention || frame.prediction.label}</p>
      </div>
    </div>
  )
}

function LiveStage({ frame, logs, onTransport }) {
  return (
    <section id="live-stage" className="section-shell">
      <SectionHeader
        eyebrow="Tech Stack & Workflow"
        title="Technology Stack and Work Chain"
        description="Pi Camera and Micro:bit data are fused on Raspberry Pi, sent to the PC backend, and turned into Sonic Pi music, LED feedback, and saved records."
        icon={Monitor}
      />

      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.95fr_0.9fr]">
        <CameraGesturePanel frame={frame} />
        <AiPredictionCard frame={frame} />
        <MusicControlCenter frame={frame} onTransport={onTransport} />
      </div>

      <GestureConsole frame={frame} />

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <MicrobitCard side="LEFT MICRO:BIT" data={frame.microbit.left} color="cyan" />
        <MicrobitCard side="RIGHT MICRO:BIT" data={frame.microbit.right} color="gold" />
      </div>

      <div className="mt-4">
        <InferenceLog logs={logs} />
      </div>
    </section>
  )
}

function CameraGesturePanel({ frame }) {
  return (
    <div className="glass-panel p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold text-white">
            <Camera size={16} className="text-cyan" />
            Raspberry Pi Camera Feed
          </p>
          <p className="mt-1 text-xs text-slate-400">Pi camera frame, hand landmarks, skeleton lines, trajectory trail</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="status-pill">FPS {frame.connection.fps}</span>
          <span className="status-pill">{frame.connection.latency} ms</span>
          <span className="status-pill">
            <StatusDot tone={frame.connection.piGatewayConnected ? 'green' : 'gold'} />
            {frame.connection.piGatewayConnected ? frame.connection.piGateway : 'Pi Ready'}
          </span>
        </div>
      </div>
      <div className="scanline relative overflow-hidden rounded-lg border border-cyan/20 bg-black/50">
        <ConductorSignalScene frame={frame} />
      </div>
      <div className="mt-4">
        <AssetPlaceholder
          title={assetSlots[1].title}
          path={assetSlots[1].path}
          note={assetSlots[1].note}
        />
      </div>
    </div>
  )
}

function AiPredictionCard({ frame }) {
  return (
    <div className="glass-panel p-5">
      <div className="mb-5 flex items-center justify-between">
        <p className="flex items-center gap-2 text-sm font-semibold text-white">
          <Brain size={16} className="text-violet-300" />
          AI Prediction
        </p>
        <span className="status-pill">
          <StatusDot tone="green" />
          Local Inference
        </span>
      </div>

      <motion.div
        key={frame.prediction.label}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-lg border border-gold/25 bg-gold/10 p-5"
      >
        <p className="text-xs uppercase text-gold">Current Intention</p>
        <h3 className="mt-3 font-display text-4xl font-semibold text-white">{frame.prediction.label}</h3>
        <p className="mt-1 text-lg text-gold">{frame.prediction.zh}</p>
        <div className="mt-5 flex items-end justify-between">
          <div>
            <p className="text-xs text-slate-400">AI Confidence</p>
            <p className="font-display text-4xl font-semibold text-white">{frame.prediction.confidence}%</p>
          </div>
          <Gauge className="text-gold" size={42} />
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
          <motion.div
            className="h-full bg-gradient-to-r from-gold to-cyan"
            animate={{ width: `${frame.prediction.confidence}%` }}
          />
        </div>
        <p className="mt-4 text-sm text-slate-200">System response: {frame.prediction.response}</p>
      </motion.div>

      <div className="mt-5">
        <p className="mb-3 text-xs font-semibold uppercase text-slate-400">Top-3 Predictions</p>
        <div className="space-y-3">
          {frame.prediction.top3.map((item) => (
            <div key={item.label}>
              <div className="mb-1 flex justify-between text-xs text-slate-300">
                <span>{item.label}</span>
                <span>{item.value}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/10">
                <motion.div
                  className="h-full rounded-full bg-cyan"
                  initial={{ width: 0 }}
                  animate={{ width: `${item.value}%` }}
                  transition={{ duration: 0.6 }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-2">
        {gestureCatalog.map((gesture) => (
          <div key={gesture.key} className="rounded-md border border-white/10 bg-white/[0.04] p-3">
            <p className="text-xs font-semibold text-white">{gesture.label}</p>
            <p className="text-xs text-slate-400">{gesture.zh}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function MusicControlCenter({ frame, onTransport }) {
  const [transportPending, setTransportPending] = useState(false)
  const [clockNow, setClockNow] = useState(() => Date.now())
  const metrics = [
    { label: 'BPM', value: frame.music.bpm, icon: Activity, suffix: '' },
    { label: 'Volume', value: frame.music.volume, icon: Volume2, suffix: '%' },
    { label: 'Energy', value: frame.music.energy, icon: Zap, suffix: '%' },
    { label: 'Density', value: frame.music.density, icon: SlidersHorizontal, suffix: '%' },
  ]
  const sonicPiDisplay = getSonicPiDisplayState(frame.music)
  const TransportIcon = frame.music.playing ? Pause : Play
  const transportAction = frame.music.playing ? 'pause' : 'start'
  const transportLabel = frame.music.playing ? 'Pause Music' : 'Play Music'
  const uiReceivedAt = Number(frame.music.uiReceivedAt) || clockNow / 1000
  const secondsSinceFrame = frame.music.playing
    ? Math.max(0, Math.min(clockNow / 1000 - uiReceivedAt, 1.25))
    : 0
  const loopDuration = Math.max(0, Number(frame.music.durationSeconds) || 0)
  const rawLoopElapsed = loopDuration
    ? (Number(frame.music.elapsedSeconds || 0) + secondsSinceFrame) % loopDuration
    : Number(frame.music.elapsedSeconds || 0)
  const [displayLoopElapsed, setDisplayLoopElapsed] = useState(rawLoopElapsed)
  const progressWidth = loopDuration
    ? Math.min(100, Math.max(0, (displayLoopElapsed / loopDuration) * 100))
    : frame.music.progress

  useEffect(() => {
    if (!frame.music.playing) {
      setClockNow(Date.now())
      return undefined
    }
    const timer = window.setInterval(() => setClockNow(Date.now()), 100)
    return () => window.clearInterval(timer)
  }, [frame.music.playing])

  useEffect(() => {
    setDisplayLoopElapsed((previous) => {
      if (!frame.music.playing || !loopDuration) return rawLoopElapsed

      const nearLoopEnd = previous >= loopDuration - 1.5
      const wrappedToStart = nearLoopEnd && rawLoopElapsed <= 1.5
      const movedBackward = rawLoopElapsed + 0.35 < previous

      if (wrappedToStart) return rawLoopElapsed
      if (movedBackward) return previous
      return rawLoopElapsed
    })
  }, [frame.music.playing, loopDuration, rawLoopElapsed])

  const handleTransport = async (action = transportAction) => {
    if (!onTransport || transportPending) return
    setTransportPending(true)
    try {
      await onTransport(action)
    } catch (error) {
      console.error(error)
    } finally {
      setTransportPending(false)
    }
  }

  return (
    <div className="glass-panel p-5">
      <div className="mb-5 flex items-center justify-between">
        <p className="flex items-center gap-2 text-sm font-semibold text-white">
          <Music2 size={16} className="text-gold" />
          Music Control Center
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          <span className="status-pill">{frame.music.style}</span>
          <span className={sonicPiDisplay.pillClass}>{sonicPiDisplay.label}</span>
        </div>
      </div>

      <div className="rounded-lg border border-white/10 bg-black/25 p-4">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-white">{frame.music.title}</p>
            <p className="text-xs text-slate-400">Key: {frame.music.key} | Engine: {frame.music.engine}</p>
            {sonicPiDisplay.hint ? <p className="mt-1 text-[11px] text-gold/80">{sonicPiDisplay.hint}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              className="grid h-10 w-10 place-items-center rounded-md border border-white/10 bg-white/[0.055] text-slate-100 transition hover:border-cyan/35 hover:bg-cyan/10 disabled:cursor-wait disabled:opacity-60"
              aria-label="Previous track"
              title="Previous track"
              disabled={transportPending}
              onClick={() => handleTransport('previous')}
            >
              <SkipBack size={17} />
            </button>
            <button
              type="button"
              className="grid h-10 w-10 place-items-center rounded-md bg-gold text-slate-950 transition hover:bg-[#ffe08a] disabled:cursor-wait disabled:opacity-60"
              aria-label={transportLabel}
              title={transportLabel}
              disabled={transportPending}
              onClick={() => handleTransport()}
            >
              <TransportIcon size={18} />
            </button>
            <button
              type="button"
              className="grid h-10 w-10 place-items-center rounded-md border border-white/10 bg-white/[0.055] text-slate-100 transition hover:border-cyan/35 hover:bg-cyan/10 disabled:cursor-wait disabled:opacity-60"
              aria-label="Next track"
              title="Next track"
              disabled={transportPending}
              onClick={() => handleTransport('next')}
            >
              <SkipForward size={17} />
            </button>
          </div>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-white/10">
          <motion.div className="h-full bg-gradient-to-r from-cyan to-gold" animate={{ width: `${progressWidth}%` }} />
        </div>
        <div className="mt-2 flex justify-between text-xs text-slate-400 tabular-nums">
          <span className="w-12 font-mono">{formatDuration(displayLoopElapsed)}</span>
          <span className="w-20 text-right font-mono">Loop {formatDuration(loopDuration)}</span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2">
            <p className="text-slate-500">Section</p>
            <p className="mt-1 truncate font-semibold text-white">{frame.music.section}</p>
          </div>
          <div className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2">
            <p className="text-slate-500">Bar / Beat</p>
            <p className="mt-1 font-semibold text-white">{frame.music.lastBar}.{frame.music.lastBeat}</p>
          </div>
          <div className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2">
            <p className="text-slate-500">Beat Power</p>
            <p className="mt-1 font-semibold text-white">{frame.music.beatStrength}%</p>
          </div>
        </div>

      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        {metrics.map((metric) => {
          const Icon = metric.icon
          return (
            <div key={metric.label} className="metric-tile">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-xs text-slate-400">{metric.label}</span>
                <Icon size={15} className="text-cyan" />
              </div>
              <p className="font-display text-2xl font-semibold text-white">
                {metric.value}
                <span className="text-sm text-slate-400">{metric.suffix}</span>
              </p>
            </div>
          )
        })}
      </div>

      <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.04] p-4">
        <p className="text-xs font-semibold uppercase text-slate-400">Gesture Mapping</p>
        <div className="mt-3 space-y-3 text-sm text-slate-200">
          <MappingRow left="Hand height zone" right="Layer select (melody → drums)" />
          <MappingRow left="Fist push direction" right="Start / Stop / BPM" />
          <MappingRow left="Palm push direction" right="Volume up / down" />
        </div>
      </div>
    </div>
  )
}

function MappingRow({ left, right }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span>{left}</span>
      <ChevronRight size={15} className="shrink-0 text-gold" />
      <span className="text-right text-cyan">{right}</span>
    </div>
  )
}

// ── 坐标手势控制台（识别器逐帧状态可视化，替代灯板手势反馈） ─────────────

const COORD_ACTIONS = [
  { key: 'stop', label: '停止', hint: '左拳静置', color: 'from-coral to-gold' },
  { key: 'start', label: '开始', hint: '右拳静置', color: 'from-mint to-cyan' },
  { key: 'vol_up', label: '音量+', hint: '左掌上推', color: 'from-gold to-amber-300' },
  { key: 'vol_down', label: '音量-', hint: '右掌下推', color: 'from-gold to-amber-300' },
  { key: 'bpm_up', label: 'BPM+', hint: '左拳上推', color: 'from-cyan to-gold' },
  { key: 'bpm_down', label: 'BPM-', hint: '右拳下推', color: 'from-cyan to-gold' },
  { key: 'style', label: '风格', hint: '双拳高低差', color: 'from-violet-400 to-cyan' },
  { key: 'zone_on', label: '声部开', hint: '双掌同区', color: 'from-mint to-cyan' },
  { key: 'zone_off', label: '声部关', hint: '双拳同区', color: 'from-coral to-gold' },
]

const HAND_LABEL = {
  fist: { text: '拳 FIST', cls: 'border-gold/40 bg-gold/15 text-gold' },
  palm: { text: '掌 PALM', cls: 'border-cyan/40 bg-cyan/15 text-cyan' },
  unknown: { text: '无手', cls: 'border-white/10 bg-white/[0.04] text-slate-500' },
}

function CoordinateHandCard({ side, hand, zones }) {
  const meta = hand.present ? (HAND_LABEL[hand.label] || HAND_LABEL.unknown) : HAND_LABEL.unknown
  const pushing = hand.present && Math.abs(hand.vy) >= 0.5
  const arrow = !hand.present ? '·' : hand.vy <= -0.5 ? '▲' : hand.vy >= 0.5 ? '▼' : '·'
  return (
    <div className="rounded-lg border border-white/10 bg-black/25 p-3">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase text-slate-400">{side}</p>
        <span className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${meta.cls}`}>
          {meta.text}
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto] items-center gap-3">
        <div className="relative h-36 overflow-hidden rounded-md border border-white/10 bg-black/40">
          {zones.bands.map(([lo, hi], idx) => (
            <div
              key={idx}
              className={`absolute inset-x-0 border-y ${hand.zone === idx
                ? 'border-cyan/50 bg-cyan/20'
                : 'border-white/10 bg-white/[0.05]'}`}
              style={{ top: `${lo * 100}%`, height: `${(hi - lo) * 100}%` }}
            >
              <span className={`absolute left-1 top-0 text-[9px] ${hand.zone === idx ? 'text-cyan' : 'text-slate-500'}`}>
                {zones.layers[idx]}
              </span>
            </div>
          ))}
          {hand.present && (
            <motion.div
              className={`absolute inset-x-0 h-[3px] rounded-full ${hand.label === 'fist' ? 'bg-gold' : 'bg-cyan'}`}
              animate={{ top: `${hand.y * 100}%` }}
              transition={{ type: 'tween', duration: 0.08 }}
              style={{ boxShadow: hand.label === 'fist' ? '0 0 8px #f6c453' : '0 0 8px #38bdf8' }}
            />
          )}
        </div>
        <div className="flex w-12 flex-col items-center gap-1">
          <motion.span
            className={`font-display text-2xl ${pushing ? (hand.vy < 0 ? 'text-cyan' : 'text-gold') : 'text-slate-600'}`}
            animate={pushing ? { y: hand.vy < 0 ? [-2, -6, -2] : [2, 6, 2] } : { y: 0 }}
            transition={pushing ? { repeat: Infinity, duration: 0.7 } : {}}
          >
            {arrow}
          </motion.span>
          <span className="text-[10px] tabular-nums text-slate-500">
            {hand.present ? `${Math.abs(hand.vy).toFixed(1)}/s` : '—'}
          </span>
          <span className="text-[10px] tabular-nums text-slate-500">
            {hand.present ? `开${Math.round(hand.openness * 100)}%` : ''}
          </span>
        </div>
      </div>
    </div>
  )
}

function GestureConsole({ frame }) {
  const coord = frame.coordinate || {}
  const hands = coord.hands || { left: {}, right: {} }
  const progress = coord.progress || {}
  const lastActions = coord.lastActions || []
  const latest = lastActions.length ? lastActions[lastActions.length - 1] : null
  const nowSec = Date.now() / 1000
  const latestAge = latest ? nowSec - Number(latest.at || 0) : Infinity
  const layers = frame.music.layers || {}
  const layerOrder = ['melody', 'harmony', 'bass', 'drums']
  const layerZh = { melody: '旋律', harmony: '和声', bass: '低音', drums: '打击' }

  return (
    <div className="glass-panel mt-4 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm font-semibold text-white">
          <Hand size={16} className="text-cyan" />
          Gesture Conducting Console
          <span className="text-xs font-normal text-slate-400">坐标手势 · 逐帧规则识别</span>
        </p>
        <div className="flex flex-wrap gap-2">
          <span className="status-pill">
            <StatusDot tone={coord.enabled ? 'green' : 'gold'} />
            {coord.enabled ? `Recognizer ${coord.fps} fps` : 'Recognizer Standby'}
          </span>
          {coord.anchor && coord.anchor.mode !== 'off' && (
            <span className="status-pill" title="Micro:bit 锚点：无活性锚点时不识别任何手势">
              <StatusDot tone={coord.anchor.active ? 'green' : 'red'} />
              {coord.anchor.active
                ? `Anchor L${coord.anchor.left_live ? '●' : '○'} R${coord.anchor.right_live ? '●' : '○'}`
                : 'Micro:bit anchor missing — gestures disabled'}
            </span>
          )}
          <span className="status-pill">{frame.music.style}</span>
          <span className="status-pill">
            Track {Number(frame.music.trackIndex || 0) + 1}/{frame.music.trackCount || 1}
          </span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.25fr_0.9fr]">
        <CoordinateHandCard side="LEFT HAND" hand={hands.left || {}} zones={{ bands: [], layers: [] }} />

        <div className="rounded-lg border border-white/10 bg-black/25 p-3">
          <p className="mb-3 text-xs font-semibold uppercase text-slate-400">
            Action Triggers <span className="ml-1 font-normal text-slate-500">持续帧进度 → 触发</span>
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {COORD_ACTIONS.map((action) => {
              const value = Math.round(Math.min(1, Number(progress[action.key] || 0)) * 100)
              const fired = latest && latest.name === action.key && latestAge < 2
              return (
                <div
                  key={action.key}
                  className={`rounded-md border px-2.5 py-2 transition ${fired
                    ? 'border-gold/60 bg-gold/15'
                    : 'border-white/10 bg-white/[0.03]'}`}
                >
                  <div className="mb-1 flex items-center justify-between text-[11px]">
                    <span className={fired ? 'font-semibold text-gold' : 'text-slate-300'}>
                      {action.label}
                      {fired ? ' ✦' : ''}
                    </span>
                    <span className="text-slate-500">{action.hint}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                    <motion.div
                      className={`h-full rounded-full bg-gradient-to-r ${action.color}`}
                      animate={{ width: `${value}%` }}
                      transition={{ type: 'tween', duration: 0.1 }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-white/10 pt-2 text-[11px] text-slate-400">
            <span>
              最近触发: {latest && latestAge < 30
                ? `${COORD_ACTIONS.find((a) => a.key === latest.name)?.label || latest.name}${latest.layer ? ` · ${latest.layer}` : ''}${latest.direction ? ` · ${latest.direction}` : ''}`
                : '—'}
            </span>
            <span>{latest && latestAge < 30 ? `${latestAge.toFixed(1)}s 前` : ''}</span>
          </div>
        </div>

        <CoordinateHandCard side="RIGHT HAND" hand={hands.right || {}} zones={{ bands: [], layers: [] }} />
      </div>

      <div className="mt-4 rounded-lg border border-white/10 bg-black/25 p-3">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase text-slate-400">
            <Layers size={13} className="text-cyan" />
            Voice Layers
          </p>
          <span className="text-xs tabular-nums text-slate-400">
            {layerOrder.filter((name) => layers[name] !== false).length}/4 ON · BPM {frame.music.bpm} · VOL {frame.music.volume}%
          </span>
        </div>
        <div className="grid gap-2 sm:grid-cols-4">
          {layerOrder.map((name) => {
            const on = layers[name] !== false
            return (
              <motion.div
                key={name}
                layout
                className={`flex items-center justify-between rounded-md border px-3 py-2 text-xs font-semibold transition ${
                  on
                    ? 'border-cyan/40 bg-cyan/15 text-cyan'
                    : 'border-white/10 bg-white/[0.03] text-slate-500'
                }`}
              >
                <span>{layerZh[name]} {name}</span>
                <span className={`rounded px-1.5 py-0.5 text-[10px] ${on ? 'bg-cyan/15 text-cyan' : 'bg-white/[0.05] text-slate-500'}`}>
                  {on ? 'ON' : 'OFF'}
                </span>
              </motion.div>
            )
          })}
        </div>
      </div>

    </div>
  )
}


function MicrobitCard({ side, data, color }) {
  const accent = color === 'cyan' ? 'text-cyan border-cyan/25 bg-cyan/10' : 'text-gold border-gold/25 bg-gold/10'
  return (
    <div className="glass-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold text-white">
            <Radio size={16} className={color === 'cyan' ? 'text-cyan' : 'text-gold'} />
            {side}
          </p>
          <p className="mt-1 text-xs text-slate-400">{data.id} via BLE broadcast / ESP32 gateway</p>
        </div>
        <span className={`rounded-md border px-3 py-1 text-xs font-semibold ${accent}`}>{data.signal}</span>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-[0.8fr_1.2fr]">
        <AssetPlaceholder title="Device photo placeholder" path="/media/microbit-wrist.jpg" note="替换为真实 Micro:bit 佩戴照片。" type="image" />
        <div className="grid grid-cols-3 gap-3">
          {['x', 'y', 'z'].map((axis) => (
            <div key={axis} className="metric-tile">
              <p className="text-xs uppercase text-slate-400">{axis}</p>
              <p className="mt-2 font-display text-2xl font-semibold text-white">{data[axis]}g</p>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
        <div className="metric-tile">
          <p className="text-slate-400">Motion</p>
          <p className="mt-1 font-semibold text-white">{data.motion}</p>
        </div>
        <div className="metric-tile">
          <p className="text-slate-400">Battery</p>
          <p className="mt-1 font-semibold text-white">{data.battery}%</p>
        </div>
        <div className="metric-tile">
          <p className="text-slate-400">Signal</p>
          <p className="mt-1 font-semibold text-white">{data.signal}</p>
        </div>
      </div>
    </div>
  )
}

function InferenceLog({ logs }) {
  return (
    <div className="glass-panel p-5">
      <p className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
        <Clock size={16} className="text-gold" />
        AI Inference Log
      </p>
      <div className="space-y-2 font-mono text-xs text-slate-300">
        {logs.map((line) => (
          <p key={line} className="rounded-md border border-white/10 bg-black/25 px-3 py-2">
            {line}
          </p>
        ))}
      </div>
    </div>
  )
}

function DecisionFlow({ frame, connectionState }) {
  return (
    <section id="ai-flow" className="section-shell">
      <SectionHeader
        eyebrow="AI Intelligence"
        title="AI Decision Flow"
        description="Camera tracking and Micro:bit motion signals are fused so the system can understand conducting intention while the performance is happening."
        icon={Brain}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_0.8fr]">
        <div className="glass-panel p-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {flowSteps.map((step, index) => (
              <motion.div
                key={step.name}
                initial={{ opacity: 0, y: 12 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.4 }}
                transition={{ delay: index * 0.04 }}
                className="relative rounded-lg border border-white/10 bg-white/[0.045] p-4"
              >
                <div className="mb-4 flex items-center justify-between">
                  <span className="rounded-md border border-cyan/25 bg-cyan/10 px-2 py-1 text-xs text-cyan">{step.layer}</span>
                  <StatusDot tone={index <= 5 ? 'green' : 'gold'} />
                </div>
                <p className="text-sm font-semibold text-white">{step.name}</p>
                <p className="mt-2 text-xs leading-5 text-slate-400">{step.detail}</p>
              </motion.div>
            ))}
          </div>
        </div>

        <div className="glass-panel p-5">
          <p className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
            <Wifi size={16} className="text-cyan" />
            Frontend Payload Preview
          </p>
          <pre className="max-h-[430px] overflow-auto rounded-lg border border-white/10 bg-black/35 p-4 text-xs leading-5 text-slate-200">
            {JSON.stringify(
              {
                timestamp: frame.timestamp,
                camera: frame.camera,
                microbit: {
                  leftAcceleration: frame.microbit.left.y,
                  rightAcceleration: frame.microbit.right.y,
                },
                prediction: {
                  gesture: frame.prediction.gesture,
                  confidence: frame.prediction.confidence / 100,
                },
                music: frame.music,
                latency: frame.connection.latency,
                piGateway: {
                  status: frame.connection.piGateway,
                  listen: frame.connection.piGatewayHost,
                  lastMessage: frame.connection.piLastMessage,
                  messageCounts: frame.connection.piMessageCounts,
                  lastError: frame.connection.piLastError,
                },
                connectionState,
              },
              null,
              2,
            )}
          </pre>
        </div>
      </div>
    </section>
  )
}

function ArchitectureView() {
  const rows = [
    { icon: Camera, title: 'Sensing Layer', items: ['Pi Camera', 'Micro:bit L/R', 'Wrist IMU + Buttons'] },
    { icon: Server, title: 'Edge Gateway Layer', items: ['ESP32 BLE Gateway', 'UDP 17778', 'Pi Fusion Pipeline', 'TCP JSONL 9000'] },
    { icon: Cpu, title: 'AI and Logic Layer', items: ['MediaPipe Landmarks', 'Gesture Event Engine', 'Music Mapping Engine'] },
    { icon: Database, title: 'PC Backend Layer', items: ['Flask REST API', 'Live State Router', 'SQLite Logging'] },
    { icon: Music2, title: 'Performance Output Layer', items: ['Sonic Pi OSC', 'Speaker Output', 'RGB LED Matrix'] },
  ]

  return (
    <section id="architecture" className="section-shell">
      <SectionHeader
        eyebrow="System Architecture"
        title="System Architecture"
        description="A real data path from Pi Camera and Micro:bit sensing to Raspberry Pi fusion, PC backend control, Sonic Pi output, LED feedback, and database logging."
        icon={Network}
      />

      <div className="glass-panel p-5">
        <div className="grid gap-4 lg:grid-cols-5">
          {rows.map((row, index) => {
            const Icon = row.icon
            return (
              <div key={row.title} className="relative rounded-lg border border-white/10 bg-white/[0.045] p-4">
                <div className="mb-4 flex items-center justify-between">
                  <div className="grid h-10 w-10 place-items-center rounded-md border border-cyan/25 bg-cyan/10 text-cyan">
                    <Icon size={18} />
                  </div>
                  {index < rows.length - 1 ? <ChevronRight className="hidden text-gold lg:block" size={20} /> : null}
                </div>
                <p className="font-semibold text-white">{row.title}</p>
                <div className="mt-4 space-y-2">
                  {row.items.map((item) => (
                    <div key={item} className="rounded-md border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-300">
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function CalibrationTraining() {
  return (
    <section id="training" className="section-shell">
      <SectionHeader
        eyebrow="Calibration & Training"
        title="Calibration and Training Mode"
        description="Before performance, the system can learn the performer's hand range and motion baseline so recognition feels more stable and personal."
        icon={Settings}
      />

      <div className="grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
        <div className="glass-panel p-5">
          <p className="mb-4 text-sm font-semibold text-white">Calibration Checklist</p>
          <div className="space-y-3">
            {trainingSteps.map((step) => (
              <div key={step.label} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.04] px-4 py-3">
                <span className="text-sm text-slate-200">{step.label}</span>
                <span className={`grid h-6 w-6 place-items-center rounded-md ${step.done ? 'bg-mint text-slate-950' : 'border border-gold/35 text-gold'}`}>
                  {step.done ? <Check size={14} /> : <RefreshCw size={13} />}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-panel p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-white">Gesture Collection Task</p>
              <p className="mt-1 text-xs text-slate-400">Label: Volume Up · Plan: 10 samples · Completed: 6</p>
            </div>
            <button type="button" className="secondary-button">
              <Radio size={15} />
              Start Recording
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            {[
              ['Sample Quality', 'Good'],
              ['Duration', '1.2 s'],
              ['Acceleration Peak', '2.03 g'],
              ['Camera Tracking', '97%'],
            ].map(([label, value]) => (
              <div key={label} className="metric-tile">
                <p className="text-xs text-slate-400">{label}</p>
                <p className="mt-2 font-semibold text-white">{value}</p>
              </div>
            ))}
          </div>

          <div className="mt-5 h-72">
            <ResponsiveContainer>
              <AreaChart data={analyticsSeries}>
                <defs>
                  <linearGradient id="accelGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.65} />
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                <XAxis dataKey="tick" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Area type="monotone" dataKey="acceleration" stroke="#38bdf8" fill="url(#accelGradient)" strokeWidth={3} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </section>
  )
}

function AboutProject() {
  const cards = [
    ['Problem', 'Traditional music control relies on keyboards, mice, and touchscreens, making it difficult to capture rhythm, intensity, and expression from real conducting gestures.'],
    ['Solution', 'The system captures two-hand motion through a camera and Micro:bit devices, uses a local AI model to recognize conducting intent, and converts that intent into music control commands in real time.'],
    ['Innovation', 'Contactless Interaction · Multi-sensor Fusion · Edge AI Inference · Real-time Music Control · Persistent Data Analytics'],
    ['Application', 'Music education, conductor training, interactive exhibitions, creative performance, accessible music interaction, entertainment, and digital art.'],
  ]

  return (
    <section id="about" className="section-shell pb-20">
      <SectionHeader
        eyebrow="Project About"
        title="Project Overview and Media Slots"
        description="This section keeps the core proposal concept while reserving clear locations for the real videos and photos that will be added before the roadshow."
        icon={Home}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_0.85fr]">
        <div className="grid gap-4 sm:grid-cols-2">
          {cards.map(([title, body]) => (
            <div key={title} className="glass-panel p-5">
              <p className="mb-3 text-sm font-semibold text-gold">{title}</p>
              <p className="text-sm leading-6 text-slate-300">{body}</p>
            </div>
          ))}
        </div>
        <div className="glass-panel p-5">
          <p className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
            <Layers size={16} className="text-cyan" />
            Reserved Media Slots
          </p>
          <div className="space-y-3">
            {assetSlots.map((slot, index) => (
              <AssetPlaceholder
                key={slot.path}
                title={slot.title}
                path={slot.path}
                note={slot.note}
                type={slot.type || (index === 0 || index === 1 ? 'video' : 'image')}
              />
            ))}
          </div>
          <div className="mt-5 rounded-lg border border-dashed border-gold/30 bg-gold/5 p-4">
            <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
              <Server size={16} className="text-gold" />
              Reserved Interface Slots
            </p>
            <div className="space-y-3">
              {reservedInterfaceSlots.map((slot) => (
                <div key={slot.field} className="rounded-md border border-white/10 bg-black/20 p-3">
                  <p className="text-sm font-semibold text-white">{slot.title}</p>
                  <p className="mt-1 font-mono text-[11px] text-gold">{slot.field}</p>
                  <p className="mt-1 font-mono text-[11px] text-slate-500">fallback: {slot.fallback}</p>
                  <p className="mt-2 text-xs leading-5 text-slate-300">{slot.note}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

// Maps a coordinate-recognizer action name to visitor-friendly text —
// shared from conductorData (imported above).

function ExperienceMode({ open, onClose, frame, onTransport }) {
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [transportPending, setTransportPending] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const [sessionActive, setSessionActive] = useState(false)
  const [guestPlaybackActive, setGuestPlaybackActive] = useState(false)
  const scenario = experienceScenarios[selectedIndex]
  const liveInputReady = Boolean(
    frame.camera?.hasLiveLandmarks ||
    frame.camera?.hasLiveVideo ||
    frame.connection.piGatewayConnected,
  )
  const displayBpm = Math.max(72, Math.min(148, Number(frame.music.bpm || 108) + scenario.bpmOffset))
  const displayPlaying = liveInputReady ? frame.music.playing : guestPlaybackActive && scenario.gesture !== 'stop'
  const fallbackFrame = {
    ...frame,
    prediction: {
      ...frame.prediction,
      gesture: scenario.gesture,
      label: scenario.label.toUpperCase(),
      confidence: 94,
      response: scenario.effect,
      top3: [
        { label: scenario.label, value: 93 },
        { label: 'Idle', value: 4 },
        { label: 'Tempo Hold', value: 2 },
      ],
    },
    music: {
      ...frame.music,
      bpm: displayBpm,
      volume: scenario.volume,
      energy: scenario.energy,
      density: scenario.gesture === 'bpm_up' ? 72 : scenario.gesture === 'vol_up' ? 68 : scenario.gesture === 'stop' ? 22 : 52,
      playing: displayPlaying,
      beatStrength: scenario.gesture === 'start' ? 100 : frame.music.beatStrength,
    },
  }
  const displayFrame = liveInputReady ? frame : fallbackFrame
  const lastCoordinateAction = frame.coordinate?.lastActions?.length
    ? frame.coordinate.lastActions[frame.coordinate.lastActions.length - 1]
    : null
  const coordinateAction = lastCoordinateAction && (Date.now() / 1000 - Number(lastCoordinateAction.at || 0)) < 12
    ? describeCoordinateAction(lastCoordinateAction.name)
    : null
  const sonicPiDisplay = getSonicPiDisplayState(frame.music)
  const experienceMusicStatus = frame.music.sonicPiConnected
    ? displayFrame.music.playing ? 'Playing' : 'Paused'
    : sonicPiDisplay.label
  const activeExperience = liveInputReady
    ? {
        label: coordinateAction ? coordinateAction[0].toUpperCase() : frame.prediction.label,
        subtitle: coordinateAction ? 'Coordinate recognizer · live rule-based input' : 'Real camera + Micro:bit input',
        effect: coordinateAction ? coordinateAction[1] : frame.prediction.response,
        color: '#38bdf8',
      }
    : scenario
  const fallbackLedAction = scenario.gesture === 'stop'
    ? 'Red stop flash'
    : scenario.gesture === 'vol_up'
      ? 'Volume wave up'
      : scenario.gesture === 'bpm_up'
        ? 'Tempo meter sweep'
        : 'Start flash'
  const liveLedBrightness = Number(displayFrame.actuation?.led?.brightness || 0)
  const liveLedBrightnessPct = liveLedBrightness <= 1 ? Math.round(liveLedBrightness * 100) : Math.round(liveLedBrightness)
  const liveLed = displayFrame.actuation?.led?.pattern
    ? `${displayFrame.actuation.led.pattern} · ${liveLedBrightnessPct}%`
    : 'LED Ready'
  const experienceLedAction = liveInputReady ? liveLed.replace(/\s.\s(?=\d+%$)/, ' ') : fallbackLedAction
  const databaseCell = displayFrame.actuation?.databaseSaved || frame.connection.backend === 'REST Online' ? 'Saved' : 'Ready'
  const experienceActionChain = liveInputReady && coordinateAction
    ? [
        ['Detected Action', coordinateAction[0]],
        ['Recognizer', `Rules ${frame.coordinate?.fps || 0} fps`],
        ['Music Action', coordinateAction[1]],
        ['LED Action', experienceLedAction],
        ['Database', databaseCell],
      ]
    : [
        ['Detected Gesture', displayFrame.prediction.label],
        ['AI Confidence', `${displayFrame.prediction.confidence}%`],
        ['Music Action', liveInputReady ? displayFrame.prediction.response : scenario.effect],
        ['LED Action', experienceLedAction],
        ['Database', databaseCell],
      ]
  const guestStatus = countdown > 0 ? `Starting in ${countdown}` : sessionActive ? 'Guest Session Live' : 'Ready for Guest'
  const trackStyleLists = {
    shape_of_you: ['acoustic_pop', 'tropical_house', 'festival_edm'],
    world_is_mine: ['piano_pop', 'vocaloid_electro', 'rock_band'],
  }
  const styleList = trackStyleLists[displayFrame.music.trackId] || trackStyleLists.shape_of_you
  const styleKey = String(displayFrame.music.style || '').toLowerCase().replace(/[\s-]+/g, '_')
  const styleIndex = Math.max(0, styleList.indexOf(styleKey))
  const layersOn = Object.values(displayFrame.music.layers || {}).filter(Boolean).length
  const handsPresent = [displayFrame.coordinate?.hands?.left?.present, displayFrame.coordinate?.hands?.right?.present]
  const handsCount = handsPresent.filter(Boolean).length
  const handsValue = handsCount === 2 ? 'L + R' : handsCount === 1 ? (handsPresent[0] ? 'Left' : 'Right') : 'None'
  const musicParameterVisuals = [
    {
      label: 'BPM',
      value: displayFrame.music.bpm,
      source: 'Left fist up = BPM + · right fist down = BPM −',
      bar: Math.min(100, Math.max(0, ((Number(displayFrame.music.bpm) - 60) / 120) * 100)),
      color: 'from-cyan to-gold',
    },
    {
      label: 'Volume',
      value: `${displayFrame.music.volume}%`,
      source: 'Left palm up = louder · right palm down = quieter',
      bar: displayFrame.music.volume,
      color: 'from-gold to-amber-300',
    },
    {
      label: 'Style',
      value: displayFrame.music.style,
      source: 'Both fists: left high = previous · right high = next',
      bar: ((styleIndex + 1) / styleList.length) * 100,
      color: 'from-mint to-cyan',
    },
    {
      label: 'Layers',
      value: `${layersOn}/4 on`,
      source: 'Two palms in a zone = layer on · two fists = layer off',
      bar: (layersOn / 4) * 100,
      color: 'from-violet-400 to-cyan',
    },
    {
      label: 'Beat Power',
      value: `${displayFrame.music.beatStrength}%`,
      source: 'Live beat feedback from Sonic Pi',
      bar: displayFrame.music.beatStrength,
      color: 'from-coral to-gold',
    },
    {
      label: 'Hands',
      value: handsValue,
      source: 'Put both hands inside the Pi camera view',
      bar: (handsCount / 2) * 100,
      color: 'from-cyan to-mint',
    },
  ]
  const gestureGuide = [
    ['Right fist', 'Start the music'],
    ['Left fist', 'Stop the music'],
    ['Left palm push up', 'Volume up'],
    ['Right palm push down', 'Volume down'],
    ['Left fist push up', 'BPM up'],
    ['Right fist push down', 'BPM down'],
    ['Both fists · left high', 'Previous style'],
    ['Both fists · right high', 'Next style'],
    ['Two palms in a zone', 'Layer ON · zones top to bottom: melody, harmony, bass, drums'],
    ['Two fists in a zone', 'Layer OFF · same zones'],
  ]

  useEffect(() => {
    if (!open) {
      setCountdown(0)
      setSessionActive(false)
      setGuestPlaybackActive(false)
    }
  }, [open])

  useEffect(() => {
    if (countdown <= 0) return undefined
    const timer = window.setTimeout(() => {
      setCountdown((value) => {
        const next = Math.max(0, value - 1)
        if (next === 0) setSessionActive(true)
        return next
      })
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [countdown])

  useEffect(() => {
    if (!sessionActive) return undefined
    const timer = window.setTimeout(() => {
      setSessionActive(false)
      setGuestPlaybackActive(false)
      setSelectedIndex(0)
    }, 45000)
    return () => window.clearTimeout(timer)
  }, [sessionActive])

  const startGuestSession = () => {
    setSelectedIndex(0)
    setSessionActive(true)
    setGuestPlaybackActive(true)
    setCountdown(0)
    void handleTransport('start')
  }

  const pauseGuestMusic = () => {
    setGuestPlaybackActive(false)
    void handleTransport('pause')
  }

  const resetGuestSession = () => {
    setCountdown(0)
    setSessionActive(false)
    setGuestPlaybackActive(false)
    setSelectedIndex(0)
    void handleTransport('reset')
  }

  async function handleTransport(action) {
    if (!onTransport || transportPending) return
    setTransportPending(true)
    try {
      await onTransport(action)
    } catch (error) {
      console.error(error)
    } finally {
      setTransportPending(false)
    }
  }

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 overflow-hidden presentation-backdrop px-3 py-1.5 text-slate-100 sm:px-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="mx-auto flex h-full max-w-7xl flex-col">
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-1.5">
              <div>
                <p className="eyebrow">
                  <Sparkles size={14} />
                  Visitor Experience
                </p>
                <h2 className="mt-1 font-display text-2xl font-semibold text-white sm:text-3xl">
                  Try Conducting the System
                </h2>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="status-pill">
                  <StatusDot tone={sessionActive ? 'green' : countdown > 0 ? 'gold' : 'cyan'} />
                  {guestStatus}
                </span>
                <span className="status-pill">
                  <StatusDot tone={liveInputReady ? 'green' : 'gold'} />
                  {liveInputReady ? 'Real Input Ready' : 'Gesture Preview Ready'}
                </span>
                <button type="button" className="secondary-button" onClick={onClose}>
                  <X size={16} />
                  Exit
                </button>
              </div>
            </div>

            <div className="grid min-h-0 flex-1 content-start gap-3 py-1.5">
              <div className="grid min-h-0 items-start gap-3 xl:grid-cols-[1.12fr_0.88fr]">
                <div className="glass-panel flex min-h-0 flex-col p-3">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-white">{activeExperience.label}</p>
                    <p className="mt-1 text-xs text-slate-400">{activeExperience.subtitle}</p>
                  </div>
                  <span className="status-pill" style={{ borderColor: `${activeExperience.color}66`, color: activeExperience.color }}>
                    {activeExperience.effect}
                  </span>
                </div>
                <div className="relative min-h-0 flex-1">
                  <ConductorSignalScene frame={displayFrame} heightClass="h-[48vh] min-h-[300px] max-h-[560px]" />
                  {countdown > 0 ? (
                    <div className="absolute inset-0 grid place-items-center rounded-lg bg-black/55 backdrop-blur-sm">
                      <div className="text-center">
                        <p className="text-xs font-semibold uppercase text-cyan">Guest session starts in</p>
                        <p className="mt-2 font-display text-7xl font-semibold text-white">{countdown}</p>
                      </div>
                    </div>
                  ) : null}
                </div>
                <div className="mt-2 grid grid-cols-4 gap-2">
                  {['melody', 'harmony', 'bass', 'drums'].map((layer) => {
                    const layerOn = Boolean(displayFrame.music?.layers?.[layer])
                    return (
                      <div key={layer} className={`rounded-md border px-2 py-1 text-center transition ${layerOn ? 'border-cyan/45 bg-cyan/10' : 'border-white/10 bg-white/[0.04]'}`}>
                        <p className="text-[10px] uppercase tracking-wide text-slate-400">{layer}</p>
                        <p className={`text-sm font-semibold ${layerOn ? 'text-cyan' : 'text-slate-500'}`}>{layerOn ? 'ON' : 'OFF'}</p>
                      </div>
                    )
                  })}
                </div>
                </div>

                <div className="grid min-h-0 gap-2 xl:grid-rows-[auto_auto_minmax(0,1fr)]">
                <div className="glass-panel p-2.5">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="flex items-center gap-2 text-sm font-semibold text-white">
                      <Hand size={16} className="text-gold" />
                      Gesture Control Guide
                    </p>
                    <span className="status-pill">Follow the Pi camera view</span>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {gestureGuide.map(([gesture, result], index) => (
                      <div key={gesture} className="rounded-md border border-white/10 bg-white/[0.045] p-2">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-white">{gesture}</p>
                          <span className="font-mono text-[11px] text-gold">{String(index + 1).padStart(2, '0')}</span>
                        </div>
                        <p className="text-xs leading-5 text-slate-300">{result}</p>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 rounded-md border border-dashed border-cyan/25 bg-cyan/5 p-2">
                    <p className="text-xs leading-5 text-slate-300">
                      Stand inside the Pi camera area. Move slowly first, then make a clear gesture and watch the music parameters change below the video.
                    </p>
                  </div>
                  {!liveInputReady ? (
                    <div className="mt-2 grid gap-2 sm:grid-cols-4">
                      {experienceScenarios.map((item, index) => (
                        <button
                          key={item.gesture}
                          type="button"
                          className={`rounded-md border px-3 py-1.5 text-left transition ${
                            index === selectedIndex
                              ? 'border-gold/50 bg-gold/10'
                              : 'border-white/10 bg-white/[0.045] hover:border-cyan/35 hover:bg-cyan/10'
                          }`}
                          onClick={() => setSelectedIndex(index)}
                        >
                          <span className="mb-2 block h-1 w-10 rounded-full" style={{ backgroundColor: item.color }} />
                          <p className="text-xs font-semibold text-white">{item.label}</p>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className="glass-panel p-2.5">
                  <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-white">
                    <Zap size={16} className="text-cyan" />
                    Live Action Chain
                  </p>
                  <div className="grid gap-2 sm:grid-cols-5 xl:grid-cols-5">
                    {experienceActionChain.map(([label, value]) => (
                      <div key={label} className="rounded-md border border-white/10 bg-white/[0.045] px-2 py-1.5">
                        <p className="truncate text-[10px] uppercase text-slate-500">{label}</p>
                        <p className="mt-1 truncate text-xs font-semibold text-white">{value}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="glass-panel flex min-h-0 flex-col p-2.5">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="flex items-center gap-2 text-sm font-semibold text-white">
                    <Music2 size={16} className="text-gold" />
                    Music Control
                    </p>
                    <span className={frame.music.sonicPiConnected ? 'status-pill' : sonicPiDisplay.pillClass}>
                      {experienceMusicStatus}
                    </span>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-5">
                    <button type="button" className="primary-button py-2" disabled={transportPending} onClick={startGuestSession}>
                      <Sparkles size={16} />
                      Start Guest
                    </button>
                    <button type="button" className="secondary-button py-2" disabled={transportPending} onClick={() => handleTransport('previous')}>
                      <SkipBack size={16} />
                      Prev
                    </button>
                    <button type="button" className="secondary-button py-2" disabled={transportPending} onClick={pauseGuestMusic}>
                      <Pause size={16} />
                      Pause
                    </button>
                    <button type="button" className="secondary-button py-2" disabled={transportPending} onClick={() => handleTransport('next')}>
                      <SkipForward size={16} />
                      Next
                    </button>
                    <button type="button" className="secondary-button py-2" disabled={transportPending} onClick={resetGuestSession}>
                      <RefreshCw size={16} />
                      Reset
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {[
                      ['Pi Camera', frame.camera?.hasLiveVideo ? 'Live' : 'Preview'],
                      ['Landmarks', frame.camera?.hasLiveLandmarks ? `${frame.camera.hands.length} Hands` : 'Preview'],
                      ['Sonic Pi', frame.music.sonicPiConnected ? 'Live' : sonicPiDisplay.label],
                    ].map(([label, value]) => (
                      <span key={label} className="status-pill">
                        <span className="text-slate-500">{label}</span>
                        <span className="font-semibold text-white">{value}</span>
                      </span>
                    ))}
                  </div>
                  <div className="mt-2 grid flex-1 min-h-[72px] gap-2 rounded-md border border-white/10 bg-black/20 p-2 sm:grid-cols-[0.9fr_1.1fr]">
                    <div>
                      <p className="text-[10px] uppercase text-slate-500">Current Track</p>
                      <p className="mt-1 truncate text-sm font-semibold text-white">{displayFrame.music.title}</p>
                      <p className="mt-1 font-mono text-[11px] text-slate-400">
                        {displayFrame.music.bpm} BPM / {displayFrame.music.section}
                      </p>
                    </div>
                    <div className="flex items-end gap-1">
                      {Array.from({ length: 18 }, (_, index) => (
                        <span
                          key={index}
                          className="flex-1 rounded-t-sm bg-gradient-to-t from-cyan to-gold"
                          style={{
                            height: `${30 + ((index * 17 + displayFrame.music.beatStrength) % 56)}%`,
                            opacity: index % 4 === 0 ? 1 : 0.62,
                          }}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              </div>

              <div className="glass-panel p-2.5">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="flex items-center gap-2 text-sm font-semibold text-white">
                    <SlidersHorizontal size={16} className="text-cyan" />
                    Music Parameter Visualization
                  </p>
                  <span className="status-pill">{displayFrame.music.title}</span>
                </div>
                <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
                  {musicParameterVisuals.map((item) => (
                    <div key={item.label} className="rounded-md border border-white/10 bg-white/[0.045] p-2.5">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-[10px] uppercase text-slate-500">{item.label}</p>
                          <p className="mt-1 font-display text-xl font-semibold text-white">{item.value}</p>
                        </div>
                        <span className="rounded-md border border-white/10 bg-black/25 px-1.5 py-0.5 text-[9px] uppercase text-slate-400">
                          Live
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
                        <motion.div className={`h-full bg-gradient-to-r ${item.color}`} animate={{ width: `${item.bar}%` }} />
                      </div>
                      <p className="mt-1.5 line-clamp-2 text-[10px] leading-4 text-slate-400">{item.source}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}

function RoadshowVideoModal({ open, onClose }) {
  const [videoError, setVideoError] = useState(false)
  const videoSlot = assetSlots[0]

  useEffect(() => {
    if (open) setVideoError(false)
  }, [open])

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 overflow-y-auto bg-black/85 px-4 py-6 text-slate-100 backdrop-blur"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="mx-auto flex min-h-full max-w-6xl flex-col">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="eyebrow">
                  <Video size={14} />
                  Prepared Roadshow Video
                </p>
                <h2 className="mt-3 font-display text-3xl font-semibold text-white sm:text-5xl">
                  Recorded Demo Opening
                </h2>
              </div>
              <button type="button" className="secondary-button" onClick={onClose}>
                <X size={16} />
                Exit
              </button>
            </div>

            <div className="glass-panel flex-1 p-5">
              {!videoError ? (
                <video
                  className="aspect-video w-full rounded-lg border border-white/10 bg-black object-contain"
                  src={videoSlot.path}
                  controls
                  playsInline
                  onError={() => setVideoError(true)}
                />
              ) : (
                <div className="grid min-h-[52vh] place-items-center rounded-lg border border-dashed border-cyan/35 bg-cyan/5 p-6 text-center">
                  <div className="max-w-xl">
                    <div className="mx-auto grid h-14 w-14 place-items-center rounded-md border border-cyan/30 bg-cyan/10 text-cyan">
                      <Video size={26} />
                    </div>
                    <p className="mt-5 text-xl font-semibold text-white">{videoSlot.title}</p>
                    <p className="mt-2 font-mono text-sm text-cyan">{videoSlot.path}</p>
                    <p className="mt-4 text-sm leading-6 text-slate-300">{videoSlot.note}</p>
                  </div>
                </div>
              )}
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {[
                  ['Gesture Input', 'The conductor moves naturally instead of using keyboard or touch controls.'],
                  ['AI Understanding', 'Camera and Micro:bit signals are fused into one conducting intention.'],
                  ['Live Music', 'Sonic Pi turns the recognized intention into changing tempo, volume, and rhythm.'],
                ].map(([title, body]) => (
                  <div key={title} className="rounded-md border border-white/10 bg-white/[0.045] p-4">
                    <p className="text-sm font-semibold text-white">{title}</p>
                    <p className="mt-2 text-xs leading-5 text-slate-400">{body}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}

function PresentationMode({ open, onClose, frame, onTransport }) {
  const [step, setStep] = useState(0)
  const [presentationVideoError, setPresentationVideoError] = useState(false)
  const [transportPending, setTransportPending] = useState(false)
  const videoSlot = assetSlots[0]
  const steps = [
    { title: 'Prepared Video', headline: 'Recorded Demo Opening', sub: 'A complete preview of gesture-driven music interaction.', icon: Video },
    { title: 'Workflow', headline: 'Technology Stack and Work Chain', sub: 'From hand motion to musical response in one connected loop.', icon: Network },
    { title: 'Music Control', headline: 'Gesture Changes Music Parameters', sub: 'BPM, volume, energy, density, and beat power update from hand movement.', icon: Activity },
    { title: 'Guest Mode', headline: 'Audience Interaction Mode', sub: 'Visitors can step in, follow gesture cues, and control the music.', icon: Sparkles },
    { title: 'Live Demo', headline: 'Live Raspberry Pi Performance', sub: 'The real camera, sensors, AI, and Sonic Pi perform together.', icon: Camera },
  ]
  const current = steps[step]
  const StepIcon = current.icon
  const PresentationTransportIcon = frame.music.playing ? Pause : Play
  const presentationTransportAction = frame.music.playing ? 'pause' : 'start'
  const presentationTransportLabel = frame.music.playing ? 'Pause Music' : 'Play Music'
  const presentationTitles = steps.map((item) => item.title)
  const sonicPiDisplay = getSonicPiDisplayState(frame.music)
  const presentationMusicStatus = frame.music.sonicPiConnected
    ? frame.music.playing ? 'Playing' : 'Paused'
    : sonicPiDisplay.label
  const microbitLive = [frame.microbit.left.signal, frame.microbit.right.signal].some((value) => !/waiting/i.test(String(value)))
  const musicParameterTiles = [
    {
      label: 'BPM',
      value: frame.music.bpm,
      source: 'Right-hand beat / strike',
      tone: 'text-cyan',
      bar: Math.min(100, Math.max(0, ((Number(frame.music.bpm) - 72) / 76) * 100)),
    },
    {
      label: 'Volume',
      value: `${frame.music.volume}%`,
      source: 'Left-hand height',
      tone: 'text-gold',
      bar: frame.music.volume,
    },
    {
      label: 'Energy',
      value: `${frame.music.energy}%`,
      source: 'Motion intensity',
      tone: 'text-mint',
      bar: frame.music.energy,
    },
    {
      label: 'Density',
      value: `${frame.music.density}%`,
      source: 'Gesture duration',
      tone: 'text-violet-300',
      bar: frame.music.density,
    },
    {
      label: 'Beat Power',
      value: `${frame.music.beatStrength}%`,
      source: 'Acceleration peak',
      tone: 'text-coral',
      bar: frame.music.beatStrength,
    },
    {
      label: 'Section',
      value: frame.music.section,
      source: 'Gesture event',
      tone: 'text-white',
      bar: frame.music.playing ? 100 : 45,
    },
  ]
  const actionChain = [
    ['Gesture', frame.prediction.label],
    ['Confidence', `${frame.prediction.confidence}%`],
    ['Music', frame.prediction.response],
    ['LED', frame.actuation?.led?.pattern || 'Ready'],
    ['Database', frame.actuation?.databaseSaved || frame.connection.backend === 'REST Online' ? 'Saved' : 'Ready'],
  ]
  const workflowItems = [
    ['Pi Camera + MediaPipe', 'Captures the performer and extracts hand landmarks on Raspberry Pi.'],
    ['Micro:bit + ESP32', 'Two wrist Micro:bits broadcast motion packets through the ESP32 UDP gateway.'],
    ['Pi Fusion Pipeline', 'Aligns camera and wrist data, then sends live JSONL events to the PC backend.'],
    ['Flask Backend', 'Routes gestures, updates live state, logs SQLite records, and exposes REST APIs.'],
    ['Sonic Pi + LED', 'Receives OSC music commands and sends visible feedback to the LED matrix.'],
  ]
  const techStackItems = ['React + Vite', 'Tailwind CSS', 'Flask REST', 'TCP JSONL', 'Pi MediaPipe', 'Micro:bit + ESP32', 'Sonic Pi OSC', 'SQLite']
  const guestModeItems = [
    ['Watch your hand', 'The Pi camera view shows the visitor and hand tracking overlay.'],
    ['Try a gesture', 'Make a fist to start or stop, push a palm to change volume, or push a fist to change BPM.'],
    ['See music change', 'BPM, volume, energy, density, and beat power update visually.'],
    ['Reset quickly', 'The session resets quickly so the next visitor can try it immediately.'],
  ]

  useEffect(() => {
    if (open) setPresentationVideoError(false)
  }, [open])

  async function handlePresentationTransport(action) {
    if (!onTransport || transportPending) return
    setTransportPending(true)
    try {
      await onTransport(action)
    } catch (error) {
      console.error(error)
    } finally {
      setTransportPending(false)
    }
  }

  const liveStatusItems = [
    {
      label: 'Camera',
      value: frame.connection.camera,
      active: frame.connection.camera === 'Connected',
      icon: Camera,
    },
    {
      label: 'Micro:bit',
      value: microbitLive ? 'L/R Online' : 'Sensors Ready',
      active: microbitLive,
      icon: Radio,
    },
    {
      label: 'Raspberry Pi',
      value: frame.connection.piGatewayConnected ? 'Pi Live' : 'Pi Stream Ready',
      active: frame.connection.piGatewayConnected || frame.connection.piGatewayRunning,
      icon: Server,
    },
    {
      label: 'AI Model',
      value: frame.connection.model || 'Model Ready',
      active: frame.connection.model === 'Model Loaded' || frame.prediction.confidence > 0,
      icon: Brain,
    },
    {
      label: 'Sonic Pi',
      value: frame.music.sonicPiConnected ? 'Live' : 'Music Standby',
      active: frame.music.sonicPiConnected,
      icon: Music2,
    },
    {
      label: 'Database',
      value: frame.connection.backend === 'REST Online' ? 'Logging' : 'Ready to Record',
      active: frame.connection.backend === 'REST Online',
      icon: Database,
    },
  ]
  const renderSlide = () => {
    if (step === 0) {
      return (
        <div className="grid min-h-[54vh] items-center gap-4 lg:grid-cols-[0.88fr_1.12fr]">
          <div className="min-w-0">
            <p className="eyebrow mb-4">Prepared Opening</p>
            <h2 className="font-display text-4xl font-semibold leading-tight text-white sm:text-6xl">{current.headline}</h2>
            <p className="mt-4 max-w-xl text-lg leading-8 text-slate-300">
              A human conducting gesture becomes visible musical change. The opening video shows the complete experience before the live performance begins.
            </p>
            <div className="mt-5 rounded-lg border border-white/10 bg-white/[0.055] p-3">
              <p className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase text-cyan">
                <Users size={16} />
                Project Team
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {teamMembers.map((member) => (
                  <div key={member.id} className="rounded-md border border-white/10 bg-black/20 px-3 py-2">
                    <p className="font-display text-base font-semibold text-white">{member.name}</p>
                    <p className="mt-1 text-[11px] uppercase text-slate-500">{member.role}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="mt-4 grid max-w-xl grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              {[
                ['Camera', frame.connection.camera],
                ['Hands', frame.connection.hands],
                ['Pi Link', frame.connection.piGatewayConnected ? 'Pi Live' : 'Pi Ready'],
                ['Sonic Pi', frame.music.sonicPiConnected ? 'Live' : 'Music Ready'],
              ].map(([label, value]) => (
                <div key={label} className="rounded-md border border-white/10 bg-white/[0.055] p-3">
                  <p className="text-slate-500">{label}</p>
                  <p className="mt-1 font-semibold text-white">{value}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="glass-panel p-4">
            {!presentationVideoError ? (
              <video
                className="aspect-video w-full rounded-lg border border-white/10 bg-black object-contain"
                src={videoSlot.path}
                controls
                playsInline
                onError={() => setPresentationVideoError(true)}
              />
            ) : (
              <div className="grid aspect-video place-items-center rounded-lg border border-dashed border-cyan/35 bg-cyan/5 p-6 text-center">
                <div className="max-w-lg">
                  <div className="mx-auto grid h-14 w-14 place-items-center rounded-md border border-cyan/30 bg-cyan/10 text-cyan">
                    <Video size={26} />
                  </div>
                  <p className="mt-5 text-xl font-semibold text-white">{videoSlot.title}</p>
                  <p className="mt-2 font-mono text-sm text-cyan">{videoSlot.path}</p>
                  <p className="mt-4 text-sm leading-6 text-slate-300">{videoSlot.note}</p>
                </div>
              </div>
            )}
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {[
                ['Motion Input', 'Camera and wrist sensors capture the conductor movement.'],
                ['AI Interpretation', 'The system recognizes intention such as start, stop, tempo, and volume.'],
                ['Musical Response', 'Sonic Pi turns the decision into audible changes in real time.'],
              ].map(([label, value]) => (
                <div key={label} className="rounded-md border border-white/10 bg-white/[0.045] px-3 py-2">
                  <p className="text-xs font-semibold text-white">{label}</p>
                  <p className="mt-1 text-[11px] leading-4 text-slate-400">{value}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="lg:col-span-2">
            <div className="grid gap-2 sm:grid-cols-5">
              {['Prepared Video', 'Workflow', 'Music Control', 'Guest Mode', 'Live Demo'].map((item, index) => (
                <div key={item} className="rounded-md border border-white/10 bg-white/[0.045] px-4 py-3 text-center">
                  <p className="text-xs text-slate-500">0{index + 1}</p>
                  <p className="mt-1 text-sm font-semibold text-cyan">{item}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )
    }

    if (step === 1) {
      return (
        <div className="grid min-h-[54vh] items-center gap-5 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <p className="eyebrow mb-4">Tech Stack & Workflow</p>
            <h2 className="font-display text-4xl font-semibold leading-tight text-white sm:text-6xl">{current.headline}</h2>
            <p className="mt-4 text-lg leading-8 text-slate-300">
              The system connects Pi-side sensing, PC-side control, Sonic Pi output, visual feedback, and database logging into one real-time performance loop.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {techStackItems.map((item) => (
                <span key={item} className="rounded-md border border-white/10 bg-white/[0.055] px-3 py-2 text-sm font-semibold text-cyan">
                  {item}
                </span>
              ))}
            </div>
          </div>
          <div className="glass-panel p-5">
            <div className="grid gap-3">
              {workflowItems.map(([label, detail], index) => (
                <div key={label} className="grid items-center gap-3 rounded-lg border border-white/10 bg-white/[0.045] p-4 sm:grid-cols-[64px_1fr]">
                  <div className="flex items-center gap-3">
                    <span className="grid h-11 w-11 place-items-center rounded-md border border-cyan/25 bg-cyan/10 font-mono text-sm font-semibold text-cyan">
                      0{index + 1}
                    </span>
                  </div>
                  <div>
                    <p className="text-base font-semibold text-white">{label}</p>
                    <p className="mt-1 text-sm leading-6 text-slate-300">{detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )
    }

    if (step === 2) {
      return (
        <div className="grid min-h-[54vh] gap-5 xl:grid-cols-[0.85fr_1.15fr]">
          <div className="grid content-center gap-4">
            <p className="eyebrow w-fit">Music Mapping</p>
            <h2 className="font-display text-4xl font-semibold leading-tight text-white sm:text-6xl">{current.headline}</h2>
            <p className="text-lg leading-8 text-slate-300">
              Instead of pressing buttons, the performer shapes the music by moving their hands. The screen shows every musical change as it happens.
            </p>
            <div className="rounded-lg border border-cyan/20 bg-cyan/5 p-5">
              <p className="mb-4 text-sm font-semibold uppercase text-cyan">Gesture Mapping</p>
              <div className="grid gap-3">
                {[
                  ['Two palms in a zone', 'Layer ON (melody → drums)'],
                  ['Right fist', 'Start music'],
                  ['Fist push up / down', 'BPM up / down'],
                  ['Left fist', 'Stop music'],
                ].map(([gesture, output]) => (
                  <div key={gesture} className="flex items-center justify-between gap-4 rounded-md border border-white/10 bg-black/20 px-4 py-3">
                    <span className="text-sm font-semibold text-white">{gesture}</span>
                    <span className="text-sm text-gold">{output}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="grid content-center gap-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {musicParameterTiles.map((item) => (
                <div key={item.label} className="rounded-lg border border-white/10 bg-white/[0.055] p-5">
                  <p className="text-xs uppercase text-slate-500">{item.label}</p>
                  <p className={`mt-2 font-display text-4xl font-semibold ${item.tone}`}>{item.value}</p>
                  <p className="mt-2 text-xs text-slate-400">{item.source}</p>
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
                    <motion.div className="h-full bg-gradient-to-r from-cyan to-gold" animate={{ width: `${item.bar}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )
    }

    if (step === 3) {
      return (
        <div className="grid min-h-[54vh] items-center gap-5 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <p className="eyebrow mb-4">Audience Experience</p>
            <h2 className="font-display text-4xl font-semibold leading-tight text-white sm:text-6xl">{current.headline}</h2>
            <p className="mt-4 text-lg leading-8 text-slate-300">
              Visitors can stand in the camera area, follow the gesture guide, and hear the music respond to their own movement.
            </p>
            <div className="mt-6 rounded-lg border border-gold/25 bg-gold/10 p-5">
              <p className="text-sm font-semibold uppercase text-gold">Guest Control Guide</p>
              <div className="mt-4 grid gap-3">
                {guestModeItems.map(([title, body], index) => (
                  <div key={title} className="rounded-md border border-white/10 bg-black/20 px-4 py-3">
                    <p className="font-semibold text-white">0{index + 1} · {title}</p>
                    <p className="mt-1 text-sm leading-6 text-slate-300">{body}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="grid gap-4">
            <div className="rounded-lg border border-white/10 bg-white/[0.055] p-5">
              <p className="mb-4 text-sm font-semibold uppercase text-slate-400">One-screen Experience Layout</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  ['Pi camera view', 'Visitor image + hand landmarks'],
                  ['Gesture tutorial', 'Clear actions and expected music result'],
                  ['Music visualization', 'BPM, volume, energy, density, beat power'],
                  ['Fast reset', 'Ready for the next visitor'],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-md border border-white/10 bg-black/20 p-4">
                    <p className="text-sm font-semibold text-white">{label}</p>
                    <p className="mt-2 text-xs leading-5 text-slate-400">{value}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-cyan/15 bg-cyan/5 p-5">
              <p className="mb-4 text-sm font-semibold uppercase text-cyan">Action Feedback</p>
              <div className="grid gap-2">
                {actionChain.map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3 rounded-md border border-white/10 bg-black/20 px-3 py-2">
                    <span className="text-xs uppercase text-slate-500">{label}</span>
                    <span className="truncate text-sm font-semibold text-white">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )
    }

    return (
      <div className="grid min-h-[54vh] items-center gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <p className="eyebrow mb-4">Final Live Demonstration</p>
          <h2 className="font-display text-4xl font-semibold leading-tight text-white sm:text-6xl">{current.headline}</h2>
          <p className="mt-4 text-lg leading-8 text-slate-300">
            The final performance is live: the conductor's real movement drives the music, while the screen shows recognition, response, and saved event data.
          </p>
          <div className="mt-5">
            <ConductorSignalScene frame={frame} heightClass="h-[38vh] min-h-[300px]" />
          </div>
        </div>
        <div className="grid gap-2.5">
          <div className="rounded-lg border border-gold/25 bg-gold/10 p-3">
            <p className="text-xs uppercase text-gold">Current Intention</p>
            <p className="mt-2 font-display text-3xl font-semibold text-white">{frame.prediction.label}</p>
            <p className="mt-1 text-base text-gold">{frame.prediction.response}</p>
            <div className="mt-2 flex items-end gap-4">
              <p className="font-display text-4xl font-semibold text-cyan">{frame.prediction.confidence}%</p>
              <p className="mb-2 text-xs uppercase text-slate-500">Confidence</p>
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              ['BPM', frame.music.bpm],
              ['Volume', `${frame.music.volume}%`],
              ['Energy', `${frame.music.energy}%`],
              ['Beat Power', `${frame.music.beatStrength}%`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-white/10 bg-white/[0.055] p-2.5">
                <p className="text-xs uppercase text-slate-500">{label}</p>
                <p className="mt-1 font-display text-2xl font-semibold text-white">{value}</p>
              </div>
            ))}
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.055] p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="flex items-center gap-2 text-sm font-semibold text-white">
                <Music2 size={16} className="text-gold" />
                Sonic Pi Control
              </p>
              <span className={frame.music.sonicPiConnected ? 'status-pill' : sonicPiDisplay.pillClass}>
                {presentationMusicStatus}
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">
              <button
                type="button"
                className="secondary-button py-1.5"
                disabled={transportPending}
                onClick={() => handlePresentationTransport('previous')}
              >
                <SkipBack size={16} />
                Prev
              </button>
              <button
                type="button"
                className="primary-button py-1.5"
                disabled={transportPending}
                onClick={() => handlePresentationTransport(presentationTransportAction)}
              >
                <PresentationTransportIcon size={16} />
                {presentationTransportLabel}
              </button>
              <button
                type="button"
                className="secondary-button py-1.5"
                disabled={transportPending}
                onClick={() => handlePresentationTransport('next')}
              >
                <SkipForward size={16} />
                Next
              </button>
              <button
                type="button"
                className="secondary-button py-1.5"
                disabled={transportPending}
                onClick={() => handlePresentationTransport('reset')}
              >
                <RefreshCw size={16} />
                Reset Music
              </button>
            </div>
            {sonicPiDisplay.hint ? <p className="mt-2 text-[11px] leading-4 text-gold/80">{sonicPiDisplay.hint}</p> : null}
          </div>
          <div className="rounded-lg border border-cyan/15 bg-cyan/5 p-3">
            <p className="mb-2 text-sm font-semibold uppercase text-cyan">Live Chain</p>
            <div className="grid gap-1.5">
              {actionChain.map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3 rounded-md border border-white/10 bg-black/20 px-3 py-1">
                  <span className="text-xs uppercase text-slate-500">{label}</span>
                  <span className="truncate text-sm font-semibold text-white">{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (!open) return null

  return (
    <AnimatePresence>
      <motion.div
        className="presentation-backdrop fixed inset-0 z-50 overflow-hidden"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <div className="mx-auto flex h-screen max-w-7xl flex-col px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid h-11 w-11 place-items-center rounded-md border border-gold/35 bg-gold/10 text-gold">
                <StepIcon size={19} />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">{presentationTitles[step]}</p>
                <p className="text-xs text-slate-400">AIoT Smart Conducting Performance System</p>
              </div>
            </div>
            <button type="button" className="secondary-button" onClick={onClose}>
              <X size={16} />
              Exit
            </button>
          </div>

          <div className="mt-3 grid gap-2 rounded-lg border border-white/10 bg-black/25 p-1.5 shadow-glow sm:grid-cols-3 xl:grid-cols-6">
            {liveStatusItems.map((item) => {
              const Icon = item.icon
              return (
                <div key={item.label} className="flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.045] px-3 py-1.5">
                  <div className={`grid h-8 w-8 place-items-center rounded-md border ${item.active ? 'border-emerald-400/35 bg-emerald-400/10 text-emerald-300' : 'border-gold/30 bg-gold/10 text-gold'}`}>
                    <Icon size={17} />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-[11px] uppercase text-slate-500">{item.label}</p>
                    <p className={`truncate text-sm font-semibold ${item.active ? 'text-emerald-200' : 'text-gold'}`}>{item.value}</p>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="grid min-h-0 flex-1 place-items-center py-4">
            <motion.div
              key={step}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              className="w-full"
            >
              {renderSlide()}
            </motion.div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-3">
            <div className="flex gap-2">
              {steps.map((item, index) => (
                <button
                  key={item.title}
                  type="button"
                  className={`h-2.5 w-12 rounded-full ${index === step ? 'bg-gold' : 'bg-white/15'}`}
                  onClick={() => setStep(index)}
                  aria-label={`Presentation step ${index + 1}`}
                />
              ))}
            </div>
            <div className="flex gap-2">
              <button type="button" className="secondary-button" onClick={() => setStep((value) => Math.max(0, value - 1))}>
                <Pause size={15} />
                Previous
              </button>
              <button type="button" className="primary-button" onClick={() => setStep((value) => Math.min(steps.length - 1, value + 1))}>
                <Play size={15} />
                Next
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}

function App() {
  const { frame, logs, connectionState, sendSonicPiTransport } = useConductorFeed()
  const [presentationOpen, setPresentationOpen] = useState(false)
  const [experienceOpen, setExperienceOpen] = useState(false)
  const [videoOpen, setVideoOpen] = useState(false)

  const openPresentation = () => {
    setPresentationOpen(true)
    const fullscreenRequest = document.documentElement.requestFullscreen?.()
    fullscreenRequest?.catch?.(() => {})
  }

  const closePresentation = () => {
    setPresentationOpen(false)
    if (document.fullscreenElement) {
      const fullscreenExit = document.exitFullscreen?.()
      fullscreenExit?.catch?.(() => {})
    }
  }

  const openExperience = () => {
    setExperienceOpen(true)
  }

  const closeExperience = () => {
    setExperienceOpen(false)
  }

  const openRoadshowVideo = () => {
    setVideoOpen(true)
  }

  const closeRoadshowVideo = () => {
    setVideoOpen(false)
  }

  return (
    <div className="min-h-screen bg-transparent text-slate-100">
      <TopNav onPresentation={openPresentation} onExperience={openExperience} connectionState={connectionState} />
      <main>
        <HeroSection frame={frame} onPresentation={openPresentation} onExperience={openExperience} onVideo={openRoadshowVideo} />
        <ExperienceGateway frame={frame} onExperience={openExperience} />
        <LiveStage frame={frame} logs={logs} onTransport={sendSonicPiTransport} />
        <DecisionFlow frame={frame} connectionState={connectionState} />
        <ArchitectureView />
      </main>
      <RoadshowVideoModal open={videoOpen} onClose={closeRoadshowVideo} />
      <ExperienceMode open={experienceOpen} onClose={closeExperience} frame={frame} onTransport={sendSonicPiTransport} />
      <PresentationMode open={presentationOpen} onClose={closePresentation} frame={frame} onTransport={sendSonicPiTransport} />
    </div>
  )
}

export default App
