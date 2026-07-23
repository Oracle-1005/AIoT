# AIoT 硬件项目结构说明

**更新日期**: 2026-07-23

本文档记录当前 `hardware/` 目录与树莓派运行目录的对应关系。当前正式链路为：

```text
micro:bit L/R -> BLE 广播 -> ESP32 -> UDP:17778 -> Raspberry Pi
Pi Camera -> Raspberry Pi
Raspberry Pi fusion_pipeline -> TCP:9000 -> PC backend
PC backend -> 模型 / Sonic Pi / 后续 LED 控制
```

树莓派统一运行根目录：

```text
/home/ag1_client/aiot_conductor/project
```

树莓派统一 Python 环境：

```text
/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python
```

旧目录 `/home/ag1_client/aiot_project` 不再作为运行根目录使用；历史内容已迁移或归档。

## 1. 树莓派运行目录

```text
/home/ag1_client/aiot_conductor/project/
├── camera_to_Pi/                         # 摄像头实际运行目录
│   ├── .venv/                            # 统一 Python 虚拟环境
│   ├── camera_to_pi/                     # 摄像头采集与 MediaPipe 包
│   ├── models/                           # 摄像头预览模型资源
│   ├── config.json
│   ├── main.py                           # 独立摄像头 JSONL 输出
│   └── visual_verify.py                  # 摄像头浏览器预览，HTTP 8765
│
├── hardware/
│   ├── fusion_pipeline/                  # 正式融合服务
│   │   ├── main.py                       # 融合服务入口
│   │   ├── config.yaml                   # UDP/TCP/camera/fusion 配置
│   │   ├── gateway_adapter.py            # ESP32 UDP 输入适配
│   │   ├── camera_adapter.py             # 摄像头输入适配
│   │   ├── fusion_engine.py              # jitter buffer 与时间对齐
│   │   ├── time_aligner.py               # 最近邻样本对齐
│   │   ├── tcp_client.py                 # 到 PC 后端的 TCP JSONL 客户端
│   │   ├── schemas.py                    # fused_frame / control_event / status 模板
│   │   ├── test_e2e.py                   # 无硬件模拟测试
│   │   └── pi-fusion.service             # systemd 服务模板
│   │
│   ├── pi_pc/                            # Pi 侧处理工具
│   │   ├── camera_clock.py               # 摄像头时间戳映射
│   │   ├── cleaner.py                    # 序号和间隙清理辅助
│   │   └── noise_filter.py               # micro:bit IMU 噪声过滤
│   │
│   ├── sensors/                          # 硬件抽象
│   │   ├── base.py
│   │   └── camera.py                     # Picamera2 + MediaPipe HandLandmarker
│   │
│   ├── raspberry_pi/
│   │   ├── camera_to_Pi/                 # 摄像头源码副本与说明
│   │   ├── esp32_ble_gateway_to_Pi/      # ESP32 UDP 接收器
│   │   ├── microbit_to_Pi/               # micro:bit 包解析协议
│   │   ├── MICROBIT_ESP32_CAMERA_DATA_FLOW.md
│   │   └── PI_PROJECT_LED_HANDOFF.md
│   │
│   ├── raspberry_pi_iot/
│   │   └── led/                          # 后续 LED 灯带控制预留目录
│   │
│   ├── esp32/
│   │   └── microbit_ble_wifi_gateway/    # ESP32 Arduino 网关固件
│   │
│   ├── microbit/
│   │   ├── microbit_to_pi/               # 当前 micro:bit MakeCode 广播固件
│   │   └── legacy_ble_connection_tests/  # 旧 BLE 直连实验归档
│   │
│   └── utils/
│
├── models/                               # fusion 服务共用 MediaPipe 模型
└── legacy/                               # 旧顶层脚本归档
```

## 2. PC 仓库中的 `hardware/` 目录

```text
hardware/
├── FUSION_PIPELINE_DEPLOY.md             # Pi 融合服务部署与验证
├── END_TO_END_TRANSMISSION_VERIFICATION.md # 完整端到端验证流程
├── PI_BACKEND_COMMUNICATION_PLAN.md      # Pi 与 PC 后端通信方案
├── PROJECT_STRUCTURE.md                  # 本文件
├── requirements.txt
│
├── fusion_pipeline/                      # Pi 正式融合服务源码
├── pi_pc/                                # Pi 侧滤波、清理、时钟映射工具
├── sensors/                              # 摄像头硬件抽象
├── raspberry_pi/                         # Pi 接收器、摄像头说明、LED 交接文档
├── raspberry_pi_iot/                     # LED 灯带控制预留
├── esp32/                                # ESP32 网关固件
├── microbit/                             # micro:bit 固件与旧 BLE 归档
│   ├── microbit_to_pi/                   # 当前 BLE 广播固件
│   └── legacy_ble_connection_tests/      # 旧 GATT/UART 连接实验，不作为正式链路
│
├── ble/                                  # 早期 BLE 实验
├── features/                             # 早期特征实验
├── fusion/                               # 早期融合实验
├── messages/                             # 早期消息结构实验
├── transport/                            # 早期传输实验
└── tests/                                # 早期硬件测试
```

PC 后端代码不在 `hardware/` 内，实际位置是：

```text
backend/
```

启动后端：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\app.py
```

## 3. 当前运行约束

- `pi-fusion.service` 从 `/home/ag1_client/aiot_conductor/project/hardware/fusion_pipeline` 运行。
- `pi-fusion.service` 使用 `/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python`。
- 正式 micro:bit 链路是 `micro:bit -> BLE 广播 -> ESP32 -> UDP:17778 -> Pi`。
- Pi 直连两块 micro:bit 的 BLE GATT/UART 方案只保留为历史调试材料，不作为当前稳定方案。
- 摄像头预览 `8765` 会占用 Pi Camera，不能与 `pi-fusion.service` 同时运行。
- micro:bit 预览 `8787` 会占用 UDP `17778`，不能与 `pi-fusion.service` 同时运行。
- PC 后端 `backend/app.py` 启动后监听 HTTP `5000` 和 TCP `9000`。

## 4. 核心验证方式

完整验证流程见：

```text
hardware/END_TO_END_TRANSMISSION_VERIFICATION.md
```

最常用的 PC 端验证命令：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 30
```

通过标准：

- `gateway_running=yes`
- `pi_connected=yes`
- `status` 计数持续增加
- `fused_frame` 计数持续增加
- 按下 micro:bit 按键后 `control_event` 计数增加

PC 浏览器可查看：

```text
http://127.0.0.1:5000/api/status
http://127.0.0.1:5000/api/pi/status
http://127.0.0.1:5000/api/sensors/live
http://127.0.0.1:5000/api/pi/messages?message_type=fused_frame&limit=5
```
