# 双 micro:bit → 树莓派数据链路代码 Demo

> 当前推荐实机链路：micro:bit v2 使用 BLE 广播发送数据，ESP32 扫描广播后通过 UDP 转发到树莓派。旧的“树莓派或 ESP32 同时连接两块 micro:bit BLE UART/GATT”方案仍保留在代码与文档中作为参考，但不再作为稳定性优先的默认方案。

本项目依据 `Microbit_to_Pi_v01.md` 实现：

- micro:bit：MakeCode TypeScript，采集三轴加速度、Pitch、Roll，完成按键防抖、长按和组合键判断；当前广播固件将数据压缩进 Eddystone UID 广播载荷；
- ESP32：扫描左右 micro:bit 广播，按 `HAND=0/1` 还原为项目原始 17 B/11 B 小端序二进制包，并通过 UDP 发给树莓派；
- 树莓派：接收 ESP32 UDP 网关帧，校验、解析、序号跟踪、控制事件去重，并分流到状态队列和优先控制队列；
- 输出：UTF-8 JSON Lines，方便后续时间同步、摄像头融合或发送到 PC。

## 目录

```text
microbit/
  main.ts              MakeCode 主程序；通过 HAND=0/1 区分左右腕
  pxt.json              MakeCode 项目依赖
  tools/                浏览器实时预览服务
  MICROBIT_VISUAL_VERIFICATION.md  可视化验证说明
raspberry_pi/
  config.example.json  双设备及 micro:bit -> Pi Notify/Indicate UUID 配置
  microbit_receiver/   协议、跟踪、BLE 接收和命令行入口
  tests/                无硬件协议单元测试
  tools/                本地示例包解析脚本
```

需要直观看到实时数据时，优先使用 `hardware/raspberry_pi/esp32_ble_gateway_to_Pi` 的 UDP receiver；旧版直连 BLE 预览仍可按 `MICROBIT_VISUAL_VERIFICATION.md` 启动 `tools/live_preview_server.py`。

## 当前 v2 广播方案状态

截至 2026-07-23，已在两块 micro:bit v2 上烧录广播固件：

- 左手：`HAND = 0`；
- 右手：`HAND = 1`；
- 采样周期：`SAMPLE_PERIOD_MS = 150`；
- 状态样本显式重复：`SENSOR_REPEAT_TOTAL = 1`；BLE 广播层会自然重复当前广告包，程序不再额外调用第二次状态广播；
- 按键事件重复：`EVENT_REPEAT_TOTAL = 7`，重复间隔 `EVENT_REPEAT_INTERVAL_MS = 90`，每次事件广播后保留 `CONTROL_HOLD_MS = 70` 的控制包窗口；
- 广播格式：Eddystone UID 载荷内的 16 B 紧凑包；
- ESP32 不连接、不配对、不依赖 micro:bit 地址，只扫描并解析广播。

树莓派端已验证能收到 ESP32 转发的左右手数据，输出中的 `gateway.flags = 1` 表示数据来自广播转发链路。广播是无确认链路，因此偶发 `sequence_gap` 属于正常现象；判断是否稳定应看左右两侧是否持续刷新，而不是要求每一个序号都完整到达。ESP32 会按 `sample_sequence` 过滤重复包，树莓派只看到第一次成功到达的样本。

## 当前实测地址与预览入口

截至 2026-07-22，树莓派 `AG1` 上正式 `microbit_to_Pi/config.json` 已更新为：

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

预览页面已验证可访问：

```text
http://192.168.43.221:8787/
http://AG1:8787/
```

