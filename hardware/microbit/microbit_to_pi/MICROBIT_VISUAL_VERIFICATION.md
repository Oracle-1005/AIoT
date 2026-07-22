# micro:bit 到树莓派 BLE 数据可视化验证说明

本文档用于验证 `micro:bit -> Raspberry Pi` 的 BLE 数据链路是否正常。验证目标不是只看到终端 JSON，而是通过浏览器页面直观看到姿态、加速度、序号和控制事件是否随 micro:bit 动作实时变化。

## 当前实测状态

截至 2026-07-22，树莓派 `AG1` 上已验证的正式接收配置为：

```json
{
  "tx_characteristic_uuid": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
  "sensor_queue_size": 512,
  "event_dedup_ttl_seconds": 10.0,
  "devices": [
    {"hand": "left", "address": "E7:C8:C1:AF:21:46"},
    {"hand": "right", "address": "FD:15:9A:47:7F:8F"}
  ]
}
```

预览页面已验证可从电脑浏览器打开：

```text
http://192.168.43.221:8787/
http://AG1:8787/
```

如果只想确认预览服务是否连到接收流，可在电脑端执行：

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://192.168.43.221:8787/health
```

正常响应应包含 `"ok": true`，且 `latest` 字段中有最近的 `microbit_sensor_state`。当前实测已返回左手样本：`source="left"`、`hand=0`，并包含 `raw.ax_mg/ay_mg/az_mg`、`pitch_deg` 和 `roll_deg`。

## 文件位置

micro:bit 相关代码统一放在：

```text
hardware/microbit/microbit_to_pi/
  main.ts                         MakeCode TypeScript 固件源码
  pxt.json                         MakeCode 项目配置，包含 no-pairing BLE 配置
  README.md                        协议和基础运行说明
  MICROBIT_VISUAL_VERIFICATION.md  本可视化验证说明
  tools/live_preview_server.py     浏览器实时预览服务
```

树莓派接收端仍放在：

```text
hardware/raspberry_pi/microbit_to_Pi/
  microbit_receiver/               BLE 接收、协议解析、队列分流
  config.example.json              接收端配置模板
```

这样分工是为了保留硬件侧结构：`hardware/microbit/` 管 micro:bit 固件和验证工具，`hardware/raspberry_pi/` 管运行在树莓派上的接收服务。

## 一、烧录 micro:bit 固件

当前已验证的 MakeCode 项目配置在 `pxt.json` 中。关键点是：

```json
"microbit-dal": {
  "bluetooth": {
    "open": 1,
    "pairing_mode": 0,
    "whitelist": 0
  }
}
```

这会生成无需配对的 BLE 固件，避免树莓派端因为旧配对缓存、白名单或安全模式导致扫描得到但 GATT 连接失败。

烧录左手 micro:bit 时保持：

```typescript
const HAND: number = 0
```

如果后续烧录右手 micro:bit，把 `main.ts` 中该值临时改为：

```typescript
const HAND: number = 1
```

右手板当前已验证过一次 DAPLink 拖拽烧录异常：普通复制到 `MICROBIT` 盘符会生成 `ASSERT.TXT`，位置为 `source/daplink/drag-n-drop/file_stream.c:164`。可行处理方式是清除 `ASSERT.TXT` 后，用 pyOCD 通过 CMSIS-DAP 调试接口烧录：

```powershell
python -m pyocd commander -t nrf52833 --probe 99063602000528206a0e2f5b8fe408e9000000006e052820 -c unlock -c reset -c exit
python -m pyocd flash -t nrf52833 -e chip -f 1000000 -M under-reset --probe 99063602000528206a0e2f5b8fe408e9000000006e052820 hardware\microbit\microbit_to_pi\built\mbcodal-binary.hex
```

烧录完成后应把仓库中的 `main.ts` 恢复为默认模板值 `HAND=0`，避免后续左手固件误烧成右手。

## 二、准备树莓派接收端配置

在树莓派上进入接收端目录：

```bash
cd ~/aiot_conductor/project/microbit_to_Pi
cp config.example.json config.json
```

把 `config.json` 中的 `devices` 改成实测扫描到的 micro:bit 地址或完整名称。例如当前已验证的左右双板：

```json
{
  "tx_characteristic_uuid": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
  "sensor_queue_size": 512,
  "event_dedup_ttl_seconds": 10.0,
  "devices": [
    {"hand": "left", "address": "E7:C8:C1:AF:21:46"},
    {"hand": "right", "address": "FD:15:9A:47:7F:8F"}
  ]
}
```

注意：MakeCode UART 在树莓派 BlueZ/Bleak 下实测应订阅 `6e400002-b5a3-f393-e0a9-e50e24dcca9e`。`6e400003...` 是写入端，不适合作为 `start_notify()` 目标。

## 三、启动浏览器实时预览页面

把本目录中的预览脚本同步到树莓派后，在树莓派运行：

```bash
cd ~/aiot_conductor/project
camera_to_Pi/.venv/bin/python \
  ~/aiot_conductor/project/hardware/microbit/microbit_to_pi/tools/live_preview_server.py \
  --receiver-dir ~/aiot_conductor/project/microbit_to_Pi \
  --config config.json \
  --python ~/aiot_conductor/project/camera_to_Pi/.venv/bin/python \
  --host 0.0.0.0 \
  --port 8787
