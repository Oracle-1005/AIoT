# 手势指挥系统 — 各模块任务分解

> **版本**: v1.0 | **日期**: 2026-07-22
> **参考**: `docs/GESTURE_CONDUCTOR_DESIGN.md`

---

## 模块总览

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  前端     │    │  后端     │    │  AI模型  │    │  硬件     │
│ (王玺达)  │    │ (罗子超)  │    │ (王祎哲)  │    │ (王清源   │
│           │    │           │    │           │    │  王俊智)  │
│ Dashboard │◄───│ Flask API │◄───│ Gesture   │◄───│ Pi 5     │
│ 可视化    │    │ TCP网关   │    │ Classifier│    │ ESP32    │
│           │    │ OSC适配   │    │           │    │ LED灯带  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
```

**接口边界**（各模块之间的约定）：

| 边界 | 方向 | 协议 | 数据格式 |
|------|------|------|---------|
| 前端 ↔ 后端 | 双向 | REST API + WebSocket | JSON |
| 后端 ↔ AI 模型 | 同进程调用 | `model_service.predict()` | Python dict |
| 后端 → Sonic Pi | 单向 | OSC over UDP | OSC path + args |
| 后端 ↔ 树莓派 | 双向 | TCP :9000 | JSON Lines |
| 树莓派 ↔ ESP32 | 双向 | Wi-Fi TCP :9001 | JSON Lines |
| 树莓派 → LED 灯带 | 单向 | GPIO18 | rpi_ws281x |

---

## 一、AI 模型（王祎哲）

### 1.1 总体目标

构建手势分类 AI 模型，接收滑动窗口特征向量，输出手势标签 + 置信度。

### 1.2 具体任务

| # | 任务 | 产出 | 优先级 |
|---|------|------|:------:|
| 1 | **编写 `model/inference.py`** — `GestureClassifier` 类 | 可运行的模型骨架代码 | P0 |
| 2 | **设计特征向量** — 确定从 `window_features` 提取哪些特征 | 特征名列表，~30-50 维 | P0 |
| 3 | **编写数据录制脚本** — 利用现有系统录制标注数据 | 训练数据集 (JSONL/CSV) | P0 |
| 4 | **采集训练数据** — 每种手势 50+ 样本 | 标注数据文件 | P1 |
| 5 | **编写训练 Notebook** — `model/train_gesture_classifier.ipynb` | Notebook，含评估指标 | P1 |
| 6 | **训练 + 导出模型** — Random Forest / XGBoost | `model/models/gesture_classifier.pkl` | P1 |
| 7 | **模型迭代** — 扩充数据、调参、尝试其他算法 | 更高准确率的模型版本 | P2 |

### 1.3 接口约定

**输入**（来自后端的滑动窗口数据）：
```python
window_data = {
    "camera_features": {
        "left_hand":  { "trajectory_length": ..., "wrist_speed_mean": ..., "openness_mean": ..., ... },
        "right_hand": { ... }
    },
    "microbit_features": {   # ESP32 IMU 特征（Pi 端 window.py 生成）
        "left_hand":  { "acc_magnitude_mean": ..., "max_jerk_g_s": ..., ... },
        "right_hand": { ... }
    },
    "cross_modal_features": {
        "estimated_bpm": ..., "motion_intensity": ..., ...
    }
}
```

**输出**（给后端 `model_service.py`）：
```python
{
    "gesture": "downbeat",       # 8 种手势标签之一
    "gesture_id": 1,             # 对应 gesture_code
    "confidence": 0.92,          # [0, 1]
    "timestamp": 1721052000.500,
    "features_used": ["right_wrist_vy_std", ...],
    "all_probs": {               # 所有手势的概率
        "idle": 0.01, "downbeat": 0.92, "crescendo": 0.02,
        "decrescendo": 0.01, "cutoff": 0.01, "style_switch": 0.01,
        "tempo_up": 0.01, "tempo_down": 0.01
    }
}
```

### 1.4 与后端的集成方式

```python
# backend/model_service.py（已有，无需改动）
from model.inference import GestureClassifier

