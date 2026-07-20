# 后端接口适配修改指导文档

> **目的**：指导后端开发人员修改 PC 端代码，使其正确消费硬件（Pi 5）发送的 3 种消息类型。 **不在本文档中修改任何代码，仅说明要改什么、为什么改、怎么改。**

---

## 0. 当前接口事实

硬件（Pi 5）通过 TCP + JSON Lines 向 PC 发送 **3 种**消息类型（`window_features` 已取消）：

| 消息类型 | 频率 | 数据来源 |
|----------|------|----------|
| `fused_frame` | ~25 Hz | `FusionEngine._fuse()` → `MessageBuilder.build_fused_frame()` |
| `control_event` | 事件触发 | `_detect_event_from_window()` → `MessageBuilder.build_control_event()` |
| `status` | 1 Hz | `_build_status()` → `MessageBuilder.build_status()` |

硬件**不发送** `window_features`。PC 端不在线运行 Random Forest 手势分类模型。手势/事件检测由 Pi 端的 `_detect_event_from_window()`（基于 jerk 阈值 + 滑动窗口）完成，结果以 `control_event` 发给 PC。

---

## 1. 修改文件清单

| 文件 | 修改次数 | 说明 |
|------|:---:|------|
| `backend/state.py` | **4** | ① `apply_fused_frame` 遍历 microbits 数组 ② `apply_pi_status` 按嵌套结构取 microbit 状态 ③ `apply_control_event` 同步更新 music_state ④ 扩展 GESTURES 枚举 |
| `backend/message_router.py` | **1** | ⑤ 移除 `window_features` 相关逻辑（清理死代码，非强制） |

**共需修改 2 个文件，5 处改动。**

---

## 2. 修改详情

### 修改 ① — `state.py` 的 `apply_fused_frame`（第 81–102 行）

**现状问题**：
```python
# 当前代码：在 payload 中查找 microbit_left / left / left_hand 等顶级键
for destination, keys in (
    ("microbit_left", ("microbit_left", "left", "left_hand")),
    ("microbit_right", ("microbit_right", "right", "right_hand")),
):
    sample = next((payload.get(key) for key in keys
                   if isinstance(payload.get(key), dict)), None)
```

硬件实际发送的 payload 结构：
```json
{
  "camera": { "hands": [...], "frame_id": 4821, ... },
  "microbits": [
    {
      "device_id": "MB_LEFT",
      "hand": "left",
      "raw_interpolated": { "acceleration_mg": [84, 1164, -362], "pitch_deg": 18, "roll_deg": -7 },
      "instant_features": { "acceleration_magnitude_g": 1.221, ... },
      ...
    },
    {
      "device_id": "MB_RIGHT",
      "hand": "right",
      "raw_interpolated": { "acceleration_mg": [-102, 1388, -418], "pitch_deg": 21, "roll_deg": 6 },
      ...
    }
  ],
  "fusion": { "valid": true, ... }
}
```

数据在 `payload["microbits"]` **数组**里，不是 `payload["microbit_left"]` 这样的顶级键。

**修改方案**：用 `for` 循环遍历 `payload.get("microbits", [])` 数组，按 `hand` 字段分发到 `sensor_state["microbit_left"]` / `sensor_state["microbit_right"]`。

**修改后的伪代码**：
```python
def apply_fused_frame(self, payload: dict[str, Any], received_at: float) -> None:
    with self._lock:
        self.sensor_state["timestamp"] = received_at

        # ---- Camera ----
        camera = payload.get("camera")
        if isinstance(camera, dict):
            self.sensor_state["camera"] = copy.deepcopy(camera)
            self.camera_connected = True
            hands = camera.get("hands")
            if isinstance(hands, list):
                self.sensor_state["hand_count"] = len(hands)
                self.sensor_state["hand_detected"] = bool(hands)

        # ---- Micro:bits (遍历数组) ----
        for mb in payload.get("microbits", []):
            if not isinstance(mb, dict):
                continue
            hand = mb.get("hand", "")
            if hand == "left":
                self.sensor_state["microbit_left"] = copy.deepcopy(mb)
                self.microbit_left_connected = True
            elif hand == "right":
                self.sensor_state["microbit_right"] = copy.deepcopy(mb)
                self.microbit_right_connected = True
```

**核心改动**：删掉原来那套 `(destination, keys)` 元组遍历，改为直接遍历 `payload["microbits"]` 数组，用 `mb["hand"]` 做分支。

---

### 修改 ② — `state.py` 的 `apply_pi_status`（第 68–79 行）

**现状问题**：
```python
def apply_pi_status(self, payload: dict[str, Any]) -> None:
    with self._lock:
        self.pi_state["status"] = copy.deepcopy(payload)
        devices = payload.get("devices", payload)
        if isinstance(devices, dict):
            self.camera_connected = _online(devices.get("camera", self.camera_connected))
            self.microbit_left_connected = _online(
                devices.get("microbit_left", devices.get("left_microbit", self.microbit_left_connected))
            )
            self.microbit_right_connected = _online(
                devices.get("microbit_right", devices.get("right_microbit", self.microbit_right_connected))
            )
```

