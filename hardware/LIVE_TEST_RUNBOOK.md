# 现场链路测试手册（硬件组交接）

**日期**: 2026-07-24
**交接状态**: 全链路在线，可直接开始现场测试
**关联文档**: `hardware/FUSION_PIPELINE_DEPLOY.md`、`hardware/fusion_pipeline/FUSION_LIVE_PREVIEW.md`

---

## 0. 一句话现状

```text
micro:bit ×2 ──BLE──→ ESP32 ──UDP:17778──→ Pi fusion ──TCP:9000──→ PC 后端 (192.168.43.209)
Camera ──→ Pi (MediaPipe) ──┘                    │
                                          进程内预览页 :8790（视频+数据）
```

后端、推理链（GestureClassifier 规则版）、8790 预览页均已在线运行。
**本次测试由硬件组员执行，本文档是操作与判定依据。**

---

## 1. 当前运行环境

| 组件 | 位置 | 状态 |
|------|------|------|
| PC 后端 | `192.168.43.209`（Flask `:5000` REST + TCP `:9000`） | 运行中，`model_loaded=true` |
| pi-fusion | Pi `192.168.43.221`，`pi-fusion.service`（systemd） | active，已连 `.209:9000` |
| 摄像头 | Pi Camera（ov5647，配置 640×480 @ 30fps，实际约 16~17fps + MediaPipe） | 由 pi-fusion 独占 |
| micro:bit ×2 / ESP32 | 广播 150ms → UDP:17778 | 在线（后端 `microbit_left/right=true`） |
| 进程内预览页 | `http://192.168.43.221:8790/` | 随 pi-fusion 同进程运行 |

Pi 上关键配置（`/home/ag1_client/aiot_conductor/project/hardware/fusion_pipeline/config.yaml`）：

```yaml
tcp:
  host: "192.168.43.209"   # ← 当前 PC 后端 IP；PC 换网后需同步修改并 restart
  port: 9000
video_stream:
  enabled: true            # 可选独立 MJPEG 视频流；主预览仍优先使用 8790
camera:
  pixel_format: "BGR888"
  min_hand_detection_confidence: 0.35
  min_hand_presence_confidence: 0.35
  min_tracking_confidence: 0.40
  max_missing_frames: 4    # 仅视频预览保持，不伪造训练关键点
```

---

## 2. 浏览器/接口入口

| 入口 | 用途 |
|------|------|
| `http://192.168.43.221:8790/` | **主预览页**：摄像头视频（含 MediaPipe 叠加）、micro:bit 原始/过滤数据、发送前完整消息、消息队列 |
| `http://127.0.0.1:5000/api/gesture/current` | 当前手势识别结果（gesture/confidence） |
| `http://127.0.0.1:5000/api/gesture/history?limit=50` | 最近识别历史 |
| `http://127.0.0.1:5000/api/pi/status` | Pi 链路状态（消息计数） |
| `http://127.0.0.1:5000/api/status` | 后端总状态（推理计数、网关、模型） |

---

## 3. 现场测试流程（约 3 分钟）

### 3.1 站位

- 正对摄像头 **1~1.5 米**，双手入画，光线充足；
- 先在 8790 页面确认能看到自己、手部关键点叠加正常跟随。
- 手持续入画时观察 `5s detection`，建议稳定在 85% 以上；`miss streak` 不应频繁超过 4。
- `preview held` 偶尔为 1/2 表示视频使用短时保持，不代表该帧已经生成真实关键点。

### 3.2 九动作序列（camera-v1 模型版动作定义，2026-07-25 定稿）

每个动作**持续约 3 秒，动作之间静止 2 秒**。观察者盯 `/api/gesture/current`（或 8790 页数据区），记录每个动作的识别标签。

| # | 动作 | 预期识别 |
|---|------|---------|
| 1 | 双手静止或放下 | `idle` |
| 2 | **右手**张开→握拳（约 0.5 秒内握紧） | `gesture_start` |
| 3 | 右手张掌快速下劈急停（全程手型不变） | `downbeat` |
| 4 | 右手张掌快速上挑急停（全程手型不变） | `upbeat` |
| 5 | 双手掌心向前（正对摄像头），慢速上托 | `crescendo` |
| 6 | 双手掌心向前（正对摄像头），慢速下压 | `decrescendo` |
| 7 | 左手指向左侧（全程保持指出手型），右手静止 | `left_cue` |
| 8 | 右手指向右侧（全程保持指出手型），左手静止 | `right_cue` |
| 9 | **左手**张开→握拳（约 0.5 秒内握紧） | `stop` |

