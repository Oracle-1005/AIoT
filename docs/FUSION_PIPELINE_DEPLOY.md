# AIoT 融合管线部署与验证指南

**版本**: 1.1
**日期**: 2026-07-23
**关联文档**: `hardware/raspberry_pi/MICROBIT_ESP32_CAMERA_DATA_FLOW.md`

**本机环境**:

| 项目 | 值 |
|------|-----|
| 树莓派 IP | `192.168.43.221` |
| 树莓派用户 | `ag1_client` |
| 树莓派项目根目录 | `/home/ag1_client/aiot_project/` |
| 树莓派 venv | `/home/ag1_client/aiot_project/venv/bin/python` |
| PC 后端 IP | `192.168.43.209` |
| PC 后端端口 | `9000` |

---

## 1. 架构

```
 micro:bit L/R ──BLE广播──→ ESP32 ──UDP:17778──→ Pi
 Camera ──Picamera2──→ MediaPipe ──→ Pi
                                         │
                                  FusionEngine
                                  (jitter buffer 250ms)
                                         │
                                  TcpJsonlClient TCP:9000
                                         │
                                         ▼
                                   PC Backend
                              (pi_gateway.py :9000)
                                         │
                              message_router → state / sonic_pi
```

### 1.1 组成

| 组件 | 位置 | 说明 |
|------|------|------|
| ESP32 网关 | 物理设备 | 扫描 BLE 广播，还原协议，UDP 转发 MBGW 帧 |
| micro:bit v2 × 2 | 物理设备 | 150ms 周期 BLE 广播，按键事件 7 次重复 |
| Pi Camera | 物理设备 | Picamera2 采集，MediaPipe 手部关键点检测 |
| fusion_pipeline | `hardware/fusion_pipeline/` | 融合管线（本指南部署目标） |
| PC Backend | `backend/` | TCP 服务器，接收 JSONL，路由到 state / sonic_pi |

### 1.2 消息类型

| type | 频率 | 触发源 |
|------|------|--------|
| `fused_frame` | ~30 Hz | 摄像头帧驱动，jitter buffer 延迟 250ms 后输出 |
| `microbit_control_event` | 事件驱动 | micro:bit 按键，快速通道，不等融合 |
| `status` | 1 Hz | 链路健康，含 micro:bit age/rssi、camera fps、jitter buffer |

---

## 2. 前置条件

### 2.1 硬件

- [ ] ESP32 网关已烧录固件（`hardware/esp32/microbit_ble_wifi_gateway/`）
- [ ] ESP32 Wi-Fi 已连接，与 Pi 同网段
- [ ] 两颗 micro:bit v2 已烧录广播固件（`hardware/microbit/microbit_to_pi/main.ts`）
- [ ] 两颗 micro:bit 上电，显示 **L** / **R**
- [ ] Pi Camera 已连接
- [ ] PC 与 Pi 在同一网络

### 2.2 软件

- [ ] Pi：Raspberry Pi OS (64-bit, Bookworm)，Python 3.11+
- [ ] Pi：已安装 `picamera2`、`mediapipe`、`pyyaml`
- [ ] PC：后端代码已部署，`backend/app.py` 可启动

---

## 3. 目录结构

```
aiot_project/                          # Pi 上项目根目录
├── hardware/
│   ├── fusion_pipeline/              # ★ 新融合管线
│   │   ├── main.py                   #     入口
│   │   ├── config.yaml               #     配置（需修改 tcp.host）
│   │   ├── fusion_engine.py          #     融合引擎 (jitter buffer)
│   │   ├── gateway_adapter.py        #     UDP 接收 + 噪声过滤
│   │   ├── camera_adapter.py         #     摄像头封装
│   │   ├── tcp_client.py             #     TCP JSONL 客户端
│   │   ├── time_aligner.py           #     最近邻对齐
│   │   ├── schemas.py                #     消息模板
│   │   ├── test_e2e.py               #     端到端测试
│   │   └── pi-fusion.service         #     systemd 服务文件
│   │
│   ├── pi_pc/                        # DSP 模块
│   │   ├── noise_filter.py           #     EMA + Median 噪声过滤
│   │   ├── camera_clock.py           #     摄像头时钟线性回归
│   │   └── cleaner.py                #     序列间隙检测
│   │
│   ├── sensors/                      # 硬件抽象
│   │   └── camera.py                 #     CameraSensor
│   │
│   ├── raspberry_pi/
│   │   ├── esp32_ble_gateway_to_Pi/  # ESP32 网关接收器
│   │   ├── microbit_to_Pi/           # 协议解析 + 序号追踪
│   │   └── camera_to_Pi/             # 摄像头预览
│   │
│   └── utils/                        # 配置工具
│
├── backend/                          # PC 后端（在 PC 上运行）
│   ├── app.py
│   ├── pi_gateway.py                 # TCP 服务器 (:9000)
│   ├── message_router.py             # 消息验证与路由
│   └── state.py                      # 实时状态管理
│
├── venv/                             # Python 虚拟环境
└── models/                           # MediaPipe 模型
```