健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://192.168.43.221:8787/health
```

正常返回包含 `"ok": true` 和 `latest.microbit_sensor_state`。如果日志出现 `le-connection-abort-by-local`，先确认没有第二个 receiver 占用 BLE，再按对应 micro:bit 背面 reset，使屏幕重新显示 `L` 或 `R`。

## 重要修正：MakeCode UART Notify UUID

本项目使用 MakeCode `bluetooth.startUartService()`。在树莓派 BlueZ/Bleak 实机枚举中，UART Service 的方向为：

| UUID 末尾 | 名称 | 方向与用途 |
| --- | --- | --- |
| `0002` | TX/Notify | micro:bit 通知/指示树莓派，树莓派应 `start_notify()` |
| `0003` | RX/Write | 树莓派写入 micro:bit |

因此树莓派默认订阅 `6e400002-b5a3-f393-e0a9-e50e24dcca9e`。代码仍将它放在配置文件中，方便实机发现服务后调整。

## 一、烧录两块 micro:bit

1. 打开 [MakeCode for micro:bit](https://makecode.microbit.org/)，新建项目。
2. 进入“扩展”，搜索并添加 `Bluetooth`。Bluetooth 与 Radio 会占用同一无线硬件，本项目不使用 Radio。
3. 切换到 JavaScript，把 `microbit/main.ts` 完整复制进去。
4. 烧录左腕前设置：

   ```typescript
   const HAND = 0
   ```

5. 复制一个 MakeCode 项目，烧录右腕前改成：

   ```typescript
   const HAND = 1
   ```

6. 上电后屏幕先显示 `L` 或 `R`。与树莓派连接成功显示勾，断开显示叉。

### micro:bit 端关键设计

- `input.acceleration()` 的单位本身就是 mg，无需再乘 1000；
- `input.rotation()` 返回角度，直接编码为 `int16`；
- 默认按 10 Hz 发送 `sensor_state`，优先保证树莓派 BlueZ/GATT 连接稳定；
- 采样时立即记录 `input.runningTime()`，序号也在采样时递增；
- 事件首包立即发送，最新状态包随后发送，再发送到期重复包；
- 状态发送暂时受阻时只保留最新样本，避免旧状态堆积；
- 右手 B 长按才映射紧急停止；左手 B 长按不会在释放后误触发暂停；
- A+B 一旦进入组合状态，直到两键全释放前都不会产生单键事件。

## 二、准备树莓派

```bash
sudo apt update
sudo apt install -y bluetooth bluez python3-venv
sudo systemctl enable --now bluetooth

cd raspberry_pi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

检查蓝牙适配器：

```bash
bluetoothctl show
bluetoothctl scan on
```

记录两块 micro:bit 的名称和地址。若当前 MakeCode Bluetooth 安全设置要求配对，可在 `bluetoothctl` 中依次执行：

```text
agent on
default-agent
pair AA:BB:CC:DD:EE:01
trust AA:BB:CC:DD:EE:01
```

另一块设备重复一次。配对过程中若 micro:bit 显示图案/数字，按设备提示确认。

## 三、配置并运行

```bash
cp config.example.json config.json
nano config.json
```

将左右设备地址替换为真实值。Linux 下若设备地址会变化，可删除 `address`，改用完整广播名称：

```json
{"hand": "left", "name": "BBC micro:bit [abcde]"}
```

启动：

```bash
microbit-receiver --config config.json --log-level INFO
```

将纯 JSON 数据保存到文件，同时仍在终端显示 BLE 日志：

```bash
microbit-receiver --config config.json > microbit_data.jsonl
```

`stdout` 只有 JSON，连接和错误日志走 `stderr`，不会污染数据文件。

## 四、无硬件测试

```bash
cd raspberry_pi
source .venv/bin/activate
pytest -q
python tools/make_demo_packets.py
```

测试覆盖：正确状态包、右手紧急停止、非法长度/保留位/手别、错误优先级、序号跳跃与回绕、事件重复与副本冲突。

## 五、树莓派输出字段

状态包在原文档字段之外增加：

- `sequence_status`：`first_sample`、`in_order`、`sequence_gap` 或 `device_restart`；
- `missing_sample_count`：序号缺口所表示的缺失样本数；
- `device_restarted`：是否检测到设备时间戳伴随序号明显回退。

控制事件只有首次有效副本进入 `control_queue`。队列项按 `priority` 从高到低取出；同一事件的第 2、3 份只记调试日志，不会再次执行。

## 六、接入后续时间同步/PC 传输

当前入口在：

```python
# raspberry_pi/microbit_receiver/app.py
async def consume_sensor(receiver): ...
async def consume_control(receiver): ...
```

后续可以在 `consume_sensor()` 中将 `device_timestamp_ms` 与 `pi_rx_monotonic_ns` 传给时间对齐模块，再把 `time_alignment` 从 `null` 替换为估计结果。紧急停止应继续保留在 `consume_control()` 的快速路径中，不等待滤波或摄像头融合。

## 七、常见问题

1. **提示找不到 `...0002` 或无法订阅**：确认配置使用 MakeCode UART Notify/Indicate 的 `...0002`，不要订阅只支持写入的 `...0003`。
2. **设备扫描得到但无法连接**：先停止其他电脑/手机对 micro:bit 的连接，再用 `bluetoothctl` 完成配对和信任。
3. **两边数据被拒绝为 hand 不一致**：检查左板 `HAND=0`、右板 `HAND=1`，以及 `config.json` 地址是否写反。
4. **强动作频繁达到约 ±4000 mg**：把 MakeCode 中 `AcceleratorRange.FourG` 改为 `AcceleratorRange.EightG`；树莓派校验已允许 ±8000 mg。
5. **10 Hz 稳定后希望测试更高频率**：把 `SAMPLE_PERIOD_MS` 从 100 改为 67（约 15 Hz）或 50（20 Hz），并观察序号缺口、页面 `age` 和 BLE 重连日志；不建议一开始直接回到 25 Hz 或 50 Hz。