classifier = GestureClassifier(model_path="model/models/gesture_classifier.pkl")
result = classifier.predict(window_data)
# result 直接返回给 message_router 使用
```

### 1.5 初始阶段替代方案

模型未训练好时，可先用规则模拟输出：
```python
# 临时规则：置信度 0.5 + 随机标签，保证链路可调通
```

---

## 二、后端（罗子超）

### 2.1 总体目标

PC 端控制中心：接收树莓派上行数据、调用 AI 模型、分发双信号（OSC→Sonic Pi、TCP→树莓派）。

### 2.2 具体任务

| # | 任务 | 产出 | 优先级 |
|---|------|------|:------:|
| 1 | **扩展 `database.py`** — 新增 `gesture_code_mappings` 表 + 查询方法 | DB 建表 + `get_gesture_mapping(code)` | P0 |
| 2 | **新增 `gesture_dispatcher.py`** — GestureDispatcher 类 | 代号→双信号分发逻辑 | P0 |
| 3 | **扩展 TCP 下行** — PC→Pi 发送 `gesture_command` 消息 | 双向 TCP 通信 | P0 |
| 4 | **更新 `message_router.py`** — 集成 AI 模型调用 + GestureDispatcher | 完整的 control_event 处理链路 | P0 |
| 5 | **更新 `sonic_pi.py`** — 确保风格切换等新 OSC 命令正确发送 | 现有接口验证 + 补充 | P1 |
| 6 | **新增录制接口** — `POST /api/recording/start|stop|mark` | 训练数据采集 API | P1 |
| 7 | **数据库预置数据** — 插入 gesture_code 0-10 的映射记录 | 系统启动时可用的映射表 | P0 |

### 2.3 核心代码：GestureDispatcher

新文件 `backend/gesture_dispatcher.py`，核心逻辑：

```
收到 AI 模型的预测结果
  │
  ├── gesture_label → gesture_code（查数据库）
  │
  ├── 信号 1: 构造 gesture_command JSON → TCP 发送给树莓派
  │     {"message_type":"gesture_command","gesture_code":1,"params":{...}}
  │
  └── 信号 2: 根据 music_action 发送 OSC 给 Sonic Pi
        trigger_beat  → /conductor/accent
        adjust_volume → /conductor/state
        adjust_tempo  → /conductor/bpm
        stop_or_mute  → /conductor/transport cutoff
        change_style  → /conductor/state（含风格参数，循环切换）
```

### 2.4 数据库新增

```sql
CREATE TABLE IF NOT EXISTS gesture_code_mappings (
    gesture_code    INTEGER PRIMARY KEY,
    gesture_name    TEXT    NOT NULL,
    music_action    TEXT,
    bpm_delta       REAL    DEFAULT 0,
    volume_delta    REAL    DEFAULT 0,
    volume_target   REAL,
    energy_target   REAL,
    style_name      TEXT,
    led_effect      TEXT    NOT NULL,
    led_priority    INTEGER DEFAULT 0
);
```

预置 11 条记录（gesture_code 0-10），详见设计文档 §3.2。

### 2.5 数据流整合

在 `message_router.py` 的 `control_event` 处理分支中：

```python
# 当前逻辑（保留）
live_state.apply_control_event(payload, received_at)
sonic_pi_adapter.publish_control_event(payload, live_state.get_music())

# 新增逻辑
if payload.get("event", {}).get("type"):
    gesture_label = payload["event"]["type"]
    confidence = payload["event"].get("confidence", 0.8)
    gesture_dispatcher.dispatch(gesture_label, confidence, live_state.get_music())
