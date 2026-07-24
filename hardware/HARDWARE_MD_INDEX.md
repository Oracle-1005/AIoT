# Hardware Markdown 文档索引

**更新日期**: 2026-07-24

本文档用于快速查找 `hardware/` 目录下的 Markdown 文档。后续如果新增、删除或修改 `hardware/` 下的 `.md` 文档，应同步更新本文档，至少维护：

- 文档路径；
- 文档主题；
- 当前是否属于正式链路；
- 主要验证入口或适用场景。

当前正式硬件链路：

```text
micro:bit L/R -> BLE 广播 -> ESP32 -> UDP:17778 -> Raspberry Pi
Pi Camera -> Raspberry Pi
Raspberry Pi fusion_pipeline -> TCP:9000 -> PC backend
```

## 1. 总览与部署

| 文档 | 位置 | 内容概括 | 使用场景 |
| --- | --- | --- | --- |
| Hardware Markdown 文档索引 | `hardware/HARDWARE_MD_INDEX.md` | 汇总 `hardware/` 下所有 Markdown 文档的位置、用途和维护规则。 | 查找文档入口；新增或修改文档后更新索引。 |
| 硬件项目结构说明 | `hardware/PROJECT_STRUCTURE.md` | 说明 PC 仓库和树莓派运行目录的当前结构，明确正式链路、虚拟环境、预览端口和后端位置。 | 查目录、确认当前架构、判断旧目录是否仍在使用。 |
| 融合管线部署与验证指南 | `hardware/FUSION_PIPELINE_DEPLOY.md` | 说明 `pi-fusion.service`、`fusion_pipeline`、ESP32 网关、摄像头和 PC 后端的部署与验证。 | 部署或重启 Pi 正式融合服务。 |
| 端到端传输验证流程 | `hardware/END_TO_END_TRANSMISSION_VERIFICATION.md` | 给出从 micro:bit、ESP32、Pi Camera、Pi fusion 到 PC backend 的完整验证步骤。 | 做整链路验收；确认 `status`、`fused_frame`、`control_event` 是否到达 PC。 |
| Raspberry Pi 与 PC 后端通信方案 | `hardware/PI_BACKEND_COMMUNICATION_PLAN.md` | 说明 Pi 到 PC 的 TCP JSON Lines 上行消息，以及 PC 到 Pi 的 LED/system 下行预留。 | 对接后端、模型、Sonic Pi 或后续 LED 控制。 |
| 现场链路测试手册（硬件组交接） | `hardware/LIVE_TEST_RUNBOOK.md` | 当前运行环境、8790 进程内预览入口、九动作现场测试流程与判定标准、已知问题（机位倒置、Pi 改动未入库等）。 | 硬件组员现场执行链路测试的操作依据。 |

## 2. micro:bit 与 ESP32

| 文档 | 位置 | 内容概括 | 使用场景 |
| --- | --- | --- | --- |
| 双 micro:bit 到树莓派数据链路说明 | `hardware/microbit/microbit_to_pi/README.md` | 说明当前 micro:bit v2 BLE 广播固件、左右手 `HAND` 设置、IMU 字段、按键事件和正式验证方式。 | 烧录或检查 micro:bit 固件；理解加速度和按键事件。 |
| micro:bit 到树莓派数据可视化验证说明 | `hardware/microbit/microbit_to_pi/MICROBIT_VISUAL_VERIFICATION.md` | 说明 `8787` micro:bit 预览页面、左右手状态显示、按键事件和端口冲突处理。 | 独立验证 micro:bit -> ESP32 -> Pi 是否稳定。 |
| ESP32 micro:bit BLE 广播转 Wi-Fi 网关 | `hardware/esp32/microbit_ble_wifi_gateway/README.md` | 说明 ESP32 Arduino 固件配置、Wi-Fi/Pi IP 修改、BLE 广播解析、UDP 网关帧和正式融合验证。 | 配置或重新上传 ESP32 网关固件。 |
| ESP32 BLE 网关到树莓派 UDP 接收器 | `hardware/raspberry_pi/esp32_ble_gateway_to_Pi/README.md` | 说明 Pi 端 `esp32_gateway_receiver` 的安装、命令行接收、模拟包验证和 `8787` 预览接入。 | 单独验证 Pi 是否能收到 ESP32 UDP 数据。 |
| 旧 BLE 直连实验归档 | `hardware/microbit/legacy_ble_connection_tests/README_BLE.md` | 记录旧 MakeCode BLE UART/GATT 直连实验。该方案不属于当前正式链路。 | 仅作历史参考，不作为验收标准。 |
| 硬件侧任务清单 | `hardware/HARDWARE_TASKS.md` | micro:bit 发射功率实验（辅助传感器，目标稳定在线 + 有效 ≥3 Hz）、ESP32 固件确认、micro:bit 重烧注意、LED 改 GPIO19/ws2812-pio 的文档更正。 | 硬件组员当前待办入口；采样率确认实验操作说明。 |