---

## 4. 部署步骤

### 4.1 同步代码到树莓派

```bash
# 在开发机上执行
PI_IP=192.168.43.221
PI_USER=ag1_client
PI_ROOT=/home/ag1_client/aiot_project

# 使用 rsync 同步（排除 microbit/esp32 固件）
sshpass -p '123123' rsync -avz \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'microbit/' \
    --exclude 'esp32/' \
    -e 'ssh -o StrictHostKeyChecking=accept-new' \
    hardware/ \
    ${PI_USER}@${PI_IP}:${PI_ROOT}/hardware/
```

如果开发机未安装 `sshpass`：
```bash
brew install sshpass   # macOS
# 或
sudo apt install sshpass  # Linux
```

### 4.2 安装 Python 依赖

```bash
ssh ag1_client@192.168.43.221
cd /home/ag1_client/aiot_project

# 确认 venv 存在
ls venv/bin/python

# 安装额外依赖
venv/bin/pip install pyyaml

# 验证导入链
venv/bin/python -c "
import sys
sys.path.insert(0, 'hardware')
sys.path.insert(0, 'hardware/raspberry_pi/esp32_ble_gateway_to_Pi')
sys.path.insert(0, 'hardware/raspberry_pi/microbit_to_Pi')
from fusion_pipeline import FusionEngine, GatewayAdapter, TcpJsonlClient
print('OK — all imports work')
"
```

### 4.3 配置融合管线

```bash
nano /home/ag1_client/aiot_project/hardware/fusion_pipeline/config.yaml
```

关键配置项：

```yaml
tcp:
  host: "192.168.43.209"    # ← PC 后端 IP
  port: 9000

gateway:
  listen_host: "0.0.0.0"
  listen_port: 17778         # ESP32 UDP 目标端口

camera:
  width: 640
  height: 480
  fps: 30

fusion:
  max_age_ms: 120            # micro:bit 样本最大有效期
  buffer_max_age_s: 10.0     # buffer 中样本最大保留时间
  jitter_buffer_ms: 250      # 延迟融合窗口 (150~350)

general:
  log_level: "INFO"          # 调试时改为 DEBUG
  status_interval_s: 1.0     # status 消息间隔
```

### 4.4 安装 systemd 服务

```bash
# 复制并修正路径
sudo cp /home/ag1_client/aiot_project/hardware/fusion_pipeline/pi-fusion.service \
    /etc/systemd/system/

# 修正用户名和路径（如果需要）
sudo sed -i 's|/home/pi/aiot|/home/ag1_client/aiot_project|g' \
    /etc/systemd/system/pi-fusion.service
sudo sed -i 's|User=pi|User=ag1_client|g' \
    /etc/systemd/system/pi-fusion.service
sudo sed -i 's|pi5/venv|venv|g' \
    /etc/systemd/system/pi-fusion.service

# 重载并启用
sudo systemctl daemon-reload
sudo systemctl enable pi-fusion
```

验证服务文件：
```bash
grep ExecStart /etc/systemd/system/pi-fusion.service
# 应输出:
# ExecStart=/home/ag1_client/aiot_project/venv/bin/python -u \
#   /home/ag1_client/aiot_project/hardware/fusion_pipeline/main.py \
#   --config config.yaml
```

### 4.5 运行端到端测试（可选，无需硬件）

```bash
cd /home/ag1_client/aiot_project/hardware/fusion_pipeline
/home/ag1_client/aiot_project/venv/bin/python test_e2e.py

# 预期: 🎉 ALL CHECKS PASSED
```

---

## 5. 启动顺序

```
 ① PC Backend (:9000)       ② ESP32 Gateway          ③ Pi fusion_pipeline
       │                         │                         │
       ├─ 启动                   │                         │
       │                         ├─ 上电, 连接WiFi         │
       │                         │  开始扫描BLE             │
       │                         │                         ├─ 启动
       │                         │                         │  TCP→PC:9000
       │                         │  UDP MBGW 帧 ←─────────┤  监听UDP:17778
       │                         │                         │  启动Camera
       │  ←── fused_frame ─────  │  ←── sensor_state ───  │
       │  ←── control_event ───  │  ←── control_event ──  │
       │  ←── status ──────────  │  ←── health ─────────  │
```

### 5.1 启动 PC 后端

```bash
# 在 PC (192.168.43.209) 上
cd ~/aiot_conductor/backend
source venv/bin/activate
python app.py

# 预期输出:
# [PiGateway] Listening on 0.0.0.0:9000
```