硬件实际发送的 payload 结构：
```json
{
  "camera":      { "connected": true, "actual_fps": 29.4, ... },
  "microbits": {
    "left":  { "device_id": "MB_LEFT",  "connected": true, "rssi_dbm": -58, "clock_ready": true, ... },
    "right": { "device_id": "MB_RIGHT", "connected": true, "rssi_dbm": -61, "clock_ready": true, ... }
  },
  "network":     { "pc_connected": true, "queued_messages": 2, ... },
  "led":         { "enabled": true, "backend": "rpi_ws281x", ... }
}
```

后端查找 `payload["microbit_left"]` / `payload["left_microbit"]`（顶级键），但硬件用的是 `payload["microbits"]["left"]`（嵌套结构）。

**修改方案**：从 `payload.get("microbits", {})` 取出嵌套 dict，再分别取 `left` / `right`。

**修改后的伪代码**：
```python
def apply_pi_status(self, payload: dict[str, Any]) -> None:
    with self._lock:
        self.pi_state["status"] = copy.deepcopy(payload)

        # Camera
        camera = payload.get("camera", {})
        if isinstance(camera, dict):
            self.camera_connected = _online(camera.get("connected", self.camera_connected))

        # Micro:bits
        microbits = payload.get("microbits", {})
        if isinstance(microbits, dict):
            left_mb = microbits.get("left", {})
            right_mb = microbits.get("right", {})
            if isinstance(left_mb, dict):
                self.microbit_left_connected = _online(
                    left_mb.get("connected", self.microbit_left_connected)
                )
            if isinstance(right_mb, dict):
                self.microbit_right_connected = _online(
                    right_mb.get("connected", self.microbit_right_connected)
                )
```

**核心改动**：`_online()` 的参数从整个 dict 改成 dict 内部的 `connected` 布尔字段（硬件 status 里的 `connected` 已经是 `bool`，直接取即可）。

---

### 修改 ③ — `state.py` 的 `apply_control_event`（第 104–106 行）

**现状问题**：
```python
def apply_control_event(self, payload: dict[str, Any], received_at: float) -> None:
    with self._lock:
        self.pi_state["last_control_event"] = {
            "received_at": received_at, "payload": copy.deepcopy(payload)
        }
```

只把事件存进 `pi_state.last_control_event`，不更新 `music_state`。前端轮询 `/api/music/state` 永远返回初始值 `{"playing": false, "bpm": 120, "volume": 0.8, "style": "piano"}`。

硬件实际发送的 payload 结构：
```json
{
  "event_id": "evt-00005",
  "event": {
    "type": "right_wrist_strike",
    "hand": "right",
    "confidence": 0.94,
    "strength": 0.83
  },
  "music_control": {
    "estimated_bpm": 118.1,
    "tempo_delta": 0.12,
    "volume": 0.73,
    "intensity": 0.81,
    "articulation": 0.58
  },
  "led_control": {
    "pattern": "right_pulse",
    "brightness": 0.25,
    "duration_ms": 120
  }
}
```

**修改方案**：在 `apply_control_event` 中提取 `music_control` 字段，直接更新 `music_state`。同时从 `event` 中提取当前手势名称。

**修改后的伪代码**：
```python
def apply_control_event(self, payload: dict[str, Any], received_at: float) -> None:
    with self._lock:
        # 存储原始事件
        self.pi_state["last_control_event"] = {
            "received_at": received_at, "payload": copy.deepcopy(payload)
        }

        # 同步更新音乐状态
        event = payload.get("event", {})
        music = payload.get("music_control", {})

        if isinstance(event, dict):
            gesture = event.get("type", "")
            self.music_state["current_gesture"] = gesture
            if gesture in ("downbeat", "left_wrist_strike", "right_wrist_strike"):
                self.music_state["playing"] = True
            elif gesture == "stop":
                self.music_state["playing"] = False

        if isinstance(music, dict):
            if "estimated_bpm" in music:
                self.music_state["bpm"] = int(music["estimated_bpm"])
            if "volume" in music:
                self.music_state["volume"] = round(float(music["volume"]), 2)
            if "intensity" in music and music["intensity"] > 0.7:
                # 高强度 → 触发风格轮换建议
                pass
```

**核心改动**：`apply_control_event` 不仅要存事件，还要把 `music_control` 里的 BPM、音量、强度映射到 `music_state`。这样前端 `/api/music/state` 就能拿到实时变化的音乐状态。

> **注意**：原有的 `_apply_music_effect()` 仍保留作为 `set_prediction()` 的调用方（供后续 PC 端直接推理的扩展场景使用），但不再是与硬件交互的必经路径。

---

### 修改 ④ — `state.py` 的 `GESTURES` 枚举（第 10–11 行）

**现状问题**：
```python
GESTURES = ("idle", "downbeat", "crescendo", "decrescendo", "cutoff",
            "style_switch", "tempo_up", "tempo_down")
```

