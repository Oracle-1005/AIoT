# 手势控制音乐指挥系统 — 完整设计方案

> **版本**: v1.0 | **日期**: 2026-07-22
> **目标**: 在现有 AIoT 数据采集与传输框架基础上，设计一套完整的「手势→音乐+灯光」双输出指挥系统

---

## 0. 设计决策（已确认）

| # | 决策 | 说明 |
|---|------|------|
| **左手设备** | ESP32 WiFi IMU（替代 Micro:bit BLE） | 每个手腕一个 ESP32，WiFi TCP 通信 |
| **右手设备** | ESP32 WiFi IMU（替代 Micro:bit BLE） | 自带 IMU + GPIO（蜂鸣器、小灯带） |
| **音乐输出** | Sonic Pi OSC | 沿用现有 `backend/sonic_pi.py` + `music/sonic_pi/` 架构 |
| **LED 连接** | 树莓派 GPIO18 有线直驱 | 2 块 8×32 WS2812B，路演场景指挥者站立位置固定 |
| **手势识别** | **AI 模型（核心）** | MediaPipe 做关键点提取（AI 1）+ 训练手势分类模型（AI 2） |
| **左右手分工** | 右手→节拍 / 左手→力度 | 符合传统指挥范式，灯效分区对应 |

---

## 0.1 AI 模型在项目中的定位（核心）

本项目体现 AIoT"智能"的关键，在于 **两层 AI 模型协同**：

```
┌─────────────────────────────────────────────────────────┐
│                    AI 模型 1（已有）                      │
│  MediaPipe Hand Landmarker                              │
│  • 运行位置：树莓派 5                                    │
│  • 模型类型：深度学习（CNN + Transformer）               │
│  • 输入：摄像头 RGB 图像 (640×480 @ 30fps)              │
│  • 输出：21 个手部关键点 (x,y,z) × 2 手                 │
│  • 状态：✅ 已部署，正常运行                              │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼  21 landmarks + 视觉特征
┌─────────────────────────────────────────────────────────┐
│                    AI 模型 2（待构建）  ← 项目核心贡献     │
│  GestureClassifier (手势分类模型)                        │
│  • 运行位置：PC 后端 (model/inference.py)                │
│  • 模型类型：Random Forest / XGBoost / LSTM / 小Transformer│
│  • 输入：滑动窗口内的多模态特征向量                        │
│  • 输出：手势标签 + 置信度 + 各手势概率分布                │
│  • 状态：❌ model_service.py 已预留接口，模型待训练        │
└──────────────────────────────────────────────────────────┘
```

**MediaPipe 解决"手在哪里"，GestureClassifier 解决"手在做什么指挥动作"。两者互补，共同构成 AI 管线。**

---

## 1. 总体架构

### 1.1 双信号输出模型

```
┌─────────────────────────────────────────────────────────────────────┐
│                         指挥者 (Conductor)                          │
│  左手: ESP32 (WiFi IMU) + 8×32 LED 灯带                              │
│  右手: ESP32 (WiFi IMU) + 8×32 LED 灯带                              │
│  + Pi Camera (CSI, 手部关键点)                                       │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   树莓派 5 (边缘节点)    │
                    │  • 摄像头采集 + MediaPipe  │
                    │  • ESP32 IMU 数据接收(WiFi)│
                    │  • 时间同步 + 特征提取     │
                    │  • TCP JSON Lines 上行     │
                    │  • LED 灯效渲染执行       │◄── 接收 PC 灯效指令
                    │  • ESP32 指令转发(WiFi)   │
                    └────────────┬────────────┘
                                 │ TCP :9000
                    ┌────────────▼────────────┐
                    │     PC 后端 (控制中心)   │
                    │                          │
                    │  ┌──────────────────┐    │
                    │  │  手势识别引擎     │    │
                    │  │  (规则 + ML)     │    │
                    │  └──────┬───────────┘    │
                    │         │                │
                    │    ┌────▼─────┐          │
                    │    │ 音乐意图  │          │
                    │    │ 映射器    │          │
                    │    └────┬─────┘          │
                    │         │                │
                    │  ┌──────▼──────────┐     │
                    │  │  双信号生成器    │     │
                    │  └──┬──────────┬───┘     │
                    └─────┼──────────┼─────────┘
                          │          │
                ┌─────────▼──┐  ┌───▼──────────┐
                │  信号 1    │  │   信号 2      │
                │  音乐控制  │  │   LED 灯效    │
                │  (OSC)     │  │   (TCP下行)   │
                └─────┬──────┘  └───┬──────────┘
                      │             │
              ┌───────▼──────┐  ┌──▼──────────────┐
              │  Sonic Pi    │  │ 树莓派 LED 驱动  │
              │  (PC 本地)   │  │ (rpi_ws281x)     │
              │  音乐合成     │  │ 右/左手灯带渲染  │
              └──────┬───────┘  └──────────────────┘
                     │
              ┌──────▼──────┐
              │   扬声器     │
              │   (音频输出) │
              └─────────────┘
```

### 1.2 关键设计原则

1. **低延迟优先**：手势到音乐反馈 < 100ms，手势到灯光反馈 < 50ms
2. **左右手分工**：右手控制节拍/BPM，左手控制力度/表情
3. **分层检测**：即时特征（帧级）→ 滑动窗口（800ms）→ 事件识别
4. **平滑过渡**：音乐参数使用 EMA 平滑，避免突变
5. **安全保护**：参数限幅、冲突仲裁、紧急停止

---

## 2. 手势识别体系 — AI 模型驱动

### 2.1 手势分类总览

```
                    指挥手势体系（AI 模型分类）
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   节拍类 (右手主)    力度类 (左手主)   控制类 (双手)
        │                │                │
   ┌────┴────┐     ┌─────┴─────┐    ┌────┴─────┐
  Downbeat  Tempo   Crescendo  Decrescendo  Cutoff  Style
  (下拍)   Change   (渐强)     (渐弱)      (切断)  Switch
           (变速)                            (风格切换)
        │                                         │
        └───────────── Idle (空闲) ───────────────┘
```

**核心原则**：离散手势（Downbeat/Cutoff/Style Switch）由 AI 模型分类识别；连续参数（BPM/音量/能量）由特征工程 + 回归模型估计。规则仅用于安全事件（Emergency Stop）。

### 2.2 AI 手势分类模型设计

#### 2.2.1 模型输入：多模态特征向量

模型不直接处理原始图像（MediaPipe 已完成这一步），而是接收**已提取的结构化特征**。

**单帧特征维度**（每个 fused_frame 包含）：

```
┌─────────────────────────────────────────────────────────┐
│  摄像头特征（来自 MediaPipe，camera.py 已提取）          │
│  ├── 左手 21 个关键点 (x,y,z) 归一化坐标    = 63 维     │
│  ├── 右手 21 个关键点 (x,y,z) 归一化坐标    = 63 维     │
│  ├── 左手：palm_center, openness, finger_states(5),     │
│  │         pinch_distance, wrist_velocity(3),           │
│  │         motion_direction                             │
│  ├── 右手：同上                                       │
│  ├── 双手距离                                         │
│  └── 双手高度差                                       │
│                                                         │
│  ESP32 特征（WiFi IMU）                              │
│  ├── 左手：ax, ay, az (g), pitch, roll, jerk, energy  │
│  └── 右手：同上                                       │
│                                                         │
│  总计：~140+ 维特征 / 帧                                │
└─────────────────────────────────────────────────────────┘
```

#### 2.2.2 时间窗口特征工程

单个帧不包含运动信息，需要**滑动窗口聚合**（这部分代码在 `pi_pc/window.py` 已有框架）：

```
窗口大小：800ms（约 20-24 帧 @ 30fps）
步长：100ms

窗口级特征:
  • 各维度的 mean, std, min, max
  • 手腕轨迹长度、净位移
  • 速度/加速度的峰值、过零率
  • 方向变化次数
  • 手掌开合度的变化范围
  • IMU 的频域特征（主导频率 → BPM 估计）
  • jerk 峰值和峰值密度
  • 双手协调特征（距离变化、相位差）

最终特征向量：~300-500 维（取决于特征工程选择）
```

#### 2.2.3 模型选型对比

| 模型 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **Random Forest** | 训练快、可解释、小样本友好、特征重要性可分析 | 无法利用时序结构（需手动做窗口特征） | ⭐⭐⭐⭐⭐ **首选** |
| **XGBoost / LightGBM** | 比 RF 精度更高、支持正则化 | 需要更多调参 | ⭐⭐⭐⭐ |
| **LSTM** | 原生处理时序、可学习长程依赖 | 需要大量数据、训练慢、调参困难 | ⭐⭐⭐ |
| **1D-CNN** | 自动学习局部时序模式 | 需要较多数据 | ⭐⭐⭐ |
| **小型 Transformer** | 全局注意力、SOTA 精度 | 数据需求大、部署复杂 | ⭐⭐ |