```

### 2.6 与各模块对接清单

| 对接方 | 接口 | 说明 |
|--------|------|------|
| AI 模型 | `model_service.predict(window_data)` | 同进程调用 |
| 树莓派 | TCP :9000 双向 JSON Lines | 已有机础，扩展下行 |
| Sonic Pi | OSC UDP :4560 | 已有完整实现 |
| 前端 | REST API + WebSocket | 已有，保持现有接口 |

---

## 三、前端（王玺达）

### 3.1 总体目标

Dashboard 实时展示指挥状态：当前手势、置信度、BPM、音量、灯效模式、设备连接状态。提供录制控制和手动音乐控制面板。

### 3.2 具体任务

| # | 任务 | 产出 | 优先级 |
|---|------|------|:------:|
| 1 | **手势展示区域** — 当前识别的手势名 + 置信度 | 大号手势图标 + 概率条 | P0 |
| 2 | **音乐状态面板** — BPM、音量、能量、风格、播放/暂停 | 实时更新的参数卡片 | P0 |
| 3 | **LED 状态同步** — 左右手灯带当前模式和颜色 | 两个 LED 模拟器（8×32 像素预览） | P1 |
| 4 | **设备状态面板** — ESP32×2、摄像头、树莓派、Sonic Pi 在线状态 | 连接状态指示灯（绿/黄/红） | P1 |
| 5 | **录制控制** — 开始录制、选择标签、停止录制 | 按钮 + 下拉选择手势标签 | P1 |
| 6 | **手动音乐控制** — 播放/暂停/风格切换/BPM 滑块 | 调试面板（仅开发模式） | P2 |
| 7 | **数据回放** — 加载历史数据、回放手势序列 | 时间线 + 手势动画 | P2 |

### 3.3 需调用的后端 API

**已有接口**（当前可用）：
| 方法与路径 | 作用 |
|-----------|------|
| `GET /api/status` | 系统总体状态 |
| `GET /api/gesture/current` | 当前识别手势 |
| `GET /api/gesture/history` | 手势历史记录 |
| `GET /api/sensors/live` | 传感器实时数据 |
| `GET /api/music/state` | 当前音乐参数 |

**新增接口**（需后端实现）：
| 方法与路径 | 作用 |
|-----------|------|
| `POST /api/recording/start` | 开始录制，body: `{"label":"downbeat"}` |
| `POST /api/recording/stop` | 停止录制 |
| `GET /api/gesture/mappings` | 获取手势→音乐+LED 映射表 |

### 3.4 手势展示设计参考

```
┌─────────────────────────────────┐
│         当前手势                 │
│                                 │
│         🎵 DOWNBEAT             │  大号手势名称
│        ━━━━━━━━━━━━━ 92%       │  置信度进度条
│                                 │
│  右手下拍  节拍锚点              │  描述
│                                 │
│  各手势概率:                     │
│  downbeat    ████████████ 92%   │
│  crescendo   ██ 2%              │
│  idle        █ 1%               │
│  ...                            │
└─────────────────────────────────┘
```

---

## 四、硬件（王清源 + 王俊智）

### 4.1 分工

| 人员 | 负责 |
|------|------|
| **王清源** | 树莓派 5：摄像头 + MediaPipe + 融合引擎 + LED 灯带 + ESP32 TCP 管理 |
| **王俊智** | ESP32 ×2：Wi-Fi 通信 + IMU 传感器 + NeoPixel 灯环 + 蜂鸣器 |

### 4.2 王清源 — 树莓派端任务

| # | 任务 | 产出 | 优先级 |
|---|------|------|:------:|
| 1 | **新增 `gesture_effects.py`** — GESTURE_EFFECT_MAP 映射表 | Pi 端 gesture_code→灯效查询 | P0 |
| 2 | **扩展 `tcp_client.py`** — 新增下行接收 loop + 回调 | PC→Pi 消息接收 | P0 |
| 3 | **新增 `esp32_manager.py`** — ESP32 TCP Server 管理器 | 上下行 JSON Lines 收发 | P0 |
| 4 | **扩展 `controller.py`** — 新增 `apply_gesture_effect()` + 新灯效 | 左右手独立模式 + 6 种新灯效 | P0 |
| 5 | **更新 `main.py`** — 串联下行回调 + ESP32 Manager + LED 灯效调度 | 完整的主循环集成 | P0 |
| 6 | **移除 BLE 相关代码** — 清理 `ble_manager.py`、`microbit.py` | 干净的 WiFi 架构 | P1 |
| 7 | **适配 `window.py`** — 确保 ESP32 IMU 数据正确流入滑动窗口 | IMU 特征在窗口层可用 | P1 |

#### 4.2.1 gesture_effects.py

```python
# hardware/raspberry_pi_iot/led/gesture_effects.py

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

