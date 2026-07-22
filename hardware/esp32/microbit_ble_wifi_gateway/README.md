# ESP32 micro:bit BLE-to-Wi-Fi 网关

本目录提供 ESP32 网关固件。目标是让 ESP32 负责连接两块 micro:bit 的 BLE UART，树莓派只通过 UDP 接收数据，从而绕过树莓派板载 Bluetooth/BlueZ 在双 GATT 连接下不稳定的问题。

数据链路：

```text
left micro:bit  --BLE UART Notify-->  ESP32
right micro:bit --BLE UART Notify-->  ESP32
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
5. 选择你的开发板。常见 ESP32 DevKit 可先选 `Tools > Board > ESP32 Arduino > ESP32 Dev Module`。
6. 选择 ESP32 对应串口。

## 修改网关参数

打开：

```text
MicrobitBleWifiGateway/MicrobitBleWifiGateway.ino
```

修改以下字段：

```cpp
static const char* WIFI_SSID = "CHANGE_ME";
static const char* WIFI_PASSWORD = "CHANGE_ME";

static const IPAddress PI_HOST(192, 168, 43, 221);
static const uint16_t PI_UDP_PORT = 17778;

static const char* LEFT_MICROBIT_ADDRESS = "E7:C8:C1:AF:21:46";
static const char* RIGHT_MICROBIT_ADDRESS = "FD:15:9A:47:7F:8F";
```

当前已验证的 micro:bit 地址：

```text
left  = E7:C8:C1:AF:21:46
right = FD:15:9A:47:7F:8F
```

micro:bit 固件仍使用现有 MakeCode 程序，不需要改协议。ESP32 订阅的 Notify UUID 是：

```text
6e400002-b5a3-f393-e0a9-e50e24dcca9e
```

## UDP 网关帧

ESP32 不解析业务字段，只把 micro:bit 原始二进制包包进一个很小的 UDP 帧：

```text
offset  size  field
0       4     magic = "MBGW"
4       1     version = 1
5       1     header_len = 18
6       1     payload_len = 11 or 17
7       1     flags = 0
8       4     gateway_sequence, uint32 little-endian
12      4     esp_rx_micros, uint32 little-endian
16      1     conn_index, 0=left configured link, 1=right configured link
17      1     BLE RSSI, int8
18      N     original micro:bit packet
```

Pi 端用 `esp32_gateway_receiver` 解析这个帧，再复用原有 micro:bit 协议解析器输出 JSON Lines。

## 串口日志

上传后打开 Arduino Serial Monitor，波特率设为 `115200`。正常会看到：

```text
Wi-Fi connected: 192.168.x.x
BLE gateway started
[left] subscribed, rssi=-...
[right] subscribed, rssi=-...
gateway seq=...
```

如果只看到反复 `connect failed`，先确认：

- micro:bit 已烧录 no-pairing BLE 固件；
- micro:bit 屏幕显示 `L` / `R`，没有被 MakeCode Web Bluetooth、手机或树莓派旧 receiver 占用；
- ESP32 和 micro:bit 保持 30 cm 到 1 m 距离；
- Pi 上 UDP receiver 已经启动，但即使没启动也不影响 ESP32 先完成 BLE 连接。