**推荐路径**：先 Random Forest（快速验证）→ 积累数据后尝试 XGBoost → 数据充足后考虑 LSTM。

#### 2.2.4 模型输出规范

与现有 `backend/model_service.py` 的接口完全对齐：

```python
# model/inference.py — GestureClassifier.predict(window_data) 返回值
{
    "gesture": "downbeat",          # 识别出的手势标签
    "gesture_id": 1,                # 手势 ID (1=downbeat, 2=crescendo, ...)
    "confidence": 0.92,             # 置信度 [0, 1]
    "timestamp": 1721052000.500,    # Unix 时间戳
    "features_used": [              # 实际使用的特征列表
        "right_wrist_vy_std",
        "right_jerk_max",
        "left_wrist_y_range",
        ...
    ],
    "all_probs": {                  # 所有手势的概率分布
        "idle": 0.01,
        "downbeat": 0.92,
        "crescendo": 0.02,
        "decrescendo": 0.01,
        "cutoff": 0.01,
        "style_switch": 0.01,
        "tempo_up": 0.01,
        "tempo_down": 0.01
    }
}
```

### 2.3 AI + 规则的合理分工

并不是完全不用规则——而是**规则只做它能做好的事**：

| 功能 | 方案 | 原因 |
|------|------|------|
| **离散手势识别**（downbeat/crescendo/cutoff/style_switch） | **AI 模型** | 模式复杂、个体差异大、规则难以覆盖 |
| **连续参数估计**（BPM/音量/能量） | **特征工程 + 回归/公式** | 有明确的物理含义，公式可直接映射 |
| **紧急停止**（ESP32 按键长按） | **规则** | 必须零延迟、100% 可靠，不能用概率模型 |
| **ESP32 按键控制**（开始/暂停/校准） | **规则** | 确定性操作，无需 AI |
| **安全限幅**（参数裁剪、冲突仲裁） | **规则** | 保护性逻辑，必须确定 |

```
                    ┌──────────────────┐
                    │   fused_frame    │
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌──────────────────┐        ┌──────────────────┐
    │  滑动窗口聚合     │        │  ESP32 按键解析   │
    │  (window.py)     │        │  (packet_parser)  │
    └────────┬─────────┘        └────────┬─────────┘
             │                           │
             ▼                           ▼
    ┌──────────────────┐        ┌──────────────────┐
    │  AI 模型推理      │        │  规则引擎         │
    │  GestureClassifier│        │  (安全事件)       │
    │  → 离散手势       │        │  → 紧急停止       │
    │  → 连续参数趋势   │        │  → 按钮控制       │
    └────────┬─────────┘        └────────┬─────────┘
             │                           │
             └──────────┬────────────────┘
                        ▼
              ┌──────────────────┐
              │  意图仲裁器       │
              │  (优先级 + 冷却)  │
              └────────┬─────────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
         音乐控制 (OSC)    LED 灯效 (TCP)
```

### 2.4 连续参数估计（补充 AI 模型）

离散手势之外，以下连续参数使用**公式直接计算**（因为它们有明确的物理含义）：

#### BPM 估计

```python
class BPMEstimator:
    """从手腕周期性运动估计指挥节拍速度"""
    
    def estimate(self, window_features: dict) -> float:
        # 方法1：摄像头手腕 Y 速度的过零率
        vy_sequence = window_features["right_wrist"]["vy_sequence"]  # 800ms 的速度序列
        zero_crossings = count_zero_crossings(vy_sequence)
        estimated_bpm = (zero_crossings / 2) * (60 / 0.8)  # 每拍2次过零
        
        # 方法2：ESP32 加速度幅值的主频
        acc_magnitudes = window_features["right_microbit"]["acc_magnitude_sequence"]
        dominant_freq = find_dominant_frequency(acc_magnitudes, sample_rate=25)
        bpm_from_imu = dominant_freq * 60
        
        # 融合（摄像头更可靠，权重更高）
        return estimated_bpm * 0.7 + bpm_from_imu * 0.3
```

#### 力度/音量估计

```python
class IntensityEstimator:
    """从手部运动幅度估计指挥力度"""
    
    def estimate(self, window_features: dict) -> tuple[float, float]:
        # 左手腕 Y 坐标范围 → 音量（幅度越大 → 越响）
        left_wrist_y_range = window_features["left_hand"]["wrist_y_range"]
        volume = normalize(left_wrist_y_range, min=0.05, max=0.5)  # → [0, 1]
        
        # 整体运动能量 → 音乐能量
        left_energy = window_features["left_microbit"]["motion_energy"]
        right_energy = window_features["right_microbit"]["motion_energy"]
        energy = (left_energy * 0.6 + right_energy * 0.4)  # 左手权重更高
        
        return volume, energy
```

### 2.5 手势优先级与冲突仲裁

```
优先级从高到低:
  1. Emergency Stop (ESP32 按键长按)     — 规则，不可覆盖
  2. Cutoff (AI 识别或规则辅助)          — 覆盖所有音乐操作
  3. Downbeat (AI 识别)                — 节拍锚点
  4. Style Switch (AI 识别或 ESP32 按键)— 段落切换
  5. Tempo Up/Down (BPM 趋势)          — 连续 BPM 调整
  6. Crescendo/Decrescendo (连续参数)   — 音量渐变
  7. Idle                              — 默认状态
```

---

## 3. 代号映射协议（PC ↔ 树莓派 ↔ 外设）

### 3.0 设计原则

```
┌──────────────────────────────────────────────────────────────┐
│                       PC 后端（大脑）                         │
│                                                              │
│  AI 模型 → 手势标签 → 查 SQLite → 得到 gesture_code          │
│                                    │                         │
│                    ┌───────────────┴───────────────┐         │
│                    ▼                               ▼         │
│          发送 gesture_code               发送 OSC 命令       │
│          给树莓派 (TCP)                  给 Sonic Pi (UDP)   │
└────────────────────┬──────────────────────┬─────────────────┘
                     │                      │
                     ▼                      ▼
         ┌──────────────────────┐  ┌──────────────────┐
         │  树莓派（执行器）    │  │  Sonic Pi (PC本地)│
         │                      │  │  音乐合成          │
         │  代号 → LED指令(GPIO)│  └──────────────────┘
         │  代号 → WiFi指令  │
         └──────┬───────┬───────┘
                │       │
         GPIO18 │       │ WiFi TCP
                ▼       ▼
         ┌──────────┐ ┌──────────────────┐
         │左右手灯带 │ │ 左右手 ESP32     │
         │8×32 WS2812│ │ NeoPixel + 蜂鸣器 │
         └──────────┘ └──────────────────┘
         └──────────────────┘
```

**为什么 PC 直控 Sonic Pi 而不是通过树莓派转发？**
- Sonic Pi 和 PC 后端运行在同一台机器上，OSC over UDP 走 localhost，延迟 < 1ms
- 如果走 PC→Pi→OSC→PC 路径，延迟增加网络往返 + 增加故障点
- 如果后续需要物理蜂鸣器，可以在树莓派 GPIO 上增加，由 gesture_code 同时触发

### 3.1 手势代号定义 (gesture_code)

这是整个系统的**唯一真相源**。无论 PC、树莓派、Sonic Pi，都通过这个编号理解"当前是什么手势"。

```
gesture_code  |  手势名称       |  触发方式            |  方向
──────────────┼─────────────────┼─────────────────────┼────────
     0        |  idle           |  无手势/超时回退     |  -
     1        |  downbeat       |  AI 模型识别         |  右手
     2        |  crescendo      |  AI 模型识别         |  左手
     3        |  decrescendo    |  AI 模型识别         |  左手
     4        |  cutoff         |  AI 模型识别         |  双手
     5        |  style_switch   |  AI 模型识别/按钮    |  双手
     6        |  tempo_up       |  BPM 趋势检测        |  右手
     7        |  tempo_down     |  BPM 趋势检测        |  右手
     8        |  emergency_stop |  ESP32 按键长按(规则) |  -
     9        |  start_signal   |  ESP32 按键(规则)     |  -
    10        |  pause_signal   |  ESP32 按键(规则)     |  -
```

### 3.2 PC 端数据库映射表（SQLite）

存在 `backend/database.py` 的 SQLite 中，建表语句：