```

如果你的仓库没有同步到 `~/aiot_conductor/project/hardware/...`，也可以直接把 `tools/live_preview_server.py` 拷贝到树莓派任意目录运行；只要 `--receiver-dir` 指向 `microbit_to_Pi` 接收端目录即可。

在电脑浏览器打开：

```text
http://AG1:8787/
```

如果 `AG1` 不能解析，改用树莓派 IP：

```bash
hostname -I
```

然后打开：

```text
http://树莓派IP:8787/
```

预览服务启动后会同时启动一个 `microbit_receiver.app` 子进程。不要再并行启动第二个 receiver，否则同一个 micro:bit 会被多个 BLE central 竞争连接。需要检查或停止时：

```bash
ps -ef | grep -E 'live_preview_server|microbit_receiver.app' | grep -v grep
kill "$(cat /tmp/microbit_preview.pid)"
```

## 四、页面上应该看到什么

页面正常时会出现以下变化：

- 顶部状态从 `waiting for samples` 变为 `live`。
- 中间 micro:bit 姿态块会随着你倾斜板子改变 pitch/roll。
- `ax/ay/az` 三条横向条会随着移动和旋转变化。
- 折线图会持续刷新，显示最近的 `pitch`、`roll`、`az`。
- `sequence` 会持续递增。
- `age` 通常应低于 1200 ms；如果持续变大，说明数据流暂停或连接中断。
- 按键事件会出现在“最近控制事件”区域。

左手固件的控制事件映射：

| 操作 | event_code | mapped_candidate |
| --- | --- | --- |
| A 短按 | `A_SHORT_PRESS` | `start_or_resume` |
| B 短按 | `B_SHORT_PRESS` | `pause` |
| A+B 长按 | `AB_LONG_PRESS` | `recalibrate` |

右手固件的控制事件映射：

| 操作 | event_code | mapped_candidate |
| --- | --- | --- |
| A 短按 | `A_SHORT_PRESS` | `style_switch` |
| B 长按 | `B_LONG_PRESS` | `emergency_stop` |
| A+B 长按 | `AB_LONG_PRESS` | `recalibrate` |

## 五、命令行快速验证

如果不需要网页，只想确认 receiver 是否有数据：

```bash
cd ~/aiot_conductor/project/microbit_to_Pi
../camera_to_Pi/.venv/bin/python -m microbit_receiver.app \
  --config config.json \
  --log-level INFO
