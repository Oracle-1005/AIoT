# 现场链路测试手册（硬件组交接）

**日期**: 2026-07-24
**交接状态**: 全链路在线，可直接开始现场测试
**关联文档**: `hardware/FUSION_PIPELINE_DEPLOY.md`、`hardware/fusion_pipeline/FUSION_LIVE_PREVIEW.md`

---

## 0. 一句话现状

```text
micro:bit ×2 ──BLE──→ ESP32 ──UDP:17778──→ Pi fusion ──TCP:9000──→ PC 后端 (192.168.43.117)
Camera ──→ Pi (MediaPipe) ──┘                    │
                                          进程内预览页 :8790（视频+数据）
```

后端、推理链（GestureClassifier 规则版）、8790 预览页均已在线运行。
**本次测试由硬件组员执行，本文档是操作与判定依据。**

---

## 1. 当前运行环境

| 组件 | 位置 | 状态 |
|------|------|------|
| PC 后端 | `192.168.43.117`（Flask `:5000` REST + TCP `:9000`） | 运行中，`model_loaded=true` |
| pi-fusion | Pi `192.168.43.221`，`pi-fusion.service`（systemd） | active，已连 `.117:9000` |
| 摄像头 | Pi Camera（ov5647，640×480 @ 30fps + MediaPipe） | 由 pi-fusion 独占 |
| micro:bit ×2 / ESP32 | 广播 150ms → UDP:17778 | 在线（后端 `microbit_left/right=true`） |
| 进程内预览页 | `http://192.168.43.221:8790/` | 随 pi-fusion 同进程运行 |

Pi 上关键配置（`/home/ag1_client/aiot_conductor/project/hardware/fusion_pipeline/config.yaml`）：

```yaml
tcp:
  host: "192.168.43.117"   # ← 当前指向本机后端；后端若搬回 .209 需改回并 restart
  port: 9000
video_stream:
  enabled: true            # 备用视频流配置（当前 main.py 未使用，见 §6.3）
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

### 3.2 九动作序列

每个动作**持续约 3 秒，动作之间静止 2 秒**。观察者盯 `/api/gesture/current`（或 8790 页数据区），记录每个动作的识别标签。

| # | 动作 | 预期识别 |
|---|------|---------|
| 1 | 双手静止不动 | `idle` |
| 2 | 右手从身侧抬到指挥位 | `gesture_start` |
| 3 | 右手有力地下砸一次（打拍子） | `downbeat` |
| 4 | 右手向上挑起一次 | `upbeat` |
| 5 | 右手摆动渐快渐大、手同时上抬张开 | `crescendo` |
| 6 | 右手摆动渐慢收小、手同时下降收拢 | `decrescendo` |
| 7 | 只动左手向左侧指/摆，右手静止 | `left_cue` |
| 8 | 只动右手向右侧指/摆，左手静止 | `right_cue` |
| 9 | 运动中突然双手定住 | `stop` |

### 3.3 按键快速通道

- 右手 micro:bit **长按 B 键 1 秒**；
- 预期：`/api/pi/status` 的 `control_event` 计数 +1，8790"发送前消息"区出现 `control_event`。

### 3.4 判定标准

- **通过**：9 个动作中 ≥7 个在各自时间窗内被识别为预期标签；按键事件到达。
- **注意**：当前是规则版分类器（占位），置信度 0.3~0.8 都正常；录数据重训后会换模型版。
- 误识别不用现场调试，把"动作 → 实际标签"记录下来反馈即可。

---

## 4. 服务运维速查（Pi 端）

```bash
# 查看状态 / 重启 / 日志
sudo systemctl status pi-fusion
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -f

# 关键日志标志
#   "TCP connected to 192.168.43.117:9000"  → 上行链路正常
#   "Fusion preview listening on ...:8790"  → 预览页正常
#   "Camera started."                        → 摄像头正常
```

**互斥提醒**：独立预览脚本（8765 摄像头、8787 micro:bit、以及独立运行的
`live_preview.py`）会抢占摄像头/UDP:17778，**不能与 pi-fusion 同时运行**。
但 12:49 起 8790 是 fusion 进程内预览，不互斥，可直接使用。

**后端切回 .209**：改 `config.yaml` 的 `tcp.host` 后 `sudo systemctl restart pi-fusion`。

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
2. **Pi 上改动未入库**：`preview_server.py` 及配套 `main.py` 改动目前只存在于
   Pi 本地（仓库最新提交为 `6cf4715`）。**请硬件组员尽快 commit & push**，
   否则下次代码同步会覆盖丢失。
3. **两套视频流并存待合并**：仓库内 `video_stream.py`（8791，config 开关）
   与 Pi 上 `preview_server.py`（8790，功能更全）功能重叠。当前以 8790 为准，
   后续合并时二选一，8791 默认关闭不影响任何链路。
4. **单目标上行**：`tcp.host` 只能指向一台后端。`.117`（本机）与 `.209`
   不要同时期望接收同一 Pi 的数据，切换时群里知会。
5. **Windows 防火墙**：`.117` 的 `:9000` 入站已实测放行，无需操作；
   若后端换机器运行，需重新验证 `nc -zv <新IP> 9000`。

---

## 7. 分工联系

| 范围 | 负责人 |
|------|--------|
| Pi 服务 / 摄像头 / ESP32 / micro:bit / 现场执行 | 硬件组员 |
| 后端 / 推理链 / 识别结果异常分析 | 后端侧（本机 `.117`） |