```sql
CREATE TABLE IF NOT EXISTS gesture_code_mappings (
    gesture_code    INTEGER PRIMARY KEY,
    gesture_name    TEXT    NOT NULL,
    -- 音乐参数（给 Sonic Pi OSC）
    music_action    TEXT,           -- none / trigger_beat / adjust_volume / 
                                    -- stop_or_mute / change_style / adjust_tempo
    bpm_delta       REAL    DEFAULT 0,
    volume_delta    REAL    DEFAULT 0,
    volume_target   REAL,
    energy_target   REAL,
    style_name      TEXT,
    -- LED 参数（树莓派根据 gesture_code 自行查表执行）
    led_effect      TEXT    NOT NULL,  -- 灯效名称
    led_priority    INTEGER DEFAULT 0  -- 优先级 (高→低: 100→0)
);

-- 预置数据
INSERT INTO gesture_code_mappings VALUES
--  code,  name,          music_action,    bpm_delta, vol_delta, vol_tgt, energy, style,             led_effect,       priority
    (0,   'idle',          'none',          0,         0,         NULL,    NULL,   NULL,              'breathing',       0),
    (1,   'downbeat',      'trigger_beat',  0,         0,         NULL,    NULL,   NULL,              'accent_flash',    60),
    (2,   'crescendo',     'adjust_volume', 0,         5,         NULL,    NULL,   NULL,              'intensity_glow',  20),
    (3,   'decrescendo',   'adjust_volume', 0,        -5,         NULL,    NULL,   NULL,              'intensity_glow',  20),
    (4,   'cutoff',        'stop_or_mute',  0,         0,         0,       0,      NULL,              'instant_black',   80),
    (5,   'style_switch',  'change_style',  0,         0,         NULL,    NULL,   'warm_classical',  'palette_sweep',   40),
    (6,   'tempo_up',      'adjust_tempo',  5,         0,         NULL,    NULL,   NULL,              'tempo_meter',     20),
    (7,   'tempo_down',    'adjust_tempo', -5,         0,         NULL,    NULL,   NULL,              'tempo_meter',     20),
    (8,   'emergency_stop','stop_or_mute',  0,         0,         0,       0,      NULL,              'emergency_red',   100),
    (9,   'start_signal',  'start',         0,         0,         NULL,    NULL,   NULL,              'breathing',       10),
    (10,  'pause_signal',  'pause',         0,         0,         NULL,    NULL,   NULL,              'breathing',       10);
```

### 3.3 PC → 树莓派 下行消息格式

**极简设计 — 只发代号和必要参数：**

```json
{
  "message_type": "gesture_command",
  "gesture_code": 1,
  "confidence": 0.92,
  "timestamp_ms": 1721052000500,
  "params": {
    "bpm": 112.0,
    "energy": 0.78,
    "volume": 0.85
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message_type` | string | ✓ | 固定 `"gesture_command"` |
| `gesture_code` | int | ✓ | 0-10，见 3.1 表 |
| `confidence` | float | | AI 置信度，仅 AI 识别的手势携带 |
| `timestamp_ms` | int | | PC 发送时的 Unix 毫秒时间戳 |
| `params.bpm` | float | | 当前估计 BPM（用于灯带动画同步） |
| `params.energy` | float | | 当前能量值 [0, 1] |
| `params.volume` | float | | 当前音量 [0, 1] |

**设计要点**：
- 树莓派**不需要知道**音乐的具体参数（BPM 怎么改、音量调到多少），只需要知道 `gesture_code` 就能执行正确的灯效
- `params` 里的 bpm/energy/volume 是给灯效渲染用的"调味料"（如呼吸频率、亮度、色相），不影响核心逻辑
- 即使 `params` 为空，树莓派也能根据 `gesture_code` 独立执行灯效

### 3.4 树莓派本地映射表

硬编码在 `hardware/raspberry_pi_iot/led/gesture_effects.py`（新文件）：

```python
"""Gesture → LED Effect Mapping

每个 gesture_code 对应一个确定的灯效函数。
树莓派收到 PC 下行 gesture_code 后，查此表执行。
"""

from enum import IntEnum

class GestureCode(IntEnum):
    IDLE = 0
    DOWNBEAT = 1
    CRESCENDO = 2
    DECRESCENDO = 3
    CUTOFF = 4
    STYLE_SWITCH = 5
    TEMPO_UP = 6
    TEMPO_DOWN = 7
    EMERGENCY_STOP = 8
    START_SIGNAL = 9
    PAUSE_SIGNAL = 10


# ──── 映射表：gesture_code → (灯效函数名, 左手模式, 右手模式, 优先级) ────

GESTURE_EFFECT_MAP = {
    GestureCode.IDLE: {
        "left": "breathing",
        "right": "breathing",
        "priority": 0,
        "transition_ms": 500,
    },
    GestureCode.DOWNBEAT: {
        "left": "accent_flash",
        "right": "accent_flash",   # 右手更亮（在渲染时根据 hand 参数区分）
        "priority": 60,
        "duration_ms": 120,
    },
    GestureCode.CRESCENDO: {
        "left": "intensity_glow",  # ← 左手：亮度+色相变化
        "right": "breathing",      # ← 右手：温和跟随
        "priority": 20,
        "transition_ms": 300,
    },
    GestureCode.DECRESCENDO: {
        "left": "intensity_glow",  # ← 左手：亮度+色相反向变化
        "right": "breathing",
        "priority": 20,
        "transition_ms": 300,
    },
    GestureCode.CUTOFF: {
        "left": "instant_black",
        "right": "instant_black",
        "priority": 80,
        "duration_ms": 500,
    },
    GestureCode.STYLE_SWITCH: {
        "left": "palette_sweep",
        "right": "palette_sweep",
        "priority": 40,
        "transition_ms": 500,
    },
    GestureCode.TEMPO_UP: {
        "left": "breathing",       # 左手：呼吸频率加快
        "right": "tempo_meter",    # ← 右手：流速表加速
        "priority": 20,
        "transition_ms": 200,
    },
    GestureCode.TEMPO_DOWN: {
        "left": "breathing",
        "right": "tempo_meter",    # ← 右手：流速表减速
        "priority": 20,
        "transition_ms": 200,
    },
    GestureCode.EMERGENCY_STOP: {
        "left": "emergency_red",
        "right": "emergency_red",
        "priority": 100,           # 最高优先级，不可打断
        "duration_ms": 0,          # 持续直到手动解除
    },
    GestureCode.START_SIGNAL: {
        "left": "breathing",
        "right": "breathing",
        "priority": 10,
        "transition_ms": 500,
    },
    GestureCode.PAUSE_SIGNAL: {
        "left": "breathing",
        "right": "breathing",
        "priority": 10,
        "transition_ms": 500,
    },
}
```

### 3.5 PC → Sonic Pi OSC 映射

这部分由 PC 后端直接完成（不经树莓派），根据同一份数据库映射表：

```python
# backend/gesture_dispatcher.py — PC 发送双信号的统一入口

class GestureDispatcher:
    """收到 AI 模型的手势结果后，同时发出两个信号"""
    
    def __init__(self, db, tcp_to_pi, sonic_pi_adapter):
        self.db = db
        self.pi = tcp_to_pi     # TCP 下行发送器
        self.sp = sonic_pi_adapter
    
    def dispatch(self, gesture_code: int, confidence: float, 
                 music_state: dict, window_features: dict):
        """核心方法：代号 → 双信号"""
        
        # 1. 查数据库映射表
        mapping = self.db.get_gesture_mapping(gesture_code)
        if mapping is None:
            return
        
        # 2. 信号 1：发送代号给树莓派（LED灯带）
        self.pi.send_gesture_command({
            "message_type": "gesture_command",
            "gesture_code": gesture_code,
            "confidence": confidence,
            "timestamp_ms": int(time.time() * 1000),
            "params": {
                "bpm": music_state.get("bpm", 120),
                "energy": music_state.get("energy", 0.5),
                "volume": music_state.get("volume", 0.5),
            }
        })
        
        # 3. 信号 2：直接 OSC 给 Sonic Pi（音乐）
        music_action = mapping["music_action"]
        if music_action == "trigger_beat":
            self.sp.send_accent(confidence, "downbeat")
        elif music_action == "adjust_volume":
            new_volume = clamp(music_state["volume"] + mapping["volume_delta"] / 100)
            self.sp.send_state_from_music({**music_state, "volume": new_volume})
        elif music_action == "adjust_tempo":
            new_bpm = clamp(music_state["bpm"] + mapping["bpm_delta"], 72, 148)
            self.sp.send_bpm(new_bpm)
        elif music_action == "stop_or_mute":
            self.sp.send_transport("cutoff")
        elif music_action == "change_style":
            self.sp.send_state_from_music({**music_state, 
                "style": mapping["style_name"]})
        elif music_action == "start":
            self.sp.send_transport("start")
        elif music_action == "pause":
            self.sp.send_transport("pause")
```