```

正常输出示例：

```json
{"type":"microbit_sensor_state","source":"left","message_type":1,"hand":0,"sample_sequence":13986,"device_timestamp_ms":560342,"raw":{"ax_mg":32,"ay_mg":176,"az_mg":-1040,"pitch_deg":9,"roll_deg":1},"time_alignment":null}
```

## 六、常见问题

1. 扫描得到设备但无法连接：先停止电脑、手机或浏览器 MakeCode 对 micro:bit 的连接，然后在树莓派执行 `bluetoothctl remove <address>`，必要时重启 `bluetooth` 服务。
2. 页面能打开但一直没有数据：检查 `config.json` 地址是否为当前 micro:bit 地址，且 `tx_characteristic_uuid` 是否为 `...0002`。
3. 只有日志没有姿态变化：说明 receiver 启动了但没有收到 sensor_state，优先检查 micro:bit 是否已烧录本目录的 no-pairing 固件。
4. 左右手事件被拒绝：检查 `main.ts` 中 `HAND` 和 `config.json` 中 `hand/address` 是否对应。
5. 数据偶尔出现 `sequence_gap`：短时间 BLE 抖动可以接受；若持续出现，需要缩短距离、减少 2.4 GHz 干扰，或降低发送频率。
6. `le-connection-abort-by-local`：树莓派能看到 micro:bit 广播，但 BlueZ 在 GATT 连接阶段主动中止。先按 micro:bit 背面 reset，使屏幕重新显示 `L` 或 `R`；再重启预览服务。若双板长期不稳定，优先使用 5 GHz/有线网络或外置 USB BLE 适配器。

### az_mg 如何理解

`az_mg` 是 micro:bit 板子 Z 轴方向的加速度，单位是 milli-g，且包含重力。它不是高度、速度或垂直位移。静止时三轴合成模长通常接近 `1000 mg`；如果板子平放，重力主要会体现在 `az_mg` 上，正负号取决于板子朝向。判断动作强度时应看 `sqrt(ax_mg^2 + ay_mg^2 + az_mg^2)` 相对 `1000 mg` 的偏离；若需要纯运动加速度，需要后续滤波/姿态估计模块先扣除重力分量。

## 七、连接不稳定时的处理

如果日志中大量出现：

```text
failed to discover services, device disconnected
[org.bluez.Error.InProgress] In Progress
```

优先按以下顺序处理：

1. 确认同一时间只运行一个 BLE 接收程序。不要同时运行命令行 receiver、预览服务、旧测试脚本或 MakeCode 蓝牙连接。
2. 停止预览服务：

   ```bash
   kill "$(cat /tmp/microbit_preview.pid)"
   ```

   如果 PID 文件不存在，再用：

   ```bash
   ps -ef | grep -E 'live_preview_server|microbit_receiver.app'
   ```

   找到 PID 后手动 `kill`。

3. 清理 BlueZ 状态：

   ```bash
   sudo systemctl restart bluetooth
   bluetoothctl remove E7:C8:C1:AF:21:46
   ```

4. 按一下 micro:bit 背面的 reset，等待屏幕重新显示 `L` 或 `R`。
5. 重新启动预览服务。

当前固件默认采样周期是 `100 ms`，即 10 Hz。此前 25 Hz 在 micro:bit BLE UART 上更容易触发服务发现失败、短连后断开和 BlueZ `InProgress`。如果后续需要提高采样率，建议先试 15 Hz，再试 20 Hz，并用预览页观察 `age` 和 `sequence_status`。

硬件摆放也会明显影响稳定性：

- micro:bit 与树莓派不要贴在一起，建议保持 30 cm 到 1 m 距离；RSSI 长期高于约 `-20 dBm` 时可能过强。
- 树莓派如果同时用 2.4 GHz Wi-Fi 联网，BLE 稳定性会下降；优先使用 5 GHz Wi-Fi、以太网，或给树莓派接一个 USB BLE 适配器并让它远离主板。
- 不要把 micro:bit 放在树莓派金属散热片、USB 线缆堆或电脑机身旁边。

## 八、与后续 camera 和 PC 链路的关系

预览服务只用于验证，不改变正式数据接口。正式链路仍然从 `microbit_receiver.app` 输出 JSON Lines：

- sensor_state 用于后续和 Pi camera 帧做时间同步；
- control_event 应走高优先级路径，尤其是 `emergency_stop`；
- `pi_rx_monotonic_ns` 是树莓派收到 BLE Notify/Indicate 时记录的单调时钟，可和摄像头帧时间戳做对齐；
- `time_alignment` 当前保留为 `null`，后续融合模块写入同步结果。