### 5.2 确认硬件在线

```bash
# Pi 端 — 确认 ESP32 在线
curl http://127.0.0.1:8787/health
# 预期: {"status": "live", ...}

# Pi 端 — 确认 micro:bit 数据到达 ESP32
cd /home/ag1_client/aiot_project/hardware/raspberry_pi/esp32_ble_gateway_to_Pi
/home/ag1_client/aiot_project/venv/bin/python \
    -m esp32_gateway_receiver.app --config config.example.json 2>/dev/null | head -3
# 预期: {"type":"microbit_sensor_state","source":"left",...}
```

### 5.3 启动融合管线

```bash
# Pi 端
sudo systemctl start pi-fusion

# 查看实时日志
sudo journalctl -u pi-fusion -f

# 正常日志输出:
# === AIoT Fusion Pipeline ===
# GatewayAdapter listening on 0.0.0.0:17778
# Camera started.
# TCP connected to 192.168.43.209:9000
# === Fusion Pipeline started ===
# Main loop started: poll=200 Hz, status=1 Hz
```

---

## 6. 验证数据到达

### 6.1 方式一 — 后端健康接口

```bash
# PC 端
curl -s http://localhost:5000/api/pi-gateway/status | python3 -m json.tool
```

预期输出：
```json
{
    "connected": true,
    "running": true,
    "received_messages": 1523,
    "sent_messages": 0,
    "client_address": ["192.168.43.221", 45678],
    "last_received_at": 1721734567.89
}
```

`received_messages` 持续增长即表示数据正常到达。

### 6.2 方式二 — 查看后端日志

```bash
# PC 端 — app.py 运行终端
# 每秒应收到:
#   ~25 条 fused_frame (type=fused_frame)
#   1 条 status (type=status)
```

### 6.3 方式三 — 查看 Pi 日志

```bash
# Pi 端
sudo journalctl -u pi-fusion -n 20

# 关注指标:
# - 无 "ERROR" 级别日志
# - "TCP connected to 192.168.43.209:9000" 表示与 PC 连接正常
# - 无 "Jitter buffer overflow" 警告
```

### 6.4 方式四 — 端到端测试

```bash
# Pi 端 — 模拟测试（不需要硬件，融合管线需先停止）
sudo systemctl stop pi-fusion
cd /home/ag1_client/aiot_project/hardware/fusion_pipeline
/home/ag1_client/aiot_project/venv/bin/python test_e2e.py

# 预期: 🎉 ALL CHECKS PASSED
sudo systemctl start pi-fusion   # 恢复服务
```

### 6.5 方式五 — 按键事件验证

按下右 micro:bit 的 **B 键并长按 1 秒**：

```bash
# Pi 端日志
sudo journalctl -u pi-fusion -f | grep B_LONG_PRESS

# PC 后端日志应出现 control_event → emergency_stop
```

---

## 7. 验证清单

| # | 检查项 | 命令 | 预期结果 |
|---|--------|------|----------|
| 1 | ESP32 在线 | `curl http://192.168.43.221:8787/health` | `"status": "live"` |
| 2 | Pi UDP 监听 | `sudo journalctl -u pi-fusion \| grep Gateway` | `listening on 0.0.0.0:17778` |
| 3 | Pi TCP 连接 | `sudo journalctl -u pi-fusion \| grep "TCP connected"` | `TCP connected to 192.168.43.209:9000` |
| 4 | Pi 无错误 | `sudo journalctl -u pi-fusion -n 10` | 无 ERROR |
| 5 | PC 端连接 | `curl localhost:5000/api/pi-gateway/status` | `"connected": true` |
| 6 | 消息到达 | 同上 | `"received_messages" > 0` 且持续增长 |
| 7 | 控制事件 | 长按 micro:bit B 键 | 后端收到 `emergency_stop` |
| 8 | 端到端测试 | `venv/bin/python test_e2e.py` | ALL CHECKS PASSED |

---

## 8. 故障排查

### 8.1 Pi 端服务状态

```bash
# 服务状态
sudo systemctl status pi-fusion

# 最近 50 行日志
sudo journalctl -u pi-fusion -n 50 -f

# 手动运行（调试模式，先停止服务）
sudo systemctl stop pi-fusion
cd /home/ag1_client/aiot_project/hardware/fusion_pipeline
/home/ag1_client/aiot_project/venv/bin/python main.py --config config.yaml
# Ctrl+C 停止，然后恢复服务: sudo systemctl start pi-fusion
```

### 8.2 常见问题