### 3.6 完整数据流（以 Downbeat 为例）

```
时间线：一次 Downbeat 手势从发生到反馈的全过程

t=0ms   指挥者右手下击
t=15ms  摄像头捕捉帧 + ESP32 检测到 jerk 尖峰
t=25ms  树莓派融合引擎生成 fused_frame
t=30ms  TCP JSON Lines 到达 PC 后端（上行）
t=32ms  滑动窗口累积完成 → 特征向量提取
t=35ms  AI 模型推理：GestureClassifier.predict() → "downbeat" + confidence=0.92
t=36ms  GestureDispatcher.dispatch(gesture_code=1)
        │
        ├── 信号 1 (TCP → Pi): {"message_type":"gesture_command","gesture_code":1,...}
        │      t=38ms  树莓派收到 → 查三张映射表:
        │               ├── GESTURE_EFFECT_MAP[1] → LED 灯带 accent_flash
        │               │   t=39ms  LedController 全白闪烁 ← 用户看到灯带
        │               │   t=160ms 闪烁衰减 → breathing
        │               └── GESTURE_ESP32_MAP[1] → WiFi 下行
        │                   t=39ms  发 LED,FLASH→右手 ESP32 NeoPixel
        │                   t=40ms  右手 NeoPixel 灯环全亮 ← 手腕确认
        │                   t=39ms  发 LED,FLASH→左手 ESP32 NeoPixel
        │                   t=39ms  发 BEEP→ESP32 蜂鸣器短鸣
        │
        └── 信号 2 (OSC → Sonic Pi): /conductor/accent cmd-xxx 0.92 downbeat
               t=37ms  Sonic Pi 收到 → cue :manual_accent
               t=40ms  Sonic Pi 播放强音镲+低音鼓 ← 用户听到重音
```

**关键延迟指标**：
- 手势发生 → AI 识别完成：~35ms
- AI 识别 → LED 灯带响应：~5ms（PC→Pi TCP + GPIO 渲染）
- AI 识别 → ESP32 响应：~6ms（PC→Pi TCP + Pi→ESP32 WiFi）
- AI 识别 → 音乐响应：~2ms（PC→Sonic Pi localhost OSC）
- **总延迟（手势→灯光+ESP32+音乐）：~40ms，人无法感知**

### 3.7 TCP 双向通信实现要点

当前 `TcpJsonlClient` 已有 `_reader` 字段但未使用。需要新增：

```python
# hardware/pi_pc/tcp_client.py — 新增下行接收

class TcpJsonlClient:
    # ... 现有代码保持不变 ...
    
    def set_downlink_callback(self, callback):
        """设置下行消息回调（PC → Pi）"""
        self._on_downlink = callback
    
    async def _receive_loop(self):
        """后台任务：读取 PC 下行消息"""
        while self._connected:
            try:
                line = await self._reader.readline()
                if not line:
                    raise ConnectionError("Connection closed")
                msg = json.loads(line.decode())
                if self._on_downlink:
                    self._on_downlink(msg)
            except Exception:
                await asyncio.sleep(0.1)
```

在 `main.py` 中连接：

```python
# 设置下行回调：PC 的 gesture_command → LED 控制器
self._tcp_client.set_downlink_callback(self._handle_downlink)

def _handle_downlink(self, msg: dict):
    if msg.get("message_type") == "gesture_command":
        code = msg["gesture_code"]
        effect = GESTURE_EFFECT_MAP.get(GestureCode(code))
        if effect and self._led_controller:
            self._led_controller.apply_gesture_effect(
                code, 
                msg.get("params", {})
            )
```

### 3.8 树莓派 → ESP32 WiFi 下行指令

PC 的 gesture_code 到达树莓派后，除了驱动 LED 灯带，同时通过 **WiFi TCP** 向左右手腕的 ESP32 发送指令，利用 ESP32 控制外接的蜂鸣器和 NeoPixel 灯环，提供手腕级的即时反馈。

#### 3.8.1 通信架构

```
PC (gesture_code) ──TCP──→ 树莓派 ──WiFi TCP──→ ESP32 (左手)
                           │                      ├── NeoPixel 灯环 (8-16 LED)
                           │                      └── GPIO 蜂鸣器
                           │
                           └──WiFi TCP──→ ESP32 (右手)
                                                  ├── NeoPixel 灯环 (8-16 LED)
                                                  └── GPIO 蜂鸣器
```

**ESP32 规格**（每手腕一个）：
- 芯片：ESP32-S3 或 ESP32-C3
- 通信：WiFi 802.11n，TCP Client 连接树莓派
- 传感器：板载 IMU（MPU6050 / MPU9250），替代原 Micro:bit 加速度计
- 输出：GPIO 接蜂鸣器 + NeoPixel 灯环（8-16 灯珠）
- 协议：与上行共享同一 TCP 长连接，双向 JSON Lines

**需新增**：
- 树莓派端 ESP32 TCP 管理器（连接管理 + 上下行复用）
- ESP32 端固件（Arduino / MicroPython）：解析指令并执行
- 树莓派端根据 gesture_code 查表发送 WiFi 下行指令

#### 3.8.2 指令格式

下行沿用 JSON Lines 格式（与整体架构统一）：

```json
{"type":"led","pattern":"FLASH","brightness":100}
{"type":"beep","freq_hz":800,"duration_ms":50}
{"type":"state","code":1}
{"type":"stop"}
```

| type | 字段 | 示例 | 说明 |
|------|------|------|------|
| **led** | `pattern`, `brightness` | `{"type":"led","pattern":"FLASH","brightness":80}` | ESP32 控制 NeoPixel 灯环 |
| **beep** | `freq_hz`, `duration_ms` | `{"type":"beep","freq_hz":1000,"duration_ms":100}` | GPIO 蜂鸣器 PWM |
| **state** | `code` | `{"type":"state","code":1}` | 同步系统状态 |
| **stop** | — | `{"type":"stop"}` | 停止 LED 和蜂鸣器 |

#### 3.8.3 Pattern 定义

ESP32 固件中预置 NeoPixel 灯环图案：

| pattern | 说明 | 灯环效果 |
|---------|------|---------|
| `FLASH` | 全环白光，快速衰减 | 全部灯珠 #FFFFFF → 指数衰减 |
| `ARROW_UP` | ↑ 方向指示 | 顶部灯珠亮起，两侧渐变暗 |
| `ARROW_DN` | ↓ 方向指示 | 底部灯珠亮起，两侧渐变暗 |
| `HEART` | 心跳脉冲 | 双脉冲（lub-dub）节奏 |
| `CROSS` | 红光 X（切断） | 全环红色快闪 2 次 |
| `SQUARE` | 方框循环 | 四个方向依次点亮 |
| `BREATHING` | 慢速呼吸明灭 | 正弦 0→100→0 |
| `PULSE` | 单次脉冲 | 亮度瞬时 100% → 指数衰减 |
| `OFF` | 全灭 | 全部灯珠熄灭 |

#### 3.8.4 gesture_code → ESP32 下行指令映射表

| gesture_code | 左手 ESP32 | 右手 ESP32 | 蜂鸣器 |
|:-----------:|-----------|-----------|:-----:|
| 0 (idle) | `led,BREATHING,30` | `led,BREATHING,30` | — |
| 1 (downbeat) | `led,FLASH,60` | **`led,FLASH,100`** | `beep,800,50` |
| 2 (crescendo) | **`led,ARROW_UP,80`** | `led,BREATHING,40` | — |
| 3 (decrescendo) | **`led,ARROW_DN,80`** | `led,BREATHING,40` | — |
| 4 (cutoff) | `led,CROSS,100` | `led,CROSS,100` | — |
| 5 (style_switch) | `led,SQUARE,70` | `led,SQUARE,70` | `beep,1200,30` |
| 6 (tempo_up) | `led,BREATHING,50` | **`led,ARROW_UP,70`** | `beep,1000,30` |
| 7 (tempo_down) | `led,BREATHING,50` | **`led,ARROW_DN,70`** | `beep,600,30` |
| 8 (emergency) | `led,FLASH,100` | `led,FLASH,100` | `beep,2000,200` |
| 9 (start) | `led,HEART,80` | `led,HEART,80` | `beep,800,100` |
| 10 (pause) | `led,BREATHING,30` | `led,BREATHING,30` | — |

**设计原则**：
- 右手（节拍手）亮度 > 左手 — `FLASH,100` vs `FLASH,60`
- 力度变化 → 左手 NeoPixel 显示方向
- BPM 变化 → 右手 NeoPixel 显示方向
- 蜂鸣器做节拍提示音，不替代 Sonic Pi

