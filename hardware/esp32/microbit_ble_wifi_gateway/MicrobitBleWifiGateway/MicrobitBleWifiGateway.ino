/*
  ESP32 BLE-to-Wi-Fi gateway for two micro:bit boards.

  - ESP32 acts as BLE central.
  - It subscribes to the MakeCode Nordic UART TX/Notify characteristic on each
    micro:bit.
  - Each 17 B sensor_state or 11 B control_event packet is wrapped in a small
    binary UDP frame and sent to the Raspberry Pi.

  Install in Arduino IDE:
  - Boards Manager: esp32 by Espressif Systems
  - Library Manager: NimBLE-Arduino
*/

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "MicrobitBleWifiGatewayTypes.h"

// ------------------------- User configuration -------------------------

static const char* WIFI_SSID = "CHANGE_ME";
static const char* WIFI_PASSWORD = "CHANGE_ME";

static const IPAddress PI_HOST(192, 168, 43, 221);
static const uint16_t PI_UDP_PORT = 17778;

static const char* LEFT_MICROBIT_ADDRESS = "E7:C8:C1:AF:21:46";
static const char* RIGHT_MICROBIT_ADDRESS = "FD:15:9A:47:7F:8F";

// micro:bit MakeCode UART Service UUIDs.
static NimBLEUUID UART_SERVICE_UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e");
static NimBLEUUID UART_TX_NOTIFY_UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e");

// ------------------------- Gateway UDP frame --------------------------

static const uint8_t GATEWAY_VERSION = 1;
static const uint8_t GATEWAY_HEADER_LEN = 18;
static const size_t MAX_MICROBIT_PACKET_LEN = 20;
static const size_t MAX_UDP_PACKET_LEN = GATEWAY_HEADER_LEN + MAX_MICROBIT_PACKET_LEN;

static_assert(MAX_UDP_PACKET_LEN <= 64, "gateway frame should stay small");

WiFiUDP udp;
uint32_t gatewaySequence = 0;

static void putU32LE(uint8_t* dst, uint32_t value) {
  dst[0] = value & 0xff;
  dst[1] = (value >> 8) & 0xff;
  dst[2] = (value >> 16) & 0xff;
  dst[3] = (value >> 24) & 0xff;
}

MicrobitLink links[] = {
  {"left", LEFT_MICROBIT_ADDRESS, 0, nullptr, nullptr, false, 0, 0, -127},
  {"right", RIGHT_MICROBIT_ADDRESS, 1, nullptr, nullptr, false, 0, 0, -127},
};

static void sendGatewayFrame(MicrobitLink* link, const uint8_t* data, size_t len) {
  if (len != 17 && len != 11) {
    Serial.printf("[%s] drop unexpected packet length: %u\n", link->label, (unsigned)len);
    return;
  }
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  uint8_t frame[MAX_UDP_PACKET_LEN] = {0};
  frame[0] = 'M';
  frame[1] = 'B';
  frame[2] = 'G';
  frame[3] = 'W';
  frame[4] = GATEWAY_VERSION;
  frame[5] = GATEWAY_HEADER_LEN;
  frame[6] = static_cast<uint8_t>(len);
  frame[7] = 0;  // flags, reserved for future use.
  putU32LE(frame + 8, gatewaySequence++);
  putU32LE(frame + 12, micros());
  frame[16] = link->connIndex;
  frame[17] = static_cast<uint8_t>(link->lastRssi);
  memcpy(frame + GATEWAY_HEADER_LEN, data, len);

  udp.beginPacket(PI_HOST, PI_UDP_PORT);
  udp.write(frame, GATEWAY_HEADER_LEN + len);
  udp.endPacket();
  link->lastPacketMs = millis();
}

static void onMicrobitNotify(
    MicrobitLink* link,
    NimBLERemoteCharacteristic*,
    uint8_t* data,
    size_t len,
    bool) {
  sendGatewayFrame(link, data, len);
}

class GatewayClientCallbacks : public NimBLEClientCallbacks {
 public:
  void onDisconnect(NimBLEClient* client, int reason) override {
    for (MicrobitLink& link : links) {
      if (link.client == client) {
        link.subscribed = false;
        link.notifyChar = nullptr;
        Serial.printf("[%s] disconnected, reason=%d\n", link.label, reason);
      }
    }
  }
};

