# ESP32 micro:bit BLE 广播转 Wi-Fi 网关

本目录提供 ESP32 网关固件。当前推荐方案是不再让 ESP32 或树莓派主动连接 micro:bit，而是让两块 micro:bit 周期性发送 BLE 广播包，ESP32 只负责扫描广播并通过 UDP 转发给树莓派。

这样可以绕过双 micro:bit BLE GATT 连接中的常见不稳定问题：随机地址变化、配对状态残留、连接被本地中止、同一块板被其他主机占用，以及 ESP32/BlueZ 同时维持两个连接时的重连抖动。

数据链路：

```text
left micro:bit  --BLE advertising / Eddystone UID-->  ESP32
right micro:bit --BLE advertising / Eddystone UID-->  ESP32
ESP32 --UDP/Wi-Fi--> Raspberry Pi
Raspberry Pi --JSON Lines--> preview / fusion / PC
```

## Arduino IDE 配置

1. 打开 Arduino IDE。
2. 在 `File > Preferences > Additional Boards Manager URLs` 添加 Espressif 稳定版地址：

   ```text
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```

   如果 GitHub 下载很慢，可使用 Espressif 提供的中国镜像：

   ```text
   https://jihulab.com/esp-mirror/espressif/arduino-esp32/-/raw/gh-pages/package_esp32_index_cn.json
   ```

3. 打开 `Tools > Board > Boards Manager...`，搜索 `esp32`，安装 `esp32 by Espressif Systems`。
4. 打开 `Tools > Manage Libraries...`，搜索并安装 `NimBLE-Arduino`。
5. 常见 ESP32 DevKit 可先选 `Tools > Board > ESP32 Arduino > ESP32 Dev Module`。
6. 选择 ESP32 对应串口后编译上传。

命令行 Arduino CLI 也可以使用，推荐先编译再上传：

```powershell
& 'C:\Program Files\Arduino CLI\arduino-cli.exe' --config-file C:\ArduinoCLI\arduino-cli.yaml compile --fqbn esp32:esp32:esp32 --build-path C:\ArduinoBuild\MicrobitBleWifiGateway C:\ArduinoSketches\MicrobitBleWifiGateway
& 'C:\Program Files\Arduino CLI\arduino-cli.exe' --config-file C:\ArduinoCLI\arduino-cli.yaml upload -p COM10 --fqbn esp32:esp32:esp32 --input-dir C:\ArduinoBuild\MicrobitBleWifiGateway C:\ArduinoSketches\MicrobitBleWifiGateway
```

## 修改网关参数

打开：

```text
MicrobitBleWifiGateway/MicrobitBleWifiGateway.ino
```

按现场网络修改：

```cpp
static const char* WIFI_SSID = "CHANGE_ME";
static const char* WIFI_PASSWORD = "CHANGE_ME";

static const IPAddress PI_HOST(192, 168, 43, 221);
static const uint16_t PI_UDP_PORT = 17778;
```

当前广播方案不需要填写 micro:bit 蓝牙地址，不需要配对，也不需要记录 `BBC micro:bit [xxxxx]` 名称。左右手身份由 micro:bit 数据包里的 `HAND` 字段决定：

- `HAND = 0`：左手；
- `HAND = 1`：右手。

## micro:bit 广播负载

micro:bit 使用 MakeCode `bluetooth.advertiseUidBuffer()` 发送 Eddystone UID 广播。由于广播载荷空间有限，micro:bit 先把原始项目协议压缩为 16 字节，ESP32 收到后再还原为树莓派已支持的 17 B 状态包或 11 B 控制包。

紧凑状态包：

```text
offset  size  field
0       1     compact_type = 0xa1
1       1     original micro:bit header
2       2     sequence, uint16 little-endian
4       4     device_timestamp_ms, uint32 little-endian
8       2     ax_mg, int16 little-endian
10      2     ay_mg, int16 little-endian
12      2     az_mg, int16 little-endian
14      1     pitch_deg, int8
15      1     roll_deg, int8
```

紧凑控制包：

```text
offset  size  field
0       1     compact_type = 0xa2
1       1     original micro:bit header
2       2     sequence, uint16 little-endian
4       4     device_timestamp_ms, uint32 little-endian
8       1     event_code
9       1     priority
10      1     repeat_index
11      1     repeat_total
12      4     reserved / guard bytes
```

## UDP 网关帧

ESP32 将还原后的 micro:bit 原始包包进 UDP 帧：