#### 3.8.5 树莓派端实现

```python
# hardware/pi_pc/esp32_manager.py — 新增文件

GESTURE_ESP32_MAP = {
    0:  {"left": {"type":"led","pattern":"BREATHING","brightness":30},
         "right": {"type":"led","pattern":"BREATHING","brightness":30}},
    1:  {"left": {"type":"led","pattern":"FLASH","brightness":60},
         "right": {"type":"led","pattern":"FLASH","brightness":100},
         "beep": {"type":"beep","freq_hz":800,"duration_ms":50}},
    2:  {"left": {"type":"led","pattern":"ARROW_UP","brightness":80},
         "right": {"type":"led","pattern":"BREATHING","brightness":40}},
    3:  {"left": {"type":"led","pattern":"ARROW_DN","brightness":80},
         "right": {"type":"led","pattern":"BREATHING","brightness":40}},
    4:  {"left": {"type":"led","pattern":"CROSS","brightness":100},
         "right": {"type":"led","pattern":"CROSS","brightness":100}},
    5:  {"left": {"type":"led","pattern":"SQUARE","brightness":70},
         "right": {"type":"led","pattern":"SQUARE","brightness":70},
         "beep": {"type":"beep","freq_hz":1200,"duration_ms":30}},
    6:  {"left": {"type":"led","pattern":"BREATHING","brightness":50},
         "right": {"type":"led","pattern":"ARROW_UP","brightness":70},
         "beep": {"type":"beep","freq_hz":1000,"duration_ms":30}},
    7:  {"left": {"type":"led","pattern":"BREATHING","brightness":50},
         "right": {"type":"led","pattern":"ARROW_DN","brightness":70},
         "beep": {"type":"beep","freq_hz":600,"duration_ms":30}},
    8:  {"left": {"type":"led","pattern":"FLASH","brightness":100},
         "right": {"type":"led","pattern":"FLASH","brightness":100},
         "beep": {"type":"beep","freq_hz":2000,"duration_ms":200}},
    9:  {"left": {"type":"led","pattern":"HEART","brightness":80},
         "right": {"type":"led","pattern":"HEART","brightness":80},
         "beep": {"type":"beep","freq_hz":800,"duration_ms":100}},
    10: {"left": {"type":"led","pattern":"BREATHING","brightness":30},
         "right": {"type":"led","pattern":"BREATHING","brightness":30}},
}


class Esp32Manager:
    """管理树莓派与左右手 ESP32 之间的 WiFi TCP 双向连接
    
    ESP32 作为 TCP Client 连接树莓派 TCP Server。
    上行：ESP32 → Pi (IMU 传感器数据)
    下行：Pi → ESP32 (LED + 蜂鸣器指令)
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9001):
        self._host = host
        self._port = port
        self._server = None
        self._clients: dict[str, asyncio.StreamWriter] = {}  # device_id → writer
    
    async def start(self):
        """启动 TCP Server，等待 ESP32 连接"""
        self._server = await asyncio.start_server(
            self._handle_esp32_connection, self._host, self._port
        )
    
    async def dispatch_gesture(self, gesture_code: int):
        """根据 gesture_code 向左右手 ESP32 发下行指令"""
        mapping = GESTURE_ESP32_MAP.get(gesture_code)
        if mapping is None:
            return
        
        tasks = []
        for hand in ("left", "right"):
            device_id = f"ESP32_{hand.upper()}"
            writer = self._clients.get(device_id)
            if writer and hand in mapping:
                msg = json.dumps(mapping[hand]) + "\n"
                tasks.append(self._send_to(writer, msg))
        
        # 蜂鸣器发到右手 ESP32（如不可用则发左手）
        if "beep" in mapping:
            beep_msg = json.dumps(mapping["beep"]) + "\n"
            for device_id in ("ESP32_RIGHT", "ESP32_LEFT"):
                writer = self._clients.get(device_id)
                if writer:
                    tasks.append(self._send_to(writer, beep_msg))
                    break
        
        if tasks:
            await asyncio.gather(*tasks)
    
    async def _send_to(self, writer, msg: str):
        """发送 JSON Lines 到指定 ESP32"""
        try:
            writer.write(msg.encode())
            await writer.drain()
        except Exception:
            pass  # 容忍发送失败，不阻塞主流程
```

#### 3.8.6 ESP32 端固件（MicroPython / Arduino）需实现

```
WiFi 连接:
  连接同一局域网 → TCP Client 连接树莓派 9001 端口

上行 (周期性, ~50Hz):
  读取 IMU 数据 (加速度/陀螺仪) → JSON Lines → TCP 发送

下行 (中断接收):
  TCP 收到 JSON 行 → 解析 type:
  
  type == "led":
      在 NeoPixel 灯环上执行 pattern 动画
      FLASH: 全部灯珠白亮 + 指数衰减
      ARROW_UP/DN: 方向指示
      HEART: 双脉冲
      BREATHING: 正弦明灭
      
  type == "beep":
      GPIO 引脚 PWM 输出指定频率和时长
      
  type == "stop":
      关闭灯环 + 停止蜂鸣器
```

### 3.9 Style Switch 循环切换逻辑

**机制**：每次触发 `style_switch`，在 4 种预设风格中切换到下一个，首尾相连循环。

```
触发顺序: warm_classical → cool_electronic → minimal_piano → dramatic → warm_classical → ...
```

**PC 端实现**：

```python
# backend/gesture_dispatcher.py — Style Switch 循环逻辑

STYLES = ["warm_classical", "cool_electronic", "minimal_piano", "dramatic"]
_current_style_index = 0  # 全局状态，初始为 warm_classical

def _handle_style_switch(self):
    global _current_style_index
    _current_style_index = (_current_style_index + 1) % len(STYLES)
    next_style = STYLES[_current_style_index]
    
    # 查数据库得到该风格的 OSC 参数预设
    preset = STYLE_PRESETS[next_style]
    
    # 信号1: 更新 music_state，发出 OSC 给 Sonic Pi
    self.osc.send_state_from_music({
        **self.music_state,
        "style": next_style,
        "reverb_mix": preset["reverb_mix"],
        "cutoff": preset["cutoff"],
        "energy": preset["energy"],
    })
    
    # 信号2: 发 gesture_code=5 给树莓派（带 style 参数用于调色板切换）
    self.pi.send_gesture_command({
        "message_type": "gesture_command",
        "gesture_code": 5,  # style_switch
        "params": {"style": next_style}
    })
```

**4 种风格的音乐参数预设**：

| 风格 | reverb_mix | cutoff | energy | 适合音乐类型 |
|------|:----------:|:------:|:------:|-------------|
| warm_classical | 0.35 | 100 | 0.60 | 管弦乐 |
| cool_electronic | 0.15 | 120 | 0.80 | 电子/流行 |
| minimal_piano | 0.50 | 80 | 0.40 | 钢琴独奏 |
| dramatic | 0.70 | 130 | 0.95 | 电影配乐 |

### 3.10 MusicControlState 完整定义

这是 PC 端维护的音乐状态对象，每次 AI 识别出结果后更新，发送 OSC 时从此对象取值：

```python
@dataclass
class MusicControlState:
    playing: bool = True
    bpm: float = 108.0
    master_amp: float = 0.8
    drum_amp: float = 0.75
    bass_amp: float = 0.55
    harmony_amp: float = 0.45
    melody_amp: float = 0.85
    energy: float = 0.62
    drum_density: float = 0.7
    reverb_mix: float = 0.25
    cutoff: float = 95.0
    style: str = "warm_classical"
    section: str = "main"
```

---

## 4. LED 灯光信号（信号 2）

### 4.1 信号路径

```
┌─────────────────────────────────────────────────────┐
│                   PC 后端                            │
│                                                      │
│  手势识别 ──→ MusicIntentMapper                      │
│                  │                                   │
│                  ├──→ OSC → Sonic Pi (音乐)          │
│                  │                                   │
│              ┌───▼──────────────┐                    │
│              │  LedEffectEngine │                    │
│              │  - 节拍→闪光     │                    │
│              │  - 力度→亮度     │                    │
│              │  - 能量→色相     │                    │
│              │  - 风格→调色板   │                    │
│              │  - BPM→动画速度 │                    │
│              └───┬──────────────┘                    │
│                  │                                   │
│           led_state / led_command                    │
│           (TCP JSON Lines 下行 :9000)                │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│              树莓派 LED 驱动                          │
│                                                      │
│  接收 PC 指令 → 解析 effect → 渲染到 PixelStrip       │
│                                                      │
│  ┌─────────────┐    ┌─────────────┐                  │
│  │ 左手灯带     │    │ 右手灯带     │                  │
│  │ (LED 0-255) │    │ (LED 256-511)│                  │
│  │ 8×32 WS2812B│    │ 8×32 WS2812B│                  │
│  │ [力度/能量] │    │ [节拍/节奏] │                  │
│  └─────────────┘    └─────────────┘                  │
└─────────────────────────────────────────────────────┘
```