| 症状 | 可能原因 | 解决 |
|------|----------|------|
| `TCP connected` 未出现 | PC IP 错误或后端未启动 | 检查 `config.yaml` 中 `tcp.host: "192.168.43.209"`，确认 PC 端 `app.py` 已运行 |
| `GatewayAdapter` 无数据 | ESP32 未连接或 Wi-Fi 问题 | 检查 ESP32 固件 Wi-Fi SSID/密码，`curl http://192.168.43.221:8787/health` 确认在线 |
| 大量 `missing_sources` | Jitter buffer 太小或 BLE 信号差 | 增大 `jitter_buffer_ms` 到 300-350ms |
| `Jitter buffer overflow` | 摄像头帧率远超消费速率 | 降低 `camera.fps` 或增大 `fusion_poll_interval_s` |
| Pi 端 `ImportError` | 依赖缺失或路径不对 | 运行 4.2 节导入验证，确认 venv 已安装 pyyaml |
| 微:bit 数据不到达 | ESP32 扫描不到 BLE 广播 | 缩短 micro:bit 与 ESP32 距离 (30cm~1m)；两块 micro:bit 不要贴在一起 |
| `Permission denied` 登录 Pi | 密码或用户不对 | 确认用户 `ag1_client`，密码 `123123` |

### 8.3 PC 端故障排查

```bash
# 确认 9000 端口在监听
lsof -i :9000

# 确认 Pi 能连通 PC（在 Pi 上执行）
nc -zv 192.168.43.209 9000

# 后端日志 — 直接看 app.py 运行的终端输出
```

---

## 9. 配置调优

### 9.1 Jitter Buffer 调整

`jitter_buffer_ms` 控制融合延迟与数据完整性的权衡：

| 值 | 适用场景 |
|----|----------|
| 150ms | BLE 信号极好 (RSSI > -50)，微:bit < 50cm |
| **250ms** | **推荐默认值**，覆盖一次完整采样周期 (150ms) + 网络余量 |
| 350ms | BLE 信号较弱 (RSSI < -75)，偶发大延迟 |

### 9.2 对齐阈值调整

```yaml
fusion:
  max_age_ms: 120          # 增大 → 容忍更旧的样本 → 更多 available=true
                           # 减小 → 更严格 → 更多 available=false
```

### 9.3 噪声过滤调整

```yaml
gateway:
  noise_filter:
    ema_alpha_accel: 0.85        # 更高 → 更平滑但响应慢 (0.8~0.95)
    ema_alpha_orientation: 0.90  # 同上
    outlier_threshold_mg: 500    # 更大 → 容忍更大的离群值
```

---

## 10. 日常运维

```bash
# 启动
sudo systemctl start pi-fusion

# 停止
sudo systemctl stop pi-fusion

# 重启
sudo systemctl restart pi-fusion

# 禁用开机自启
sudo systemctl disable pi-fusion

# 查看实时日志
sudo journalctl -u pi-fusion -f

# 查看最近 100 行
sudo journalctl -u pi-fusion -n 100

# 查看今日日志
sudo journalctl -u pi-fusion --since today

# 查看服务是否启用
sudo systemctl is-enabled pi-fusion

# 查看服务是否运行
sudo systemctl is-active pi-fusion
```

---

## 11. 快速部署速查

```bash
# === 在开发机上 ===
PI_IP=192.168.43.221
PI_USER=ag1_client
PI_ROOT=/home/ag1_client/aiot_project

# 1. 同步代码
sshpass -p '123123' rsync -avz \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
    --exclude 'microbit/' --exclude 'esp32/' \
    -e 'ssh -o StrictHostKeyChecking=accept-new' \
    hardware/ ${PI_USER}@${PI_IP}:${PI_ROOT}/hardware/

# 2. 安装依赖
sshpass -p '123123' ssh ${PI_USER}@${PI_IP} \
    "${PI_ROOT}/venv/bin/pip install pyyaml -q"

# 3. 安装 systemd 服务（首次部署）
sshpass -p '123123' ssh ${PI_USER}@${PI_IP} "
    sudo cp ${PI_ROOT}/hardware/fusion_pipeline/pi-fusion.service /etc/systemd/system/ &&
    sudo sed -i 's|/home/pi/aiot|${PI_ROOT}|g' /etc/systemd/system/pi-fusion.service &&
    sudo sed -i 's|User=pi|User=${PI_USER}|g' /etc/systemd/system/pi-fusion.service &&
    sudo sed -i 's|pi5/venv|venv|g' /etc/systemd/system/pi-fusion.service &&
    sudo systemctl daemon-reload &&
    sudo systemctl enable pi-fusion
"

# 4. 启动融合管线
sshpass -p '123123' ssh ${PI_USER}@${PI_IP} "sudo systemctl restart pi-fusion"

# 5. 查看日志
sshpass -p '123123' ssh ${PI_USER}@${PI_IP} "sudo journalctl -u pi-fusion -f"
```