```text
offset  size  field
0       4     magic = "MBGW"
4       1     version = 1
5       1     header_len = 18
6       1     payload_len = 11 or 17
7       1     flags = 1, advertising source
8       4     gateway_sequence, uint32 little-endian
12      4     esp_rx_micros, uint32 little-endian
16      1     conn_index, 0 = left, 1 = right
17      1     BLE RSSI, int8
18      N     restored original micro:bit packet
```

Pi 端继续使用 `esp32_gateway_receiver` 解析这个帧，再复用原有 micro:bit 协议解析器输出 JSON Lines。业务上的 left/right 仍以原始 micro:bit packet 里的 hand 字段为准。

## 串口日志

上传后打开 Arduino Serial Monitor，波特率设为 `115200`。正常会看到：

```text
BLE advertising gateway started
Connecting Wi-Fi SSID=...
Wi-Fi connected: 192.168.x.x
gateway seq=8 wifi=up mode=advertising
  [left] age_ms=1795 rssi=-55 last_sensor_seq=931
  [right] age_ms=80 rssi=-56 last_sensor_seq=881
```

`age_ms` 表示 ESP32 距离上次收到该侧 micro:bit 广播的时间。短时间升到几百毫秒或几秒是广播链路的正常现象，只要左右两侧持续刷新、`gateway seq` 持续增长，链路就是可用的。

当前 micro:bit 广播参数为：

```text
sensor sample period = 150 ms
sensor repeat total = 1
sensor repeat interval = 50 ms
control event repeat total = 7
control event repeat interval = 90 ms
control hold window = 70 ms
```

状态样本依靠 BLE 广播层在广告间隔内自然重复；micro:bit 程序不再对同一状态样本额外调用第二次 `advertiseUidBuffer()`，避免额外调用拉长实际采样间隔。ESP32 仍按左右手和 `sample_sequence` 去重，只把第一次成功收到的样本转发到树莓派。按键事件会重复广播更多次，并在每次事件广播后短暂保持控制包，避免马上被状态包覆盖。

ESP32 当前扫描参数为连续扫描窗口：

```cpp
scan->setScanCallbacks(&scanCallbacks, true);
scan->setActiveScan(false);
scan->setDuplicateFilter(false);
scan->setInterval(45);
scan->setWindow(45);
```

## 树莓派验证

独立验证会占用 UDP `17778`，如果正式融合服务正在运行，先停止：

```bash
sudo systemctl stop pi-fusion 2>/dev/null || true
```

在树莓派上进入项目虚拟环境后运行：

```bash
cd ~/aiot_conductor/project/hardware/raspberry_pi/esp32_ble_gateway_to_Pi
source ~/aiot_conductor/project/camera_to_Pi/.venv/bin/activate
python -m esp32_gateway_receiver.app --config config.json --log-level WARNING
```

正常输出会包含左右手 JSON：

```json
{"type":"microbit_sensor_state","source":"left","gateway":{"flags":1,"conn_index":0}}
{"type":"microbit_sensor_state","source":"right","gateway":{"flags":1,"conn_index":1}}
```

如果看到 `sequence_gap`，通常表示某些 BLE 广播包没有被 ESP32 扫到。这不同于连接失败，广播本身就是无确认、可丢包的链路。需要降低缺口时，优先尝试：

- micro:bit 与 ESP32 保持 30 cm 到 1 m 距离；
- 两块 micro:bit 不要贴在一起，避免同频遮挡；
- 若丢包偏高，先在 `SAMPLE_PERIOD_MS = 150`、`SENSOR_REPEAT_TOTAL = 1` 的当前配置下观察，再决定是否回退到 200 ms 或调整事件/状态策略；
- ESP32 使用 2.4 GHz Wi-Fi 时尽量靠近路由器，避免反复重连；
- 后续若需要更强可靠性，可改为 ESP-NOW、nRF24、串口无线模块，或在协议层增加重复广播。

## 与正式融合服务一起验证

确认独立接收正常后，关闭独立 receiver 或 `8787` 预览，再启动正式融合服务：

```bash
pkill -f esp32_gateway_receiver.app 2>/dev/null || true
pkill -f live_preview_server.py 2>/dev/null || true
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -f
```

PC 后端启动后，在 PC PowerShell 运行：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 30
```

通过标准：

- `pi_connected=yes`
- `status` 计数持续增加
- `fused_frame` 计数持续增加
- 左右 micro:bit 的 `age_ms` 周期性刷新
- 按键后 `control_event` 计数增加