### 4.2 左右手灯带功能分工

| 维度 | 左手灯带 (力度面板) | 右手灯带 (节拍面板) |
|------|-------------------|---------------------|
| **核心语义** | 表情、力度、能量 | 节拍、BPM、节奏 |
| **主要输入** | volume/energy 参数 | BPM/beat/bar 参数 |
| **亮度和颜色** | 力度越大越亮、偏暖 | 节拍越密闪烁越快 |
| **节拍响应** | 温和呼吸，不闪 | 每拍强闪（downbeat 最强） |
| **风格切换** | 整体色相偏移 | 整体色相偏移 |

### 4.3 灯效模式定义

#### 4.3.1 基础灯效（已实现）

| 模式 | 描述 | 触发条件 |
|------|------|---------|
| `idle` | 全灭 | 系统未启动 |
| `breathing` | 慢速正弦呼吸，BPM 同步 | 无事件时的默认状态 |
| `beat_pulse` | 拍点白蓝闪光 + 指数衰减 | 每个 downbeat |
| `wave` | 高斯波横扫 | 过渡动画 |

#### 4.3.2 新增灯效（本设计扩展）

| 模式 | 描述 | 适用手势 | 面板 |
|------|------|---------|------|
| **`intensity_glow`** | 亮度映射到 volume，色相蓝→红渐变 | Crescendo/Decrescendo | 左手 |
| **`tempo_meter`** | LED 按 BPM 频率从左到右流水 | Tempo Up/Down | 右手 |
| **`instant_black`** | 瞬间全黑 | Cutoff | 双手 |
| **`palette_sweep`** | 色相从旧调色板过渡到新调色板 | Style Switch | 双手 |
| **`accent_flash`** | 全屏白光→快速衰减，按 strength 调节 | Downbeat (强拍) | 双手 |
| **`emergency_red`** | 红色快闪 | Emergency Stop | 双手 |
| **`error_blink`** | 黄色慢闪 | 设备断连 | 对应手面板 |

### 4.4 LED 下行协议设计

#### 持续状态（led_state）— 周期性发送

```json
{
  "message_type": "led_state",
  "sequence": 8031,
  "timestamp": 1721052000.500,
  "music_sync": {
    "bpm": 112.0,
    "beat": 3,
    "bar": 18,
    "section": "chorus",
    "beat_strength": 0.45
  },
  "left_panel": {
    "mode": "intensity_glow",
    "brightness": 0.72,
    "color_hue": 240,
    "energy": 0.78,
    "volume": 0.85
  },
  "right_panel": {
    "mode": "beat_pulse",
    "brightness": 0.55,
    "color_hue": 200,
    "bpm_visual": 112.0,
    "pulse_active": false
  }
}
```

#### 一次性事件（led_command）— 事件触发

```json
{
  "message_type": "led_command",
  "event_id": 1802,
  "priority": 80,
  "target": "both",
  "effect": {
    "name": "accent_flash",
    "color": "#FFFFFF",
    "brightness": 1.0,
    "duration_ms": 120,
    "decay": "exponential"
  }
}
```

**优先级（高→低）**：
```
100 — emergency_stop (不可打断)
 80 — accent_flash, instant_black
 60 — downbeat_pulse
 40 — palette_sweep, style_change
 20 — intensity_glow, tempo_meter, breathing
  0 — idle, off
```

### 4.5 各手势对应的灯效详情

#### Downbeat

```
右手灯带: beat_pulse — 全屏白色闪光，strength 控制峰值亮度，120ms 指数衰减
左手灯带: beat_pulse — 同闪，但亮度 = strength × 0.6（弱于右手）
效果: 指挥者双手同时闪白，右手更亮，视觉上强调"右手指挥节拍"
```

#### Crescendo（渐强）

```
左手灯带: intensity_glow
  - 亮度: 20% → 100%（跟随 target_volume）
  - 色相: 240°(蓝) → 0°(红)（跟随 energy）
  - 过渡: 0.3s 线性插值
  - 效果: "越响越亮越暖"
右手灯带: breathing + 亮度微升
  - 不闪烁，温和随动
```

#### Decrescendo（渐弱）

```
左手灯带: intensity_glow
  - 亮度: 100% → 20%（跟随 target_volume）
  - 色相: 0°(红) → 240°(蓝)
  - 过渡: 0.3s 线性插值
右手灯带: breathing + 亮度微降
```

#### Cutoff（切断）

```
双手灯带: instant_black
  - 亮度: 当前 → 0%（50ms 内）
  - 保持全黑 500ms
  - 之后恢复 breathing（20% 亮度起）
效果: "一刀切"，视觉冲击力强
```

#### Style Switch（风格切换）

```
双手灯带: palette_sweep
  - 0-300ms: 色相从旧调色板过渡到新调色板
  - 同时播放一次 wave 动画（从左到右扫过）
  - 过渡后进入 breathing 模式（新色相）
调色板:
  warm_classical  → 琥珀金 #FFB347 + 暖白 #FFF5E6
  cool_electronic → 青蓝 #00CED1 + 品红 #FF00FF
  minimal_piano   → 暖白 #F5F5DC + 浅灰 #C0C0C0
  dramatic        → 红 #DC143C + 金 #FFD700 + 白闪
```

#### Tempo Up / Tempo Down

```
右手灯带: tempo_meter
  - LED 从左到右流水，流速 = BPM
  - 加速时流水加快，色相偏暖
  - 减速时流水减慢，色相偏冷
左手灯带: breathing（频率同步 BPM）
  - 亮度跟随 BPM 频率正弦变化
```

#### Idle（空闲）

```
双手灯带: breathing
  - 慢速正弦呼吸，周期 4s
  - 亮度 20% ↔ 40%
  - 色相: 柔蓝
```

### 4.6 LED 灯效增强版控制器设计

对现有 `controller.py` 的扩展建议：

```python
class LedController:  # 在现有基础上扩展
    """增强版：支持 PC 下行指令、多模式、左右手独立控制"""

    def __init__(self, ...):
        # 现有初始化...
        # 新增：模式状态
        self._left_mode = "breathing"
        self._right_mode = "breathing"
        self._left_params = {}
        self._right_params = {}
        # 新增：调色板
        self._palette = WARM_CLASSICAL_PALETTE
        # 新增：事件队列（优先级排序）
        self._event_queue: list[LedEvent] = []

    # ---- 新增：接收 PC 下行指令 ----

    def handle_pc_led_state(self, state: dict):
        """处理来自 PC 的 led_state 消息"""
        music = state.get("music_sync", {})
        left = state.get("left_panel", {})
        right = state.get("right_panel", {})

        self.set_state(
            bpm=music.get("bpm"),
            intensity=max(left.get("energy", 0.5), right.get("energy", 0.5)),
            left_weight=left.get("brightness", 0.5),
            right_weight=right.get("brightness", 0.5),
        )
        self._left_mode = left.get("mode", "breathing")
        self._right_mode = right.get("mode", "breathing")
        self._left_params = left
        self._right_params = right

    def handle_pc_led_command(self, command: dict):
        """处理来自 PC 的 led_command 一次性事件"""
        event = LedEvent(
            priority=command.get("priority", 50),
            target=command.get("target", "both"),
            effect=command.get("effect", {}),
            expires_at=time.monotonic() + command.get("effect", {}).get("duration_ms", 120) / 1000,
        )
        # 优先级队列：低优先级事件可被高优先级打断
        self._event_queue.append(event)
        self._event_queue.sort(key=lambda e: e.priority, reverse=True)

    # ---- 新灯效渲染函数 ----

    def _render_intensity_glow(self, panel: int, now: float):
        """力度辉光 — 亮度映射 volume，色相映射 energy"""
        params = self._left_params if panel == 0 else self._right_params
        volume = params.get("volume", 0.5)
        energy = params.get("energy", 0.5)
        hue = params.get("color_hue", 240)

        # energy → 色相偏移 (蓝240° → 红0°)
        hue_shifted = hue - energy * 240
        brightness = volume * self._brightness_limit

        for i in range(self._leds_per_panel(panel)):
            color = self._hsv_to_color(hue_shifted, 0.8, brightness)
            self._set_panel_led(panel, i, color)

    def _render_tempo_meter(self, panel: int, now: float):
        """节拍流速表 — LED 从左到右按 BPM 流水"""
        params = self._right_params if panel == 1 else self._left_params
        bpm = params.get("bpm_visual", 120.0)

        # BPM → 流动速度 (LED/s)
        flow_speed = bpm / 60.0 * self._leds_per_panel(panel) / 2
        offset = int((now * flow_speed) % self._leds_per_panel(panel))

        for i in range(self._leds_per_panel(panel)):
            dist = (i - offset) % self._leds_per_panel(panel)
            brightness = math.exp(-dist / 4) * self._brightness_limit
            self._set_panel_led(panel, i, (int(brightness), int(brightness*0.7), int(brightness*0.3)))

    def _render_accent_flash(self, panel: int, elapsed_ms: float):
        """强拍闪光 — 全白 + 指数衰减"""
        effect = self._active_event.effect
        duration = effect.get("duration_ms", 120)
        brightness = effect.get("brightness", 1.0) * max(0, 1 - elapsed_ms / duration)
        color_hex = effect.get("color", "#FFFFFF")
        r, g, b = self._hex_to_rgb(color_hex)
        for i in range(self._leds_per_panel(panel)):
            self._set_panel_led(panel, i, (int(r*brightness), int(g*brightness), int(b*brightness)))

    def _render_palette_sweep(self, panel: int, elapsed_ms: float):
        """调色板切换 — 色相过渡"""
        progress = min(1.0, elapsed_ms / 500)  # 500ms 过渡
        for i in range(self._leds_per_panel(panel)):
            old_color = self._palette_old[i % len(self._palette_old)]
            new_color = self._palette_new[i % len(self._palette_new)]
            blended = self._blend_color(old_color, new_color, progress)
            self._set_panel_led(panel, i, blended)

    # ---- 渲染主循环（修改 _update_animation） ----

    def _update_animation(self) -> None:
        """增强版渲染循环"""
        now = time.monotonic()

        # 1. 检查一次性事件（高优先级打断）
        active_event = self._get_active_event(now)
        if active_event:
            self._render_event(active_event, now)
        else:
            # 2. 分别渲染左右面板
            self._render_panel(0, self._left_mode, self._left_params, now)   # 左手
            self._render_panel(1, self._right_mode, self._right_params, now) # 右手

        self._strip.show()
```