**动作协议（识别原理决定，务必遵守）：**

- 握拳识别的是"握"这一下：张开→握紧的过渡须落在约 1 秒窗口内；握紧保持不动 1 秒后会自然衰减回 `idle`——这是特性，触发→LED/音乐响应→回 idle 正是设计行为。
- `start`/`stop` 的唯一区分是**手别**（右拳=start，左拳=stop）；演示前不要改机位/镜像翻转，否则左右整体互换。
- downbeat/upbeat/cue 类动作**全程保持手型不变**（指出动作直接保持指出手型平移，不要从张掌变指），否则手掌开合信号会串扰到 start/stop。
- 避免双手同时握拳（不在词表内，模型未见过）。
- 掌心向前 = 掌心正对摄像头：掌心朝向本身不是模型特征（crescendo/decrescendo 靠"慢速上/下"的垂直位移区分），但正对手掌 MediaPipe 检测最稳。
- 双手全程佩戴 micro:bit（左 L 右 R），**录制与演示佩戴状态必须一致**（佩戴状态本身是特征）。

### 3.3 按键快速通道

- 右手 micro:bit **长按 B 键 1 秒**；
- 预期：`/api/pi/status` 的 `control_event` 计数 +1，8790"发送前消息"区出现 `control_event`。

### 3.4 判定标准

- **通过**：9 个动作中 ≥7 个在各自时间窗内被识别为预期标签；按键事件到达。
- **注意**：当前为模型模式（RF，camera-v1，9 类）；模型文件缺失时回退规则版，置信度口径不同，以 `mode` 字段为准。
- 误识别不用现场调试，把"动作 → 实际标签"记录下来反馈即可。

---

## 4. 服务运维速查（Pi 端）

```bash
# 查看状态 / 重启 / 日志
sudo systemctl status pi-fusion
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -f

# 关键日志标志
#   "TCP connected to 192.168.43.209:9000"  → 上行链路正常
#   "Fusion preview listening on ...:8790"  → 预览页正常
#   "Camera started."                        → 摄像头正常
```

**互斥提醒**：独立预览脚本（8765 摄像头、8787 micro:bit、以及独立运行的
`live_preview.py`）会抢占摄像头/UDP:17778，**不能与 pi-fusion 同时运行**。
但 12:49 起 8790 是 fusion 进程内预览，不互斥，可直接使用。

**后端换 IP**：改 `config.yaml` 的 `tcp.host` 后 `sudo systemctl restart pi-fusion`。

---

## 5. 记录反馈格式

测完把结果按此格式发回（示例）：

```text
1 idle → idle ✓
2 gesture_start → gesture_start ✓
3 downbeat → downbeat ✓ (0.62)
...
按键 B 长按 → control_event 到达 ✓
8790 页面视频/数据是否正常：是/否（附现象）
```

---

## 6. 已知问题与注意（重要）

1. **摄像头画面物理倒置**：装机时镜头上下颠倒，画面旋转 180°。会导致
   下砸/上挑（downbeat/upbeat）方向互换。**请先把机位正过来再测**；
   不便物理调整时可改 picamera2 Transform 软件翻转（联系后端侧）。
2. **8790 与 8791 的关系**：`8790` 是正式链路联合预览，展示摄像头、micro:bit 和发送前融合数据；`8791` 是可选独立 MJPEG 摄像头流。两者均在 `pi-fusion` 进程内复用摄像头，不应再单独启动 `8765` 摄像头预览。
3. **单目标上行**：`tcp.host` 只能指向一台后端。当前指向 `.209`，如果后端换机器运行，需要同步修改 Pi 的 `config.yaml` 并重启 `pi-fusion`。
4. **Windows 防火墙**：`.209` 的 `:9000` 入站已实测放行，无需操作；
   若后端换机器运行，需重新验证 `nc -zv <新IP> 9000`。

---

## 7. 分工联系

| 范围 | 负责人 |
|------|--------|
| Pi 服务 / 摄像头 / ESP32 / micro:bit / 现场执行 | 硬件组员 |
| 后端 / 推理链 / 识别结果异常分析 | 后端侧（本机 `.209`） |