GESTURE_EFFECT_MAP = {
    # code: {"left": 左手灯效, "right": 右手灯效, "priority": 优先级, "duration_ms"/"transition_ms"}
    0:  {"left": "breathing",      "right": "breathing",       "priority": 0,  "transition_ms": 500},
    1:  {"left": "accent_flash",   "right": "accent_flash",    "priority": 60, "duration_ms": 120},
    2:  {"left": "intensity_glow", "right": "breathing",       "priority": 20, "transition_ms": 300},
    3:  {"left": "intensity_glow", "right": "breathing",       "priority": 20, "transition_ms": 300},
    4:  {"left": "instant_black",  "right": "instant_black",   "priority": 80, "duration_ms": 500},
    5:  {"left": "palette_sweep",  "right": "palette_sweep",   "priority": 40, "transition_ms": 500},
    6:  {"left": "breathing",      "right": "tempo_meter",     "priority": 20, "transition_ms": 200},
    7:  {"left": "breathing",      "right": "tempo_meter",     "priority": 20, "transition_ms": 200},
    8:  {"left": "emergency_red",  "right": "emergency_red",   "priority": 100,"duration_ms": 0},
    9:  {"left": "breathing",      "right": "breathing",       "priority": 10, "transition_ms": 500},
    10: {"left": "breathing",      "right": "breathing",       "priority": 10, "transition_ms": 500},
}
```

#### 4.2.2 LedController 新增灯效模式

| 模式 | 面板 | 描述 |
|------|:---:|------|
| `breathing` | 双手 | 已有 — 慢速正弦呼吸 |
| `accent_flash` | 双手 | **新增** — 全白闪光 + 指数衰减 |
| `intensity_glow` | 左手 | **新增** — 色相蓝→红 + 亮度映射 volume |
| `tempo_meter` | 右手 | **新增** — LED 按 BPM 频率流水 |
| `instant_black` | 双手 | **新增** — 瞬间全黑 |
| `palette_sweep` | 双手 | **新增** — 调色板过渡动画 |
| `emergency_red` | 双手 | **新增** — 红色快闪 |
| `wave` | 双手 | 已有 — 高斯波横扫 |

#### 4.2.3 esp32_manager.py

```
树莓派启动 TCP Server :9001
  │
  ├── 等待 ESP32_L 连接 → 记录 writer
  ├── 等待 ESP32_R 连接 → 记录 writer
  │
  ├── 上行: 读取 IMU 数据 → 注入融合引擎（替代原 BLE microbit 数据路径）
  │
  └── 下行: 收到 PC gesture_code → 查 GESTURE_ESP32_MAP → 
      向对应 ESP32 发送 {"type":"led","pattern":"FLASH","brightness":100}
```

#### 4.2.4 main.py 新增的串联逻辑

```python
# 在 start() 中新增
self._esp32_manager = Esp32Manager(host="0.0.0.0", port=9001)
await self._esp32_manager.start()

# 设置 TCP 下行回调
self._tcp_client.set_downlink_callback(self._handle_pc_downlink)

# 设置 ESP32 IMU 数据回调
self._esp32_manager.set_imu_callback(self._on_esp32_imu)

def _handle_pc_downlink(self, msg: dict):
    if msg.get("message_type") == "gesture_command":
        code = msg["gesture_code"]
        # 1. 驱动 LED 灯带
        effect = GESTURE_EFFECT_MAP.get(GestureCode(code))
        if effect and self._led_controller:
            self._led_controller.apply_gesture_effect(code, msg.get("params", {}))
        # 2. 转发给 ESP32
        asyncio.create_task(self._esp32_manager.dispatch_gesture(code))