---

## 5. PC 端处理管线 — AI 模型驱动

### 5.1 完整数据流

```
Pi → TCP :9000 → PC Backend
                      │
    ┌─────────────────┼─────────────────┐
    │                 │                 │
    ▼                 ▼                 ▼
fused_frame      control_event       status
    │                 │                 │
    ▼                 ▼                 ▼
live_state        live_state          live_state
    │                 │
    ▼                 ▼
┌──────────────────────────────┐
│  SlidingWindowAggregator    │  ← 累积 fused_frame → 800ms 窗口
│  窗口特征提取                │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  AI 模型推理（核心）          │
│  model_service.predict()     │
│  → GestureClassifier         │
│  → 手势标签 + 置信度          │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  IntentMapper               │
│  → 音乐控制参数              │
│  → LED 灯效参数              │
└──────┬───────────┬───────────┘
       │           │
       ▼           ▼
   OSC (SonicPi)  LED TCP 下行
```

### 5.2 核心模块：model/inference.py（待构建）

这是项目 AI 贡献的核心文件，实现 `GestureClassifier`：

```python
# model/inference.py — AI 手势分类模型

import pickle
import numpy as np
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

class GestureClassifier:
    """指挥手势分类器 — 基于 Random Forest 的多模态手势识别模型
    
    输入：滑动窗口特征向量（~300-500维）
    输出：手势标签 + 置信度 + 全概率分布
    """
    
    GESTURE_LABELS = [
        "idle",          # 0
        "downbeat",      # 1
        "crescendo",     # 2
        "decrescendo",   # 3
        "cutoff",        # 4
        "style_switch",  # 5
        "tempo_up",      # 6
        "tempo_down",    # 7
    ]
    
    def __init__(self, model_path: str | Path | None = None):
        if model_path and Path(model_path).exists():
            with open(model_path, 'rb') as f:
                bundle = pickle.load(f)
            self.model = bundle['model']
            self.scaler = bundle['scaler']
            self.feature_names = bundle['feature_names']
        else:
            self.model = None
            self.scaler = None
            self.feature_names = None
    
    def predict(self, window_data: dict) -> dict:
        """对滑动窗口数据进行手势分类
        
        Args:
            window_data: SlidingWindowComputer 输出的窗口特征字典
            
        Returns:
            符合 model_service.py 接口规范的预测结果
        """
        import time
        
        # Step 1: 从窗口数据提取特征向量
        features = self._extract_features(window_data)
        
        # Step 2: 标准化
        if self.scaler:
            features = self.scaler.transform([features])[0]
        
        # Step 3: 模型推理
        probs = self.model.predict_proba([features])[0]
        pred_class = int(np.argmax(probs))
        confidence = float(probs[pred_class])
        
        return {
            "gesture": self.GESTURE_LABELS[pred_class],
            "gesture_id": pred_class,
            "confidence": round(confidence, 4),
            "timestamp": time.time(),
            "features_used": self.feature_names or [],
            "all_probs": {
                label: round(float(p), 4)
                for label, p in zip(self.GESTURE_LABELS, probs)
            },
        }
    
    def _extract_features(self, window_data: dict) -> np.ndarray:
        """从窗口数据提取模型输入特征向量
        
        将 window_features 中的结构化字典展平为一维数值向量。
        """
        feature_vec = []
        
        # === 摄像头特征（per-hand）===
        camera = window_data.get("camera_features", {})
        for hand in ["left_hand", "right_hand"]:
            hf = camera.get(hand, {})
            feature_vec.extend([
                hf.get("trajectory_length", 0),
                hf.get("displacement", 0),
                hf.get("wrist_speed_mean", 0),
                hf.get("wrist_speed_std", 0),
                hf.get("wrist_speed_max", 0),
                hf.get("direction_changes", 0),
                hf.get("openness_mean", 0.5),
                hf.get("openness_range", 0),
            ])
        
        # 双手协调特征
        cm = window_data.get("cross_modal_features", {})
        feature_vec.extend([
            cm.get("hand_distance_mean", 0),
            cm.get("hand_distance_range", 0),
            cm.get("motion_intensity", 0),
        ])
        
        # === ESP32 特征（per-device）===
        mb = window_data.get("microbit_features", {})
        for dev in ["left_hand", "right_hand"]:
            mf = mb.get(dev, {})
            feature_vec.extend([
                mf.get("acc_magnitude_mean", 0),
                mf.get("acc_magnitude_std", 0),
                mf.get("max_jerk_g_s", 0),
                mf.get("jerk_peak_count", 0),
                mf.get("pitch_mean", 0),
                mf.get("pitch_range", 0),
                mf.get("roll_mean", 0),
                mf.get("roll_range", 0),
            ])
        
        # BPM 相关
        feature_vec.extend([
            cm.get("estimated_bpm", 120),
            cm.get("bpm_variability", 0),
            cm.get("motion_intensity", 0),
        ])
        
        return np.array(feature_vec, dtype=np.float32)
    
    @classmethod
    def train(cls, X: np.ndarray, y: np.ndarray, feature_names: list[str]) -> "GestureClassifier":
        """训练模型（离线使用，在 Jupyter Notebook 中调用）
        
        Args:
            X: 训练数据 (n_samples, n_features)
            y: 标签 (n_samples,) — 0-7 对应 GESTURE_LABELS
            feature_names: 特征名列表
            
        Returns:
            训练好的 GestureClassifier 实例
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler
        
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=15,
            min_samples_leaf=5,
            class_weight='balanced',
            random_state=42,
        )
        model.fit(X_scaled, y)
        
        instance = cls()
        instance.model = model
        instance.scaler = scaler
        instance.feature_names = feature_names
        
        return instance
    
    def save(self, path: str | Path) -> None:
        """保存模型到文件"""
        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'scaler': self.scaler,
                'feature_names': self.feature_names,
            }, f)
```

### 5.3 模型训练数据采集

模型需要标注数据。利用现有系统采集训练数据的流程：

```
1. 启动系统（Pi + PC 后端开启录制模式）
2. 指挥者按标签顺序各做 10-15 秒指定手势
3. 系统录制 fused_frame → 滑动窗口 → 特征向量 + 标签
4. 导出为 CSV/JSON 训练数据集
5. 在 Jupyter Notebook 中训练 + 评估 + 调参
6. 导出 .pkl 模型文件到 model/models/gesture_classifier.pkl
```

**数据采集计划**：