硬件当前只产生 `downbeat`、`left_wrist_strike`、`right_wrist_strike` 3 种事件。其中后 2 种不在 `GESTURES` 中。`GESTURES` 被用来初始化 `current_prediction["all_probs"]`（第 24 行），也用于前端可视化。

**修改方案**：扩展 `GESTURES` 枚举，加入硬件能产生的事件类型。保留原有的 8 种以备后续扩展。

**修改后**：
```python
GESTURES = (
    "idle", "downbeat", "crescendo", "decrescendo", "cutoff",
    "style_switch", "tempo_up", "tempo_down",
    # 硬件直接检测的事件类型
    "left_wrist_strike", "right_wrist_strike", "bilateral_strike",
    "gesture_start", "gesture_end", "stop", "resume",
)
```

这保证了 `all_probs` 的初始化 dict 包含所有可能出现的事件 key，前端图表不会因为未知类型报错。

---

### 修改 ⑤ — `message_router.py` 清理（第 18–20 行 + 第 71–73 行）【可选】

`window_features` 已取消，对应的死代码可以清理：

**第 18 行** — `UPLINK_MESSAGE_TYPES` 中移除 `"window_features"`：
```python
# 修改前
UPLINK_MESSAGE_TYPES = frozenset({"fused_frame", "window_features", "control_event", "status"})
# 修改后
UPLINK_MESSAGE_TYPES = frozenset({"fused_frame", "control_event", "status"})
```

**第 19–21 行** — 删除 `AUTO_INFER_WINDOW_FEATURES`：
```python
# 整段删除
AUTO_INFER_WINDOW_FEATURES = os.getenv("AIOT_AUTO_INFER_WINDOW_FEATURES", "0").lower() in {
    "1", "true", "yes", "on"
}
```

**第 71–73 行** — 删除 `window_features` 分支：
```python
# 删除
elif message_type == "window_features" and AUTO_INFER_WINDOW_FEATURES and model_service.loaded:
    result = model_service.predict(payload)
    accept_prediction(result)
```

`COMMON_FIELDS` 中的 `"timestamp"` 字段也建议加入 `"event_id"`、`"event"`、`"music_control"`、`"led_control"`，因为 `control_event` 的这些字段不应被当作 payload 提取到外部（当前它们恰好因为在 `COMMON_FIELDS` 之外所以会被误提进 payload，但 `normalize_uplink_message` 的兜底逻辑使得结果碰巧正确，所以不是阻塞问题；加了可以让语义更清晰）。

> **这一步非必须**，因为 `window_features` 不在硬件发送的类型中，`route_uplink_message` 永远不会进入那个分支。清理只是为了代码整洁。

---

## 3. 修改顺序建议

```
① apply_fused_frame    — 解锁前端 micro:bit 实时数据显示
② apply_pi_status      — 解锁 Dashboard 连接指示灯
③ apply_control_event  — 解锁手势→音乐控制链路
④ GESTURES 枚举        — 保证 all_probs 初始化不缺失
⑤ 清理 message_router  — 可选项，代码整洁
```

按此顺序改，每一步都可以独立验证（前端轮询对应的 API 端点即可看到效果）。

---

## 4. 验证方法

修改完成后，在 PC 端启动后端，确认以下端点正常返回：

| API 端点 | 验证内容 |
|----------|----------|
| `GET /api/sensors/live` | `microbit_left` / `microbit_right` 有真实的 `raw_interpolated` 数据 |
| `GET /api/status` | `microbit_left` / `microbit_right` 为 `true`（Pi 连接且 BLE 在线时） |
| `GET /api/music/state` | `current_gesture`、`bpm`、`volume` 随硬件事件实时变化 |
| `GET /api/pi/status` | `last_control_event` 包含最新的事件 payload |

硬件端（Pi）无需重启，只需确认 Pi 的 TCP 已连接到 PC 的 9000 端口即可验证。

---

## 5. 硬件侧的后续对齐（不在本次修改范围）

| 项目 | 当前状态 | 建议 |
|------|----------|------|
| 事件类型覆盖 | 仅 2~3 种（jerk 阈值） | 后续在 `_detect_event_from_window()` 中扩展 crescendo/cutoff/tempo 等手势 |
| `instant_features` 为空 | `FusionEngine._build_microbit_entry()` 硬编码 `{}` | 后续从 ring buffer 的原始样本中提取 |
| BLE 时钟同步 | `_do_one_sync_round()` 是占位实现 | 后续捕获 SYNC_ACK 完成真实同步 |

---

## 6. 不改的说明

以下内容确认无需修改：

- **`backend/pi_gateway.py`**：TCP 服务器逻辑正确，不需要改
- **`backend/database.py`**：`pi_messages` 表通过 `normalize_uplink_message` 写入，payload 的 JSON 序列化不依赖字段结构
- **`backend/app.py`**：REST API 端点不需要改
- **`backend/model_service.py`**：保留供后续扩展，当前不调用
- **硬件 `MessageBuilder`**：消息构建逻辑正确，3 种类型的 payload 结构清晰
- **硬件 `FusionEngine`**：融合逻辑正确，`fused_frame` 数据结构合理