static GatewayClientCallbacks clientCallbacks;

static void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }
  Serial.printf("Connecting Wi-Fi SSID=%s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWi-Fi connected: %s\n", WiFi.localIP().toString().c_str());
  udp.begin(0);
}

static bool connectMicrobit(MicrobitLink& link) {
  const uint32_t nowMs = millis();
  if (link.client != nullptr && link.client->isConnected() && link.subscribed) {
    return true;
  }
  if (nowMs - link.lastConnectAttemptMs < 5000) {
    return false;
  }
  link.lastConnectAttemptMs = nowMs;
  link.subscribed = false;

  Serial.printf("[%s] connecting %s\n", link.label, link.address);
  if (link.client == nullptr) {
    link.client = NimBLEDevice::createClient();
    link.client->setClientCallbacks(&clientCallbacks, false);
    link.client->setConnectTimeout(10);
  } else if (link.client->isConnected()) {
    link.client->disconnect();
  }

  NimBLEAddress address(link.address, BLE_ADDR_RANDOM);
  if (!link.client->connect(address)) {
    Serial.printf("[%s] connect failed\n", link.label);
    return false;
  }

  NimBLERemoteService* service = link.client->getService(UART_SERVICE_UUID);
  if (service == nullptr) {
    Serial.printf("[%s] UART service not found\n", link.label);
    link.client->disconnect();
    return false;
  }

  link.notifyChar = service->getCharacteristic(UART_TX_NOTIFY_UUID);
  if (link.notifyChar == nullptr || !link.notifyChar->canNotify()) {
    Serial.printf("[%s] UART TX notify characteristic not found\n", link.label);
    link.client->disconnect();
    return false;
  }

  MicrobitLink* linkPtr = &link;
  const bool ok = link.notifyChar->subscribe(
      true,
      [linkPtr](NimBLERemoteCharacteristic* characteristic,
                uint8_t* data,
                size_t len,
                bool isNotify) {
        onMicrobitNotify(linkPtr, characteristic, data, len, isNotify);
      });
  if (!ok) {
    Serial.printf("[%s] subscribe failed\n", link.label);
    link.client->disconnect();
    return false;
  }

  link.subscribed = true;
  link.lastRssi = static_cast<int8_t>(link.client->getRssi());
  Serial.printf("[%s] subscribed, rssi=%d\n", link.label, link.lastRssi);
  return true;
}

static void updateRssi() {
  static uint32_t lastRssiMs = 0;
  const uint32_t nowMs = millis();
  if (nowMs - lastRssiMs < 3000) {
    return;
  }
  lastRssiMs = nowMs;
  for (MicrobitLink& link : links) {
    if (link.client != nullptr && link.client->isConnected()) {
      link.lastRssi = static_cast<int8_t>(link.client->getRssi());
    }
  }
}

static void printHeartbeat() {
  static uint32_t lastPrintMs = 0;
  const uint32_t nowMs = millis();
  if (nowMs - lastPrintMs < 5000) {
    return;
  }
  lastPrintMs = nowMs;
  Serial.printf("gateway seq=%lu wifi=%s\n",
                static_cast<unsigned long>(gatewaySequence),
                WiFi.status() == WL_CONNECTED ? "up" : "down");
  for (const MicrobitLink& link : links) {
    const bool connected = link.client != nullptr && link.client->isConnected();
    Serial.printf("  [%s] connected=%d subscribed=%d age_ms=%lu rssi=%d\n",
                  link.label,
                  connected,
                  link.subscribed,
                  link.lastPacketMs == 0 ? 0 : static_cast<unsigned long>(nowMs - link.lastPacketMs),
                  link.lastRssi);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  connectWiFi();

  NimBLEDevice::init("microbit-wifi-gateway");
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);
  NimBLEDevice::setSecurityAuth(false, false, false);
  Serial.println("BLE gateway started");
}

void loop() {
  connectWiFi();
  for (MicrobitLink& link : links) {
    connectMicrobit(link);
  }
  updateRssi();
  printHeartbeat();
  delay(50);
}
