import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Activity,
  BarChart3,
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
  SlidersHorizontal,
  Sparkles,
  Upload,
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
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  analyticsSeries,
  assetSlots,
  flowSteps,
  gestureCatalog,
  gestureDistribution,
  historicalRows,
  navItems,
  trainingSteps,
  validationCards,
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

function TopNav({ onPresentation }) {
  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-void/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <button
          type="button"
          className="flex items-center gap-3 text-left"
          onClick={() => scrollToSection('hero')}
          aria-label="Go to hero"
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
          <span className="hidden items-center gap-2 rounded-md border border-mint/25 bg-mint/10 px-3 py-2 text-xs font-medium text-mint sm:inline-flex">
            <StatusDot tone="green" />
            System Online
          </span>
          <button type="button" className="primary-button" onClick={onPresentation}>
            <Maximize2 size={16} />
            路演模式
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

function HeroSection({ frame, onPresentation }) {
  const heroStats = [
    ['Input', 'Camera + 2×Micro:bit'],
    ['Inference', 'Local Edge AI'],
    ['Response', `${frame.connection.latency} ms`],
    ['Logging', 'Sensor + Prediction + Action'],
  ]

  return (
    <section id="hero" className="relative overflow-hidden border-b border-white/10">
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
            用动作，重新定义音乐交互
          </h1>
          <p className="mt-6 max-w-3xl text-lg leading-8 text-slate-200">
            通过摄像头、双 Micro:bit 与 Raspberry Pi 本地 AI 模型，实时识别双手指挥意图，并将动作转换为节奏、音量、能量、风格和音乐段落控制。
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button type="button" className="primary-button" onClick={() => scrollToSection('live-stage')}>
              <Play size={16} />
              开始现场演示
            </button>
            <button type="button" className="secondary-button" onClick={onPresentation}>
              <Maximize2 size={16} />
              全屏路演
            </button>
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
          <div className="glass-panel screen-frame overflow-hidden p-4">
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
            <ConductorSignalScene frame={frame} compact />
          </div>
          <AssetPlaceholder
            title={assetSlots[0].title}
            path={assetSlots[0].path}
            note={assetSlots[0].note}
          />
        </div>
      </div>
    </section>
  )
}

function ConductorSignalScene({ frame, compact = false }) {
  const waveBars = useMemo(
    () =>
      Array.from({ length: compact ? 34 : 52 }, (_, index) => ({
        height: 22 + Math.abs(Math.sin(index / 2 + frame.music.bpm / 30)) * 76,
        delay: `${index * 0.035}s`,
      })),
    [compact, frame.music.bpm],
  )

  return (
    <div className={`relative overflow-hidden rounded-lg border border-white/10 bg-void/75 ${compact ? 'h-52' : 'h-80'}`}>
      <div className="absolute inset-0 stage-grid opacity-50" />
      <div className="signal-ribbon absolute inset-x-0 top-0 h-16" />
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
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 900 360" role="presentation" aria-hidden="true">
        <path
          d="M140 190 C 240 80, 330 280, 430 150 S 610 90, 760 210"
          fill="none"
          stroke="rgba(56,189,248,0.55)"
          strokeWidth="3"
          strokeDasharray="9 10"
        />
        <path
          d="M180 240 C 310 310, 380 120, 510 190 S 670 290, 800 110"
          fill="none"
          stroke="rgba(244,199,107,0.58)"
          strokeWidth="3"
          strokeDasharray="5 12"
        />
      </svg>
      <div className="absolute inset-x-6 bottom-5 flex h-20 items-end justify-center gap-1.5">
        {waveBars.map((bar, index) => (
          <span
            key={`${bar.height}-${index}`}
            className="waveform-bar w-1 rounded-full bg-gradient-to-t from-cyan/20 via-cyan to-gold"
            style={{ height: `${bar.height}%`, animationDelay: bar.delay }}
          />
        ))}
      </div>
      <div className="absolute left-5 top-5 grid gap-2 text-xs">
        <span className="status-pill">
          <StatusDot tone="green" />
          Camera Connected
        </span>
        <span className="status-pill">
          <StatusDot tone="cyan" />
          Two Hands Detected
        </span>
      </div>
      <div className="absolute bottom-5 right-5 rounded-md border border-white/10 bg-black/35 px-3 py-2 text-right backdrop-blur">
        <p className="text-xs text-slate-400">Current Intention</p>
        <p className="font-display text-xl font-semibold text-white">{frame.prediction.label}</p>
      </div>
    </div>
  )
}

function LiveStage({ frame, logs }) {
  return (
    <section id="live-stage" className="section-shell">
      <SectionHeader
        eyebrow="Live Conducting Stage"
        title="实时指挥舞台"
        description="路演时默认进入这一屏：左侧展示摄像头和双手轨迹，中间展示 AI 识别结果，右侧展示音乐参数，底部呈现 Micro:bit 与系统响应。"
        icon={Monitor}
      />

      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.95fr_0.9fr]">
        <CameraGesturePanel frame={frame} />
        <AiPredictionCard frame={frame} />
        <MusicControlCenter frame={frame} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <MicrobitCard side="LEFT MICRO:BIT" data={frame.microbit.left} color="cyan" />
        <MicrobitCard side="RIGHT MICRO:BIT" data={frame.microbit.right} color="gold" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <RealtimeMetrics frame={frame} />
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
            实时摄像头画面
          </p>
          <p className="mt-1 text-xs text-slate-400">Hand landmarks, skeleton lines, trajectory trail</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="status-pill">FPS {frame.connection.fps}</span>
          <span className="status-pill">{frame.connection.latency} ms</span>
        </div>
      </div>
      <div className="scanline relative overflow-hidden rounded-lg border border-cyan/20 bg-black/50">
        <ConductorSignalScene frame={frame} />
        <div className="absolute inset-x-6 top-16 h-40 rounded-lg border border-dashed border-white/20 bg-white/[0.025] text-center">
          <p className="mt-4 text-xs font-medium text-slate-300">双手识别安全区</p>
        </div>
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
          AI 识别结果
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
        <p className="mt-4 text-sm text-slate-200">系统响应：{frame.prediction.response}</p>
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

function MusicControlCenter({ frame }) {
  const metrics = [
    { label: 'BPM', value: frame.music.bpm, icon: Activity, suffix: '' },
    { label: 'Volume', value: frame.music.volume, icon: Volume2, suffix: '%' },
    { label: 'Energy', value: frame.music.energy, icon: Zap, suffix: '%' },
    { label: 'Density', value: frame.music.density, icon: SlidersHorizontal, suffix: '%' },
  ]

  return (
    <div className="glass-panel p-5">
      <div className="mb-5 flex items-center justify-between">
        <p className="flex items-center gap-2 text-sm font-semibold text-white">
          <Music2 size={16} className="text-gold" />
          音乐控制中心
        </p>
        <span className="status-pill">{frame.music.style}</span>
      </div>

      <div className="rounded-lg border border-white/10 bg-black/25 p-4">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-white">{frame.music.title}</p>
            <p className="text-xs text-slate-400">Key: {frame.music.key} · Style: {frame.music.style}</p>
          </div>
          <button type="button" className="grid h-10 w-10 place-items-center rounded-md bg-gold text-slate-950" aria-label="Play demo">
            <Play size={18} />
          </button>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-white/10">
          <motion.div className="h-full bg-gradient-to-r from-cyan to-gold" animate={{ width: `${frame.music.progress}%` }} />
        </div>
        <div className="mt-2 flex justify-between text-xs text-slate-400">
          <span>01:28</span>
          <span>03:42</span>
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
          <MappingRow left="左手 Y 坐标" right="音高 / 和弦 / 音量" />
          <MappingRow left="右手 X 坐标" right="声像 / 音色" />
          <MappingRow left="加速度峰值" right="节拍 / 强拍识别" />
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
          <p className="mt-1 text-xs text-slate-400">{data.id} · Bluetooth / Serial Ready</p>
        </div>
        <span className={`rounded-md border px-3 py-1 text-xs font-semibold ${accent}`}>Connected</span>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-[0.8fr_1.2fr]">
        <AssetPlaceholder title="设备照片占位" path="/media/microbit-wrist.jpg" note="替换为真实 Micro:bit 佩戴照片。" type="image" />
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

function RealtimeMetrics({ frame }) {
  const metrics = [
    ['左手高度', `${Math.round(frame.camera.leftHandY * 100)}%`],
    ['右手位置', `${Math.round(frame.camera.rightHandX * 100)}%`],
    ['双手距离', frame.camera.handDistance],
    ['运动速度', `${frame.camera.movementSpeed} m/s`],
    ['轨迹角度', `${frame.camera.trajectoryAngle} deg`],
    ['响应延迟', `${frame.connection.latency} ms`],
  ]
  return (
    <div className="glass-panel p-5">
      <p className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
        <Gauge size={16} className="text-cyan" />
        实时特征与系统状态
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {metrics.map(([label, value]) => (
          <div key={label} className="metric-tile">
            <p className="text-xs text-slate-400">{label}</p>
            <p className="mt-2 font-display text-2xl font-semibold text-white">{value}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function InferenceLog({ logs }) {
  return (
    <div className="glass-panel p-5">
      <p className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
        <Clock size={16} className="text-gold" />
        AI 推断日志
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
        title="AI 决策过程"
        description="用于回答路演中的关键问题：AI 如何融合 Camera 与 Micro:bit 数据，并将指挥动作映射为音乐控制。"
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
            WebSocket-ready Payload
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

function ValidationHighlights() {
  return (
    <section id="validation" className="section-shell">
      <SectionHeader
        eyebrow="Proof Points"
        title="关键验证点"
        description="把现场评审通常会追问的技术可信度，用更自然的方式融入页面：AI 依据、融合价值、实时性、数据闭环和演示稳定性。"
        icon={ShieldCheck}
      />

      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="glass-panel p-6">
          <div className="flex items-center gap-3">
            <div className="grid h-12 w-12 place-items-center rounded-md border border-gold/30 bg-gold/10 text-gold">
              <ShieldCheck size={22} />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Roadshow Defense Layer</p>
              <p className="text-xs text-slate-400">用演示证据支撑项目完整性</p>
            </div>
          </div>

          <div className="mt-6 grid gap-3">
            {[
              ['特征输入', '轨迹 / 速度 / 加速度 / 时窗'],
              ['模型输出', '8 类指挥意图 + Top-3 置信度'],
              ['执行反馈', 'BPM / Volume / Energy / Style'],
              ['数据保存', 'Raw Sensor / Feature / Prediction / Action'],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-white/10 bg-white/[0.045] p-4">
                <p className="text-xs uppercase text-slate-500">{label}</p>
                <p className="mt-1 text-sm font-semibold text-slate-100">{value}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {validationCards.map((card, index) => (
            <motion.article
              key={card.title}
              className={`validation-card ${index === 0 ? 'md:col-span-2' : ''}`}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.35 }}
              transition={{ delay: index * 0.04 }}
            >
              <div className="mb-4 flex items-center justify-between">
                <p className="font-semibold text-white">{card.title}</p>
                <span className="rounded-md border border-cyan/25 bg-cyan/10 px-2 py-1 text-xs text-cyan">
                  0{index + 1}
                </span>
              </div>
              <p className="text-sm leading-6 text-slate-300">{card.claim}</p>
              <div className="mt-4 rounded-md border border-white/10 bg-black/20 p-3">
                <p className="text-xs font-semibold uppercase text-gold">Evidence</p>
                <p className="mt-1 text-xs leading-5 text-slate-300">{card.evidence}</p>
              </div>
              <p className="mt-3 text-xs leading-5 text-cyan">{card.demo}</p>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  )
}

function AnalyticsDashboard() {
  return (
    <section id="analytics" className="section-shell">
      <SectionHeader
        eyebrow="Data Analytics"
        title="历史数据与分析"
        description="展示数据库闭环：保存原始传感器数据、处理特征、AI 预测结果和最终音乐执行记录。"
        icon={BarChart3}
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['今日识别次数', '268'],
          ['平均置信度', '91.4%'],
          ['平均响应延迟', '86 ms'],
          ['有效手势率', '94.8%'],
        ].map(([label, value]) => (
          <div key={label} className="glass-panel p-5">
            <p className="text-sm text-slate-400">{label}</p>
            <p className="mt-2 font-display text-3xl font-semibold text-white">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.25fr_0.75fr]">
        <div className="glass-panel p-5">
          <p className="mb-4 text-sm font-semibold text-white">BPM / Volume / Confidence 时间序列</p>
          <div className="h-80">
            <ResponsiveContainer>
              <LineChart data={analyticsSeries}>
                <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                <XAxis dataKey="tick" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Line type="monotone" dataKey="bpm" stroke="#38bdf8" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="volume" stroke="#f4c76b" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="confidence" stroke="#22c55e" strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="glass-panel p-5">
          <p className="mb-4 text-sm font-semibold text-white">手势分布</p>
          <div className="h-80">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={gestureDistribution} dataKey="value" nameKey="name" innerRadius={58} outerRadius={96} paddingAngle={3}>
                  {gestureDistribution.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={chartTooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {gestureDistribution.map((item) => (
              <div key={item.name} className="flex items-center gap-2 text-xs text-slate-300">
                <span className="h-2 w-2 rounded-full" style={{ background: item.color }} />
                {item.name} {item.value}%
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 overflow-hidden rounded-lg border border-white/10">
        <table className="w-full min-w-[760px] border-collapse bg-white/[0.04] text-left text-sm">
          <thead className="bg-white/[0.07] text-xs uppercase text-slate-400">
            <tr>
              {['时间', '输入源', '识别动作', '置信度', '音乐响应', '延迟'].map((head) => (
                <th key={head} className="px-4 py-3 font-semibold">{head}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {historicalRows.map((row) => (
              <tr key={`${row.time}-${row.gesture}`} className="border-t border-white/10 text-slate-200">
                <td className="px-4 py-3 font-mono text-xs">{row.time}</td>
                <td className="px-4 py-3">{row.source}</td>
                <td className="px-4 py-3 text-cyan">{row.gesture}</td>
                <td className="px-4 py-3">{row.confidence}</td>
                <td className="px-4 py-3">{row.response}</td>
                <td className="px-4 py-3">{row.latency}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function ArchitectureView() {
  const rows = [
    { icon: Camera, title: '感知层', items: ['Camera', 'Micro:bit L/R', 'Hand Tracking'] },
    { icon: Server, title: '网络与边缘层', items: ['Bluetooth', 'Serial', 'WebSocket', 'Raspberry Pi 5'] },
    { icon: Cpu, title: 'AI 与业务层', items: ['Feature Engine', 'Gesture Recognition Model', 'Music Mapping Engine'] },
    { icon: Music2, title: '音乐执行层', items: ['Browser Audio', 'Speaker', 'RGB LED Matrix'] },
    { icon: Database, title: '数据层', items: ['Sensor Records', 'Predictions', 'Actions'] },
  ]

  return (
    <section id="architecture" className="section-shell">
      <SectionHeader
        eyebrow="System Architecture"
        title="系统架构视图"
        description="把 Camera、Micro:bit、Raspberry Pi、本地 AI、音乐执行和数据库写入组织成清晰的数据链路。"
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
        title="校准与训练模式"
        description="展示系统可靠性：通过摄像头位置、手部范围、IMU 零点和手势样本采集，让不同演示者都能稳定完成路演。"
        icon={Settings}
      />

      <div className="grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
        <div className="glass-panel p-5">
          <p className="mb-4 text-sm font-semibold text-white">校准检查</p>
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
              <p className="text-sm font-semibold text-white">手势采集任务</p>
              <p className="mt-1 text-xs text-slate-400">Label: Crescendo · Plan: 10 samples · Completed: 6</p>
            </div>
            <button type="button" className="secondary-button">
              <Radio size={15} />
              开始录制
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
    ['Problem', '传统音乐控制依赖键盘、鼠标和触摸屏，难以捕捉真实指挥动作中的节奏、力度和情感表达。'],
    ['Solution', '系统通过 Camera 和 Micro:bit 获取双手动作，利用本地 AI 模型识别指挥意图，并实时转换为音乐控制指令。'],
    ['Innovation', 'Contactless Interaction · Multi-sensor Fusion · Edge AI Inference · Real-time Music Control · Persistent Data Analytics'],
    ['Application', '音乐教育、指挥训练、互动展览、创意演出、特殊人群音乐交互、娱乐与数字艺术。'],
  ]

  return (
    <section id="about" className="section-shell pb-20">
      <SectionHeader
        eyebrow="Project About"
        title="项目介绍与素材替换清单"
        description="保留立项表中的核心概念，同时把路演需要的真实照片和视频位置提前留好，方便后续快速替换。"
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
            真实素材预留
          </p>
          <div className="space-y-3">
            {assetSlots.map((slot, index) => (
              <AssetPlaceholder
                key={slot.path}
                title={slot.title}
                path={slot.path}
                note={slot.note}
                type={index === 0 || index === 1 ? 'video' : 'image'}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function PresentationMode({ open, onClose, frame }) {
  const [step, setStep] = useState(0)
  const steps = [
    { title: 'Raise Your Hands to Start', sub: '系统检测双手，进入实时指挥模式。', icon: Hand },
    { title: frame.prediction.label, sub: `${frame.prediction.zh} · ${frame.prediction.response}`, icon: Brain },
    { title: `BPM ${Math.max(92, frame.music.bpm - 6)} -> ${frame.music.bpm}`, sub: '右手下落触发强拍，音乐节奏同步调整。', icon: Activity },
    { title: 'Performance Summary', sub: 'Duration 01:42 · Gestures 26 · Confidence 93.2% · Latency 84 ms', icon: ShieldCheck },
  ]
  const current = steps[step]
  const Icon = current.icon

  if (!open) return null

  return (
    <AnimatePresence>
      <motion.div
        className="presentation-backdrop fixed inset-0 z-50 overflow-auto"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <div className="mx-auto flex min-h-screen max-w-7xl flex-col px-5 py-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid h-11 w-11 place-items-center rounded-md border border-gold/35 bg-gold/10 text-gold">
                <Maximize2 size={19} />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">Presentation Mode</p>
                <p className="text-xs text-slate-400">AIoT Smart Conducting Performance System</p>
              </div>
            </div>
            <button type="button" className="secondary-button" onClick={onClose}>
              <X size={16} />
              退出
            </button>
          </div>

          <div className="grid flex-1 place-items-center py-10">
            <motion.div
              key={step}
              initial={{ opacity: 0, scale: 0.96, y: 16 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              className="w-full max-w-5xl text-center"
            >
              <div className="mx-auto mb-8 grid h-24 w-24 place-items-center rounded-full border border-cyan/35 bg-cyan/10 text-cyan shadow-glow">
                <Icon size={42} />
              </div>
              <h2 className="font-display text-5xl font-semibold text-white sm:text-7xl">{current.title}</h2>
              <p className="mx-auto mt-6 max-w-3xl text-xl leading-9 text-slate-300">{current.sub}</p>
              <div className="mt-10">
                <ConductorSignalScene frame={frame} compact />
              </div>
            </motion.div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-5">
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
                上一步
              </button>
              <button type="button" className="primary-button" onClick={() => setStep((value) => Math.min(steps.length - 1, value + 1))}>
                <Play size={15} />
                下一步
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}

function App() {
  const { frame, logs, connectionState } = useConductorFeed()
  const [presentationOpen, setPresentationOpen] = useState(false)

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

  return (
    <div className="min-h-screen bg-transparent text-slate-100">
      <TopNav onPresentation={openPresentation} />
      <main>
        <HeroSection frame={frame} onPresentation={openPresentation} />
        <LiveStage frame={frame} logs={logs} />
        <DecisionFlow frame={frame} connectionState={connectionState} />
        <ValidationHighlights />
        <AnalyticsDashboard />
        <ArchitectureView />
        <CalibrationTraining />
        <AboutProject />
      </main>
      <PresentationMode open={presentationOpen} onClose={closePresentation} frame={frame} />
    </div>
  )
}

export default App
