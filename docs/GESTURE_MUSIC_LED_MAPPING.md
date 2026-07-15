# Gesture ↔ Music ↔ LED Mapping — AIoT Smart Conducting System

> **版本**: v1.0 | **最后更新**: 2026-07-15  
> **用途**: 定义 8 种指挥手势在音乐控制和灯光反馈两条输出线上的具体映射参数

---

## 1. 总览

```
指挥手势 ──→ Random Forest 分类 ──→ 置信度 > 阈值
                                        │
                    ┌───────────────────┼───────────────────┐
                    ↓                   ↓                   ↓
              Web Audio API        Chart.js Dashboard    Pi 5 GPIO → LED Matrix
              (音乐控制)            (数据展示)            (rpi_ws281x 直驱)
```

---

## 2. 映射总表

| # | 手势 | 触发方式 | 🎵 音乐参数 | 💡 LED 灯光 | 设计理由 |
|:--:|------|----------|------------|------------|----------|
| 1 | **Downbeat** 下拍 | 右手快速下击 | **触发拍点** — `Tone.Transport` 重对齐拍子；或触发下一个音符/和弦 | **强闪** — 全屏白光脉冲，跟随拍点瞬间亮度 100% → 快速衰减 | 最核心的指挥动作，节拍锚点 |
| 2 | **Crescendo** 渐强 | 左手持续上抬 / 双手间距扩大 | **音量 ↑** — `gainNode.gain` 线性递增，每次 +3~5dB，上限可设 | **亮度爬升 + 色相偏移** — 暗蓝→亮紫→亮红，亮度 20%→100%，渐变过渡 | 传统指挥中左手控制力度，视觉上"暖=强"是直觉 |
| 3 | **Decrescendo** 渐弱 | 左手持续下压 / 双手间距缩小 | **音量 ↓** — `gainNode.gain` 线性递减，下限 -30dB | **亮度衰减 + 色相回退** — 亮红→暗紫→暗蓝，亮度 100%→20% | 渐强的逆过程，对称设计 |
| 4 | **Cutoff** 切断 | 右手握拳 / 双手急速合拢 | **静音或骤停** — `gainNode.gain` 在 0.1s 内 ramped 到 0，或 Transport 暂停 | **瞬间黑屏** — 全 LED 0% 亮度，停留 0.5s 后恢复呼吸灯 | 最戏剧性的动作，视觉反馈必须"果断" |
| 5 | **Style Switch** 风格切换 | 双手交叉挥动 / 特定手势组合 | **切换音色预设** — 更换 Tone.js instrument/sampler（管弦→电子→钢琴），或切换 reverb/EQ profile | **调色板切换** — 整体色相偏移（暖金→冷蓝→霓虹），过渡时间 0.5~1s | "换风格"是视觉上最容易展示的亮点 |
| 6 | **Idle** 空闲 | 手在体侧静止 / 无显著运动 >1s | **保持当前状态** — 无操作，持续播放；可选：进入 ambient / drone 模式 | **慢呼吸脉冲** — 亮度以 4s 周期柔缓明灭（20%↔40%），表示"待命中" | 避免没人指挥时突然静音的尴尬 |
| 7 | **Tempo Up** 加速 | 右手小幅快速画圈 / 节拍频率明显加快 | **BPM ↑** — `Tone.Transport.bpm.value` 每次 +5 BPM，上限可视音乐风格设 | **动画加速** — 脉冲/波浪频率同步 BPM，色相也可微偏暖表示"更激烈" | 拍频直接映射到 LED 闪烁频率，一目了然 |
| 8 | **Tempo Down** 减速 | 右手大幅慢速画圈 / 节拍频率明显减慢 | **BPM ↓** — `Tone.Transport.bpm.value` 每次 -5 BPM，下限 ~40 BPM | **动画减速** — 脉冲频率同步降低，色相微偏冷 | Tempo Up 的对称操作 |

---

## 3. 音乐端 — 可控参数清单