```

### 4.3 王俊智 — ESP32 端任务

| # | 任务 | 产出 | 优先级 |
|---|------|------|:------:|
| 1 | **Wi-Fi 连接 + TCP Client** — 连接树莓派 :9001 | 稳定的长连接 | P0 |
| 2 | **IMU 数据采集** — 加速度计 + 陀螺仪，50Hz | JSON Lines 上行 | P0 |
| 3 | **指令解析执行** — 接收 JSON → 控制 NeoPixel + 蜂鸣器 | LED 图案 + 蜂鸣器发声 | P0 |
| 4 | **按键检测** — GPIO 按键（开始/暂停/紧急停止） | 按键事件通过 TCP 上行 | P1 |
| 5 | **固件烧录文档** — ESP32 烧录步骤和引脚接线图 | 其他人可复现 | P1 |

#### 4.3.1 ESP32 固件逻辑

```
启动
  │
  ├── 连接 Wi-Fi（SSID + 密码硬编码或通过 Web 配网）
  ├── 初始化 IMU（MPU6050 / MPU9250）
  ├── 初始化 NeoPixel（8-16 灯珠，GPIO 引脚待定）
  ├── 初始化蜂鸣器（PWM 引脚待定）
  ├── 初始化按键（GPIO 引脚待定）
  │
  ├── TCP Client 连接树莓派 :9001
  │
  ├── 主循环（50Hz）:
  │     ├── 读取 IMU → 构建 JSON → TCP 上行
  │     │   {"type":"imu","ax":...,"ay":...,"az":...,"gx":...,"gy":...,"gz":...,"ts":...}
  │     │
  │     └── 检查按键:
  │           短按 → {"type":"button","action":"short_press"}
  │           长按 → {"type":"button","action":"long_press"}
  │
  └── TCP 接收回调:
        解析 JSON → 
          type=="led"  → NeoPixel 执行 pattern
          type=="beep" → 蜂鸣器 PWM
          type=="stop" → 关闭 NeoPixel + 蜂鸣器
```

#### 4.3.2 数据格式

**上行（ESP32 → Pi）— IMU 数据**：
```json
{"type":"imu","ax_mg":120,"ay_mg":-340,"az_mg":980,"gx_dps":1.2,"gy_dps":-0.3,"gz_dps":0.1,"ts_ms":12345}
```

**上行（ESP32 → Pi）— 按键事件**：
```json
{"type":"button","action":"short_press","hand":"right","ts_ms":12345}
```

**下行（Pi → ESP32）— LED 指令**：
```json
{"type":"led","pattern":"FLASH","brightness":100}
```

**下行（Pi → ESP32）— 蜂鸣器指令**：
```json
{"type":"beep","freq_hz":800,"duration_ms":50}
```

### 4.4 硬件接线图（参考）

```
树莓派 5:
  GPIO18 ──── 74AHCT125 电平转换 ──── WS2812B 灯带 (左手, 256 LEDs)
                                   └── WS2812B 灯带 (右手, 256 LEDs)
  5V PWR ──── 灯带供电 (每个灯带最大 2A，限制亮度 25%)
  GND   ──── 灯带 GND
  Wi-Fi ──── ESP32 (左手) :9001
       └──── ESP32 (右手) :9001

ESP32 (×2):
  GPIO? ──── NeoPixel 灯环 (8-16 LEDs, 5V)
  GPIO? ──── 蜂鸣器 (PWM)
  GPIO? ──── 按键 (GND─按键─GPIO, 内置上拉)
  I2C   ──── MPU6050/MPU9250 IMU
```

---

## 五、依赖关系与开发顺序

```
阶段一（无依赖，可并行）:
  ├── AI 模型: 编写 inference.py 骨架 + 特征提取
  ├── 后端: gesture_code_mappings 表 + GestureDispatcher
  ├── 硬件(清源): gesture_effects.py + TCP 下行接收
  └── 硬件(俊智): ESP32 固件（Wi-Fi + IMU + NeoPixel + 蜂鸣器）

阶段二（依赖阶段一）:
  ├── AI 模型: 采集数据 + 训练 + 导出 .pkl
  ├── 后端: 集成 AI 模型 + 串联完整双信号链路
  ├── 硬件(清源): esp32_manager.py + LedController 新灯效
  └── 前端: 手势展示 + 音乐状态面板

阶段三（依赖阶段二）:
  ├── 全链路联调
  └── 前端: LED 状态 + 录制控制 + 手动控制

阶段四（优化）:
  ├── AI 模型: 数据扩充 + 模型迭代
  ├── 前端: 数据回放
  └── 整体: 延迟优化 + 路演脚本排练
```

---

## 六、各模块需要的文件清单

### AI 模型
```
model/
├── inference.py                    # 新建: GestureClassifier
├── train_gesture_classifier.ipynb  # 新建: 训练 Notebook
└── models/
    └── gesture_classifier.pkl      # 生成: 训练好的模型