| 手势 | 每人采集时长 | 窗口样本数（800ms窗口/100ms步长） |
|------|:----------:|:-------------------------------:|
| idle | 15s × 3次 | ~400 |
| downbeat | 15s × 5次 | ~700 |
| crescendo | 15s × 3次 | ~400 |
| decrescendo | 15s × 3次 | ~400 |
| cutoff | 每个5s × 10次 | ~400 |
| style_switch | 每个5s × 10次 | ~400 |
| tempo_up | 15s × 3次 | ~400 |
| tempo_down | 15s × 3次 | ~400 |
| **合计** | **~30 分钟/人** | **~3500 个窗口样本** |

### 5.4 新增：IntentMapper（AI 输出 → 音乐+LED 双信号）

```python
class IntentMapper:
    """将 AI 模型的输出映射为音乐和 LED 控制信号"""
    
    def __init__(self, sonic_pi_adapter, led_engine):
        self.osc = sonic_pi_adapter
        self.led = led_engine
        self.music_state = MusicControlState()
    
    def process_ai_prediction(self, prediction: dict, window_features: dict):
        """处理 AI 模型的单次预测"""
        gesture = prediction["gesture"]
        confidence = prediction["confidence"]
        
        # 置信度过低 → 忽略
        if confidence < 0.6:
            return
        
        # === 离散手势 → 音乐 + LED ===
        if gesture == "downbeat":
            self.osc.send_accent(confidence, "downbeat")
            self.led.on_gesture("downbeat", {"strength": confidence})
        
        elif gesture == "cutoff":
            self.music_state.playing = False
            self.osc.send_transport("cutoff")
            self.led.on_gesture("cutoff", {})
        
        elif gesture == "style_switch":
            # 循环切换风格
            styles = ["warm_classical", "cool_electronic", "minimal_piano", "dramatic"]
            current_idx = styles.index(self.music_state.style)
            next_style = styles[(current_idx + 1) % len(styles)]
            self.music_state.style = next_style
            self.osc.send_state_from_music(self.music_state.to_dict())
            self.led.on_gesture("style_switch", {"style": next_style})
        
        # === 连续参数 → 音乐 + LED ===
        # BPM（来自特征工程，非 AI 分类）
        bpm = self._estimate_bpm(window_features)
        if abs(bpm - self.music_state.bpm) > 2:
            self.music_state.bpm = bpm
            self.osc.send_bpm(bpm)
        
        # 音量/能量（来自特征工程）
        volume, energy = self._estimate_intensity(window_features)
        self.music_state.apply_volume(volume)
        self.music_state.energy = energy
        
        # 周期性发送连续状态
        if self._should_send_state():
            self.osc.send_state_from_music(self.music_state.to_dict())
            self.led.on_music_state_change(self.music_state.to_dict())
```

### 5.5 训练流程（离线）

```
┌─────────────────────────────────────────────────────────┐
│  训练 Notebook（model/train_gesture_classifier.ipynb）  │
│                                                          │
│  1. 加载训练数据（JSONL/CSV）                             │
│  2. 探索性数据分析（特征分布、类别平衡）                   │
│  3. 特征选择（互信息、特征重要性）                        │
│  4. 训练/验证集分割（按人分割，避免数据泄露）             │
│  5. 模型训练（RandomForest / XGBoost）                   │
│  6. 超参数调优（GridSearchCV）                            │
│  7. 评估（混淆矩阵、F1、per-class precision/recall）     │
│  8. 特征重要性分析 + 可视化                               │
│  9. 导出 model/models/gesture_classifier.pkl             │
└─────────────────────────────────────────────────────────┘
```

---

## 6. 实现路线图（AI 优先）

### 阶段一：AI 模型 MVP（3-5 天）
**目标**：完成手势分类模型的训练和部署闭环

```
□ 编写 model/inference.py — GestureClassifier 类
  ├── _extract_features() — 从 window_features 提取特征向量
  ├── predict() — 模型推理接口
  ├── train() — 离线训练方法
  └── save() / load() — 模型持久化
□ 编写数据录制脚本
  ├── POST /api/recording/start?label=downbeat
  ├── 系统自动录制 fused_frame → 窗口特征
  └── POST /api/recording/stop → 写入 JSONL 文件
□ 采集初始训练数据（每人每种手势 10-15s）
□ 编写 model/train_gesture_classifier.ipynb
  ├── 加载数据 → 特征提取 → 标准化
  ├── RandomForest 训练 + GridSearchCV
  └── 评估（混淆矩阵、F1-score）
□ 导出 model/models/gesture_classifier.pkl
□ 集成到 backend/model_service.py（已预留接口）
```

**验收标准**：
- 模型正确加载到 backend，`model_service.predict()` 返回合法结果
- 至少 4 种手势（idle/downbeat/crescendo/cutoff）F1 > 0.75

### 阶段二：AI → 双信号闭环（2-3 天）
**目标**：AI 模型输出驱动音乐和灯光

```
□ 实现 IntentMapper（AI 输出 → OSC + LED 指令）
□ 集成到 message_router.py 的 control_event 处理链路
□ 树莓派 LED 控制器扩展：接收 PC TCP 下行 led_state/led_command
□ 端到端测试：手势 → AI 识别 → OSC 音乐 + LED 灯效
```

**验收标准**：
- Downbeat → 闪光 + 重音（延迟 < 150ms）
- Cutoff → 黑屏 + 静音
- Crescendo → 左手灯带渐变 + 音量渐变

### 阶段三：灯效增强（2-3 天）
**目标**：完善左右手分区灯效，实现视觉冲击力

```
□ 左手 intensity_glow 模式（蓝→红渐变 + 亮度爬升）
□ 右手 tempo_meter 模式（BPM 流速表）
□ palette_sweep 风格切换动画
□ 事件优先级队列（flash > glow > breathing）
□ 4 种风格调色板实现
```

**验收标准**：
- 左右手灯带独立显示不同模式
- 风格切换时色相平滑过渡
- 高优先级事件正确打断低优先级

### 阶段四：模型迭代与性能优化（3-5 天）
**目标**：提升模型准确率，优化端到端延迟

```
□ 扩充训练数据（多人、多种光照/角度）
□ 特征工程优化（基于特征重要性分析）
□ 尝试 XGBoost / LightGBM（对比 RandomForest）
□ 数据增强（时间扭曲、噪声注入）
□ 模型压缩（减少特征维度、剪枝）
□ 端到端延迟优化（目标：AI 推理 < 30ms）
```

**验收标准**：
- 6-8 种手势 F1 > 0.85
- 端到端延迟（手势→音乐）< 100ms
- 模型文件 < 5MB

---

## 7. 技术风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 灯光延迟过大（Pi→PC→Pi 来回） | LED 与音乐不同步 | led_state 以 10Hz 高频发送；beat flash 可设 offset 补偿 |
| 手势误识别（非指挥动作触发） | 音乐混乱 | 冷却时间 + 置信度阈值 + 连续 N 帧确认 |
| 左右手数据混淆 | 方向性灯效错误 | ESP32 绑定 hand 字段 + 摄像头 handedness 确认 |
| 灯光太亮刺眼 | 用户体验差 | 全局亮度上限 25%（硬件限制）+ 可远程调整 |
| Sonic Pi 未启动 | 无音乐输出 | 后端检测 Sonic Pi 在线状态，降级到仅 LED 模式 |
| WiFi 断连导致数据缺失 | 手势检测中断 | 摄像头独立检测（降级方案）+ 自动重连 |

---

## 8. 决策记录与待办

### 8.1 已确认决策

| # | 决策 | 结论 |
|---|------|------|
| 音乐输出 | Sonic Pi OSC（PC 本地） | 沿用现有架构，不经树莓派转发 |
| LED 连接 | 树莓派 GPIO18 有线直驱 | 2 块 8×32 WS2812B，路演固定位置 |
| 手势识别 | AI 模型（核心）+ 规则辅助 | MediaPipe(AI1) + GestureClassifier(AI2) + 规则仅做安全事件 |
| 左右手分工 | 右手→节拍 / 左手→力度 | 灯带分区对应，协议已体现 |
| Style Switch | 触发一次循环切换一个风格 | warm_classical → cool_electronic → minimal_piano → dramatic → 循环 |
| PC→Pi 协议 | 只发 gesture_code 代号 | Pi 本地查表执行，params 仅带 bpm/energy/volume 用于灯效微调 |

### 8.2 后续待确认

| # | 问题 | 备注 |
|---|------|------|
| 是否需要物理蜂鸣器 | 当前 Sonic Pi 可满足音乐需求，物理蜂鸣器可作为节拍提示音 | 可选扩展 |
| LED 灯效是否需要前端配置 | 当前设计为预设固定，可根据需求加入前端配置面板 | 阶段四可做 |
| 训练数据采集时间 | 需要协调团队成员的采集时间和动作标准 | 阶段一需要 |