| 参数 | Web Audio API 实现 | 受控手势 |
|------|-------------------|----------|
| **BPM** | `Tone.Transport.bpm.value` | Tempo Up / Tempo Down |
| **音量 (Gain)** | `GainNode.gain` (0~1, ramp target) | Crescendo / Decrescendo / Cutoff |
| **播放/暂停** | `Tone.Transport.start()/stop()` | Cutoff / Idle |
| **音色/乐器** | `Tone.Sampler` 或 `Tone.Synth` 切换 preset | Style Switch |
| **混响量** | `Reverb.wet.value` | Style Switch（可选不同风格附带不同混响） |
| **滤波器** | `Filter.frequency` / `Filter.type` | Style Switch（可选 EQ profile） |

---

## 4. LED 端 — 可控参数清单

| 参数 | 范围 | 实现方式 | 受控手势 |
|------|------|---------|----------|
| **全局亮度** | 0–255 | `leds[i] = CRGB(r,g,b) * brightness_factor` | Crescendo / Decrescendo / Cutoff |
| **色相 (Hue)** | 0–360° | HSV → RGB 转换 | Style Switch |
| **动画速度** | 帧间延迟 ms | 非阻塞 delay / timer | Tempo Up / Tempo Down |
| **动画模式** | enum | wave / pulse / sparkle / solid / off | Downbeat / Cutoff / Idle / Style Switch |

---

## 5. 灯光调色板预设（Style Switch 可选）

| 风格名 | 主色 | LED 效果 | 适合音乐类型 |
|--------|------|---------|-------------|
| **Warm Classical** 暖光古典 | 琥珀金 + 暖白 | 柔波 | 管弦乐 |
| **Cool Electronic** 冷光电音 | 青蓝 + 品红 | 快闪彩条 | 电子/流行 |
| **Minimal Piano** 极简钢琴 | 暖白 + 浅灰 | 慢呼吸 | 钢琴独奏 |
| **Dramatic** 戏剧 | 红 + 金 + 闪白 | Downbeat 时全屏白闪 | 电影配乐 |

---

## 6. 实现优先级

如果开发时间紧张，按以下顺序实现：

| 优先级 | 手势 | 验收标准 |
|:--:|------|------|
| **1 (MVP)** | Downbeat + Tempo Up/Down + Cutoff | 闪光+节拍同步 / BPM+灯速 / 静音+黑屏 |
| **2 (加分)** | Crescendo + Decrescendo | 音量渐变 + 亮度渐变 |
| **3 (亮点)** | Style Switch | 音色切换 + 调色板切换 |
| **4 (锦上添花)** | Idle | 呼吸灯 |

---

## 7. 前后端接口约定

前端负责 Web Audio API 音乐控制，后端发布手势事件。采用 **Server-Sent Events (SSE)** 或 **轮询** 方式通知前端。

### 7.1 手势事件数据格式（后端→前端）

```json
{
  "gesture": "downbeat",
  "gesture_id": 1,
  "confidence": 0.92,
  "timestamp": 1721052000.500000,
  "music_params": {
    "action": "trigger_beat",
    "bpm_delta": 0,
    "volume_delta": 0,
    "style": null
  },
  "led_params": {
    "effect": "flash_white",
    "brightness": 255,
    "duration_ms": 100,
    "color": "#FFFFFF"
  }
}
```

### 7.2 各手势 music_params / led_params 参考值

| gesture | music_params.action | music_params.* | led_params.effect |
|---------|--------------------|----------------|------------------|
| `idle` | `none` | — | `breathing` |
| `downbeat` | `trigger_beat` | — | `flash_white` |
| `crescendo` | `adjust_volume` | `volume_delta: +3` | `brightness_ramp_up` |
| `decrescendo` | `adjust_volume` | `volume_delta: -3` | `brightness_ramp_down` |
| `cutoff` | `stop_or_mute` | `volume_target: 0` | `instant_black` |
| `style_switch` | `change_style` | `style: "warm_classical"` 等 | `palette_switch` |
| `tempo_up` | `adjust_tempo` | `bpm_delta: +5` | `fast_pulse` |
| `tempo_down` | `adjust_tempo` | `bpm_delta: -5` | `slow_pulse` |

---

> ⚠️ **注意**：`music_params` 和 `led_params` 是后端推理模块输出手势后，由后端根据映射表自动填充的建议参数。前端和 Pi 5 LED 模块各取所需字段消费。