```

### 后端
```
backend/
├── database.py          # 修改: 新增 gesture_code_mappings 表
├── gesture_dispatcher.py # 新建: GestureDispatcher
├── pi_gateway.py        # 修改: 扩展 TCP 下行
├── message_router.py    # 修改: 集成 AI + Dispatcher
└── sonic_pi.py          # 验证: 已有功能是否完备
```

### 前端
```
frontend/src/
├── components/
│   ├── GesturePanel.jsx      # 新建: 当前手势展示
│   ├── MusicStatePanel.jsx   # 新建: 音乐参数面板
│   ├── LedPreview.jsx        # 新建: LED 灯带模拟
│   ├── DeviceStatus.jsx      # 新建: 设备连接状态
│   └── RecordingPanel.jsx    # 新建: 录制控制
└── hooks/
    └── useConductorFeed.js   # 修改: 对接新增 API
```

### 硬件（树莓派）
```
hardware/
├── main.py                              # 修改: 串联下行 + ESP32 + LED
├── pi_pc/
│   ├── tcp_client.py                    # 修改: 新增下行接收
│   └── esp32_manager.py                 # 新建: ESP32 TCP Server
├── raspberry_pi_iot/
│   └── led/
│       ├── controller.py                # 修改: 新增灯效模式
│       └── gesture_effects.py           # 新建: GESTURE_EFFECT_MAP
└── ble/                                 # 可移除或保留（不再使用）
```

### 硬件（ESP32）
```
esp32_firmware/
├── main.cpp / main.py                   # 新建: ESP32 固件
├── wifi_config.h                        # 新建: Wi-Fi 配置
├── imu_driver.cpp                       # 新建: IMU 驱动
└── README.md                            # 新建: 烧录说明 + 接线图
```

---

## 七、Sonic Pi 音乐联动技术路线

### 7.1 总览

每个手势通过 **PC 后端 → OSC → Sonic Pi Time State → live_loop** 这条链路影响音乐。下表按手势逐一说明 Sonic Pi 端的实现方法。

### 7.2 手势→Sonic Pi 实现路线表

| gesture_code | 手势 | OSC 命令 | Sonic Pi 接收端 | 参数传递方式 | 音乐效果实现机制 | 当前状态 |
|:---:|------|---------|----------------|-------------|----------------|:---:|
| **0** | Idle | 不发送 | — | — | 保持所有 `current_*` 值不变，音乐持续播放。`live_loop :parameter_smoother` 维持最后的目标值 | ✅ 已有 |
| **1** | Downbeat | `/conductor/accent` | `live_loop :osc_accent_receiver` → `cue :manual_accent` | `strength` (0-1.2), `accent_type` (string) | `live_loop :manual_accent_player` 收到 cue 后播放镲片 (`:drum_cymbal_open`) + 低音鼓 (`:bd_haus`)，音量 = `strength × main_amp`。如果是 wrist_strike 类型额外叠加 `:tb303` 合成器低音 | ✅ 已有 |
| **2** | Crescendo | `/conductor/state` | `live_loop :osc_state_receiver` | `master_amp` ↑, `energy` ↑, `melody_amp` ↑ | 1) `set :target_master_amp` 等目标值升高；2) `live_loop :parameter_smoother` 每 0.25s EMA 逼近目标（`approach` 函数，系数 0.25）；3) 鼓/贝斯/和声/旋律四个 `live_loop` 每次发声前读取 `get(:master_amp)` 等当前值，音量自然渐强 | ✅ 已有 |
| **3** | Decrescendo | `/conductor/state` | `live_loop :osc_state_receiver` | `master_amp` ↓, `energy` ↓, `melody_amp` ↓ | 与 Crescendo 机制完全相同，目标值降低，EMA 平滑衰减。下限由 `clamp` 保护（master_amp 不低于 0） | ✅ 已有 |
| **4** | Cutoff | `/conductor/transport` | `live_loop :osc_transport_receiver` | `action="cutoff"` | `set :playing, false` → 所有音频 `live_loop` 的 `playable?` 检查返回 false → 立即停止发声。Sonic Pi 不产生新音符，但 Time State 保留，恢复时可继续 | ✅ 已有 |
| **5** | Style Switch | `/conductor/state`（扩展） | `live_loop :osc_state_receiver`（复用） | `style` 字段 + 对应效果参数 (`reverb_mix`, `cutoff`, `energy`) | **需新增**：1) 扩展 `osc_state_receiver` 解析 style 字段；2) 新增 `live_loop :style_switcher`，检测 style 变化时执行过渡；3) 各音频 `live_loop` 根据 style 切换合成器音色、鼓采样、效果链；4) 风格预设见 §7.3 | ❌ 待实现 |
| **6** | Tempo Up | `/conductor/bpm` | `live_loop :osc_bpm_receiver` | `bpm` (目标值, e.g. 120) | `set :target_bpm` 升高 → `live_loop :parameter_smoother` EMA 平滑 → `live_loop :beat_clock` 的 `use_bpm get(:current_bpm)` 感知变化 → 所有依赖 beat 的 `live_loop` 节奏加快。BPM 变化速度由 `approach` 系数 0.18 控制（约 1-2 秒达到目标） | ✅ 已有 |
| **7** | Tempo Down | `/conductor/bpm` | `live_loop :osc_bpm_receiver` | `bpm` (目标值, e.g. 80) | 同 Tempo Up，目标值降低。BPM 下限由 `clamp(bpm, 72, 148)` 保护 | ✅ 已有 |
| **8** | Emergency Stop | `/conductor/transport` | `live_loop :osc_transport_receiver` | `action="cutoff"` | 同 Cutoff，`set :playing, false`。区别在于 PC 端会额外触发 LED 红色快闪 + ESP32 蜂鸣器长鸣 | ✅ 已有 |
| **9** | Start | `/conductor/transport` | `live_loop :osc_transport_receiver` | `action="start"` | `set :playing, true` → `play_transport_start_now` 播放启动提示音（鼓点+E4 音符）→ 所有音频 `live_loop` 恢复发声 → 上报 `report_music_state` 通知 PC | ✅ 已有 |
| **10** | Pause | `/conductor/transport` | `live_loop :osc_transport_receiver` | `action="pause"` | `set :playing, false` → 所有音频 `live_loop` 停止发声，但保留 Time State（BPM、音量等不重置），与 Cutoff 行为相同 | ✅ 已有 |

### 7.3 Style Switch — Sonic Pi 实现细节（待实现）

这是唯一需要新增的核心功能。4 种风格对应不同的音色和效果配置：

| 风格 | 旋律合成器 | 和声合成器 | 贝斯合成器 | 鼓组风格 | reverb_mix | cutoff | energy |
|------|----------|----------|----------|---------|:---:|:---:|:---:|
| **warm_classical** | `:blade` | `:prophet` | `:fm` | 原声感（bd_haus + sn_dub） | 0.35 | 100 | 0.60 |
| **cool_electronic** | `:tb303` | `:supersaw` | `:subpulse` | 电子感（bd_tek + sn_zome） | 0.15 | 120 | 0.80 |
| **minimal_piano** | `:beep` | `:hollow` | `:sine` | 轻打击（drum_cymbal_closed only） | 0.50 | 80 | 0.40 |
| **dramatic** | `:prophet` | `:dark_ambience` | `:tb303` | 强打击（bd_boom + sn_dolf） | 0.70 | 130 | 0.95 |

**Sonic Pi 代码变更**（在现有 `ode_to_joy.rb` 基础上新增）：

```ruby
# 1. 新增 Time State 变量
set :current_style, :warm_classical
set :target_style, :warm_classical