## 3. 摄像头与融合数据

| 文档 | 位置 | 内容概括 | 使用场景 |
| --- | --- | --- | --- |
| Camera 到 Raspberry Pi 采集与手部关键点说明 | `hardware/raspberry_pi/camera_to_Pi/README.md` | 说明 Picamera2、MediaPipe HandLandmarker、关键点输出、质量字段、去噪和静态测试。 | 单独理解或验证摄像头采集与关键点输出。 |
| 摄像头可视预览与后续融合接口说明 | `hardware/raspberry_pi/camera_to_Pi/CAMERA_PREVIEW_AND_FUSION.md` | 说明 `8765` 摄像头预览、MediaPipe 模型、预览关闭方式、摄像头输出和当前 `fused_frame` 结构。 | 打开或关闭摄像头预览；理解摄像头与 fusion 的互斥关系。 |
| 摄像头、micro:bit 与融合发送前数据联合预览 | `hardware/fusion_pipeline/FUSION_LIVE_PREVIEW.md` | 说明 `8790` 联合预览页面，集中展示摄像头 MediaPipe 输出、micro:bit 原始/过滤后样本，以及即将发送给 PC 的完整 `fused_frame`/`control_event`/`status`。 | 调试训练数据是否完整；定位采集、过滤、时间同步或发送前格式问题。 |
| micro:bit v2 广播、ESP32 网关与摄像头数据整理说明 | `hardware/raspberry_pi/MICROBIT_ESP32_CAMERA_DATA_FLOW.md` | 说明 micro:bit 广播包、ESP32 UDP 帧、Pi 接收、摄像头关键点、时间同步和融合输出。 | 理解传感器数据如何进入训练样本和后端。 |

## 4. LED 与后续扩展

| 文档 | 位置 | 内容概括 | 使用场景 |
| --- | --- | --- | --- |
| Raspberry Pi 项目配置与 LED 接入交接文档 | `hardware/raspberry_pi/PI_PROJECT_LED_HANDOFF.md` | 汇总 Pi 当前运行环境、虚拟环境依赖、正式融合链路、LED 控制器位置和后续 `led_command` 接入建议。 | 后续接入 WS2812B LED 灯带或灯板。 |

## 5. 快速查找

| 目标 | 优先查看 |
| --- | --- |
| 想跑完整链路验证 | `hardware/END_TO_END_TRANSMISSION_VERIFICATION.md` |
| 想做现场链路测试（交接流程） | `hardware/LIVE_TEST_RUNBOOK.md` |
| 想部署或重启 `pi-fusion` | `hardware/FUSION_PIPELINE_DEPLOY.md` |
| 想看 PC 是否收到 Pi 数据 | `hardware/END_TO_END_TRANSMISSION_VERIFICATION.md`、`hardware/PI_BACKEND_COMMUNICATION_PLAN.md` |
| 想烧录或调整 micro:bit | `hardware/microbit/microbit_to_pi/README.md` |
| 想配置或重新上传 ESP32 | `hardware/esp32/microbit_ble_wifi_gateway/README.md` |
| 想验证 micro:bit 预览页面 | `hardware/microbit/microbit_to_pi/MICROBIT_VISUAL_VERIFICATION.md` |
| 想验证摄像头预览页面 | `hardware/raspberry_pi/camera_to_Pi/CAMERA_PREVIEW_AND_FUSION.md` |
| 想同时看摄像头、micro:bit 和发送前融合数据 | `hardware/fusion_pipeline/FUSION_LIVE_PREVIEW.md` |
| 想确认训练数据字段 | `hardware/raspberry_pi/MICROBIT_ESP32_CAMERA_DATA_FLOW.md`、`hardware/PI_BACKEND_COMMUNICATION_PLAN.md` |
| 想接 LED 灯带 | `hardware/raspberry_pi/PI_PROJECT_LED_HANDOFF.md` |
| 想确认目录结构 | `hardware/PROJECT_STRUCTURE.md` |
| 想看硬件侧当前待办（采样率/ESP32/LED） | `hardware/HARDWARE_TASKS.md` |

## 6. 维护规则

后续维护 `hardware/` 文档时按以下规则同步更新本文档：

1. 新增 `.md` 文档后，在对应主题表格中加入路径和用途。
2. 删除或移动 `.md` 文档后，移除或修正对应索引项。
3. 文档主题发生变化后，更新“内容概括”和“使用场景”。
4. 正式链路、端口、IP、虚拟环境、验证命令发生变化后，同时更新本文档和相关专项文档。
5. 旧方案文档必须明确标注“历史归档”或“不属于当前正式链路”。
