# 第三块 micro:bit Radio/USB 网关部署与回退

**更新时间**：2026-07-24  
**当前状态**：已部署到树莓派并作为 `pi-fusion` 默认 micro:bit 输入链路。

## 1. 当前架构

```text
左手 micro:bit（47 ms）─┐
                        ├─ MakeCode Radio group 79
右手 micro:bit（53 ms）─┘
                                 ↓
第三块 micro:bit 网关（Radio 接收）
                                 ↓ USB CDC, 115200
RadioSerialAdapter
                                 ↓
原协议解析 → 序号跟踪 → 降噪滤波 → FusionEngine
                                 ↑
                     摄像头 + MediaPipe
                                 ↓
                  TCP JSON Lines → PC 后端
```

本次没有修改摄像头采集、MediaPipe、降噪算法、时间对齐算法、融合输出结构、
LED 下行或 PC 后端协议。

每个传感样本通过 Radio 发送两次，间隔 `15 ms`。Pi 的序号跟踪器会丢弃
重复副本，因此滤波、融合和 PC 后端仍只看到一个逻辑样本。

## 2. 关键文件

| 位置 | 作用 |
| --- | --- |
| `hardware/microbit/microbit_to_pi/main.ts` | 左右手 Radio 发送固件 |
| `hardware/microbit/microbit_to_pi/pxt.json` | 左右手 MakeCode 工程 |
| `hardware/microbit/microbit_radio_gateway/main.ts` | 第三块网关固件 |
| `hardware/fusion_pipeline/radio_serial_adapter.py` | Pi USB 串口输入 |
| `hardware/fusion_pipeline/gateway_adapter.py` | 共用解析、去重、滤波处理 |
| `hardware/fusion_pipeline/main.py` | 按配置选择 ESP32 或 USB 网关 |
| `hardware/fusion_pipeline/config.yaml` | 当前传输方式与串口路径 |
| `hardware/fusion_pipeline/pi-fusion.service` | 正式 systemd 服务 |
| `hardware/fusion_pipeline/test_radio_serial_adapter.py` | 新传输层测试 |

## 3. 当前设备标识

树莓派网关稳定路径：

```text
/dev/serial/by-id/usb-ARM_BBC_micro:bit_CMSIS-DAP_9900000043114e45006590030000006a0000000097969901-if01
```

它指向 `/dev/ttyACM0`。配置必须使用 `/dev/serial/by-id/...`，不要直接依赖
可能随插拔变化的 `/dev/ttyACM0`。

左右手当前映射：

| 手别 | DAPLink 唯一 ID 尾段 | Radio 序列号 |
| --- | --- | --- |
| 左手 | `e15b1fe8a20608ea` | `-1944233693` |
| 右手 | `6a0e2f5b8fe408e9` | `-349312960` |

## 4. 网关串口协议

启动：

```text
GW1,READY,79
```

数据：

```text
GW1,<gateway_rx_ms>,<rssi_dbm>,<sender_serial>,<payload_hex>
```

Pi 在收到完整串口行时立即记录 `pi_rx_monotonic_ns`。`gateway_rx_ms` 用于链路
诊断，融合仍使用 Pi 单调时钟，不会把网关板的独立时钟直接当作全局时钟。

## 5. 启动与预览

```bash
sudo systemctl restart pi-fusion
systemctl is-active pi-fusion
sudo journalctl -u pi-fusion -f
```

正常日志至少包括：

```text
RadioSerialAdapter starting on /dev/serial/by-id/...
Radio gateway serial connected
Camera started
Fusion Pipeline started
```

PC 浏览器访问：

```text
http://192.168.43.221:8790/
```

页面同时展示摄像头、左右手原始数据、滤波数据和即将发往 PC 的融合数据，
不会再次占用摄像头或串口。

旧版双手独立界面也可作为只读页面运行：

```bash
bash hardware/microbit/microbit_to_pi/tools/start_radio_preview.sh
```

访问 `http://192.168.43.221:8787/`。该页面从 `8790/state` 获取数据，不再启动
ESP32 UDP 接收器，因此可以与 `pi-fusion` 同时运行。

## 6. 快速检查

```bash
curl -s http://127.0.0.1:8790/state
```

重点检查：

- `latest_raw_microbits.left/right` 均存在；
- `transport` 为 `microbit_radio_usb`；
- `latest_filtered_microbits` 序号持续增长；
- `ages_ms.raw_microbit` 不持续增大；
- `tcp_status.pc_connected` 为 `true`；
- `tcp_status.queued_messages` 不持续增长；
- `latest_outbound.microbits[]` 同时包含左右手数据。

## 7. 实机验收结果

最终参数为左手 `47 ms`、右手 `53 ms`，每个样本发送两次、间隔 `15 ms`。
服务重启后的 35 秒观测结果：

| 指标 | 结果 |
| --- | --- |
| Radio 原始副本 | `2956` |
| 去重后逻辑样本 | `1555` |
| 左手累计缺口 | `0` |
| 右手累计缺口 | `1` |
| 逻辑缺口率 | 约 `0.064%` |
| 左右手融合可用 | 均为 `true` |
| 当前最大时间差 | `42.1 ms` |
| PC TCP | 已连接 |
| TCP 队列/发送丢弃 | `0 / 0` |

该结果验证了重复副本由 Pi 序号跟踪器正确过滤，摄像头融合和 PC 后端发送未因
传输方式切换而中断。按键协议、七次重复和 Pi 去重已通过单元测试；现场按键
语义仍建议在佩戴状态下各触发一次完成交互验收。

## 8. ESP32/BLE 回退基线

PC 原方案 Git 提交：

```text
a8fcb6e16a7d7dd5ba9482fb2ac4112e5ff31e26
```

树莓派完整回退快照：

```text
/home/ag1_client/aiot_conductor/backups/esp32_ble_20260724_1640/
```

快照包含：

- `hardware/microbit/`
- `hardware/esp32/`
- `hardware/fusion_pipeline/`
- `pi-fusion.service`
- `SHA256SUMS`

## 9. 回退到 ESP32

1. 将左右手重新烧录 Git 提交 `a8fcb6e` 中的 BLE `main.ts`。
2. 确认 ESP32 固件和 Wi-Fi 配置正常。
3. 将当前配置改为：

```yaml
gateway:
  transport: "esp32_udp"
```

4. 重启服务：

```bash
sudo systemctl restart pi-fusion
```

如需完整文件级恢复，可从树莓派回退快照复制原目录。恢复前先停止
`pi-fusion`，恢复后执行 `sudo systemctl daemon-reload` 并重新启动。

## 10. 故障处理

| 现象 | 检查与处理 |
| --- | --- |
| `Cannot open Radio gateway` | 检查 USB、电源和 `ls -l /dev/serial/by-id/` |
| 只有一只手刷新 | 核对左右手 `HAND` 值、Radio 组和板卡唯一 ID |
| 一侧持续 `sequence_gap` | 检查是否仍为相同发送周期；当前应为左 47 ms、右 53 ms |
| 串口解析错误增加 | 重插网关，确认网关固件输出 `GW1` 行且没有其他程序占用串口 |
| micro:bit 正常但融合不可用 | 检查 `max_age_ms` 和预览中的 `time_delta_ms` |
| 摄像头不可用 | 与 Radio 链路无直接关系，检查 camera 日志和设备权限 |
| PC 未收到数据 | 检查 `tcp_status`、PC 后端端口 `9000` 和网络地址 |