# 2. 扩展 osc_state_receiver，解析 style 参数
# (在现有接收逻辑末尾加入)
live_loop :osc_state_receiver do
  use_real_time
  command_id, bpm, master_amp, drum_amp, drum_density,
    bass_amp, harmony_amp, melody_amp, energy,
    reverb_mix, cutoff = sync "/osc*/conductor/state"
  # ... 现有参数设置 ...
  # 新增：检测 style 变化
  new_style = get(:target_style)  # 由 PC 端额外发送
  if new_style != get(:current_style)
    cue :style_change, old: get(:current_style), new: new_style
  end
end

# 3. 新增风格切换过渡 loop
live_loop :style_transition do
  data = sync :style_change
  # 500ms 交叉淡入淡出过渡
  10.times do |i|
    set :style_blend, i / 10.0
    sleep 0.05
  end
  set :current_style, data[:new]
  set :style_blend, 1.0
end

# 4. 修改各音频 live_loop，根据 current_style 选择音色

# 以旋律为例：
live_loop :melody do
  use_bpm get(:current_bpm)
  note_value = melody_notes.tick(:melody)
  style = get(:current_style)
  
  if playable? && note_value
    # 根据风格选择合成器
    synth_name = case style
      when :warm_classical then :blade
      when :cool_electronic then :tb303
      when :minimal_piano then :beep
      when :dramatic then :prophet
    end
    
    use_synth synth_name
    # ... 播放逻辑 ...
  end
  sleep 0.5
end

# 鼓组同理：
live_loop :drums do
  data = sync :beat
  style = get(:current_style)
  
  if playable?
    # 根据风格选择鼓采样
    kick = case style
      when :warm_classical then :bd_haus
      when :cool_electronic then :bd_tek
      when :minimal_piano then :bd_haus
      when :dramatic then :bd_boom
    end
    sample kick, amp: ...
  end
end
```

### 7.4 PC → Sonic Pi 的完整 OSC 发送时序

以一次从 **Crescendo 切换到 Downbeat 再到 Cutoff** 的完整指挥过程为例：

```
t=0ms    指挥开始 Crescendo
t=35ms   AI 识别: crescendo, confidence=0.88
t=36ms   PC 计算: target_volume = current_volume + 0.05 = 0.85
t=36ms   PC → OSC: /conductor/state cmd-001 108 0.85 0.75 0.7 0.55 0.45 0.85 0.70 0.25 95
t=37ms   Sonic Pi: set :target_master_amp, 0.85; set :target_energy, 0.70
t=37ms   parameter_smoother: 开始逐帧平滑逼近
         (每 0.25s 步进一次，约 1-2s 达到目标 → 听感上自然渐强)

t=800ms  指挥右手下击 (Downbeat)
t=835ms  AI 识别: downbeat, confidence=0.91
t=836ms  PC → OSC: /conductor/accent cmd-002 0.91 right_downbeat
t=837ms  Sonic Pi: osc_accent_receiver → cue :manual_accent
t=837ms  manual_accent_player: 镲片 + 低音鼓 即时响 (零延迟)

t=1500ms 指挥双手合拢 (Cutoff)
t=1535ms AI 识别: cutoff, confidence=0.95
t=1536ms PC → OSC: /conductor/transport cmd-003 cutoff
t=1537ms Sonic Pi: set :playing, false → 所有音符立即停止

关键设计:
  - 连续参数 (crescendo/decrescendo/tempo): EMA 平滑，避免跳变
  - 离散事件 (downbeat/cutoff): cue 机制，零延迟即时响应
  - 风格切换: 交叉淡入淡出过渡，避免突兀
```

### 7.5 各手势的 Sonic Pi 代码修改量评估

| 手势 | 需要改动的 Sonic Pi 代码 | 工作量 |
|------|------------------------|:---:|
| Idle / Downbeat / Cutoff / Start / Pause / Emergency Stop | 无 | 0 |
| Crescendo / Decrescendo | 无（仅参数值变化） | 0 |
| Tempo Up / Tempo Down | 无（仅参数值变化） | 0 |
| **Style Switch** | 新增 1 个 `live_loop` + 修改 4 个音频 `live_loop`（鼓/贝斯/和声/旋律） | ~50 行代码 |

### 7.6 后端对接要点（罗子超）

`backend/sonic_pi.py` 当前已支持 `send_transport`、`send_bpm`、`send_accent`、`send_state_from_music`。Style Switch 对接方式：

```python
# 在 GestureDispatcher 中，style_switch 触发时:
def _handle_style_switch(self):
    global _current_style_index
    _current_style_index = (_current_style_index + 1) % len(STYLES)
    next_style = STYLES[_current_style_index]
    
    # 直接复用 send_state_from_music，带上 style 对应的参数
    preset = STYLE_PRESETS[next_style]
    self.sp.send_state_from_music(
        self.music_state,
        overrides={
            "style": next_style,         # Sonic Pi 端解析此字段
            "reverb_mix": preset["reverb_mix"],
            "cutoff": preset["cutoff"],
            "energy": preset["energy"],
        }
    )
```

无需新增 OSC 路径，直接在现有的 `/conductor/state` 消息中携带 style 参数即可。Sonic Pi 端在 `osc_state_receiver` 中检测 style 变化并触发过渡。
