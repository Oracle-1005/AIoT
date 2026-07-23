/*
  ESP32 BLE-advertising-to-Wi-Fi gateway for two micro:bit boards.

  The ESP32 does not connect to micro:bit GATT services. It passively scans
  Eddystone UID advertisements produced by the MakeCode sender, expands the
  compact 16-byte advertising frame back to the existing project 17B/11B
  micro:bit protocol, and sends it to Raspberry Pi over UDP.
*/

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <WiFiUdp.h>

// ------------------------- User configuration -------------------------

static const char* WIFI_SSID = "CHANGE_ME";
static const char* WIFI_PASSWORD = "CHANGE_ME";

static const IPAddress PI_HOST(192, 168, 43, 221);
static const uint16_t PI_UDP_PORT = 17778;

// ------------------------- Advertising protocol -----------------------

static const uint8_t ADV_SENSOR = 0xa1;
static const uint8_t ADV_CONTROL = 0xa2;
static const NimBLEUUID EDDYSTONE_UUID("feaa");

// ------------------------- Gateway UDP frame --------------------------

static const uint8_t GATEWAY_VERSION = 1;
static const uint8_t GATEWAY_HEADER_LEN = 18;
static const size_t MAX_MICROBIT_PACKET_LEN = 20;
static const size_t MAX_UDP_PACKET_LEN = GATEWAY_HEADER_LEN + MAX_MICROBIT_PACKET_LEN;

static_assert(MAX_UDP_PACKET_LEN <= 64, "gateway frame should stay small");

WiFiUDP udp;
uint32_t gatewaySequence = 0;
bool udpStarted = false;

uint16_t lastSensorSeq[2] = {0xffff, 0xffff};
uint32_t lastControlKey[2] = {0xffffffff, 0xffffffff};
uint32_t lastPacketMs[2] = {0, 0};
int8_t lastRssi[2] = {-127, -127};

static void putU16LE(uint8_t* dst, uint16_t value) {
  dst[0] = value & 0xff;
  dst[1] = (value >> 8) & 0xff;
}

static void putU32LE(uint8_t* dst, uint32_t value) {
  dst[0] = value & 0xff;
  dst[1] = (value >> 8) & 0xff;
  dst[2] = (value >> 16) & 0xff;
  dst[3] = (value >> 24) & 0xff;
}

static uint16_t getU16LE(const uint8_t* src) {
  return static_cast<uint16_t>(src[0]) | (static_cast<uint16_t>(src[1]) << 8);
}

static uint32_t getU32LE(const uint8_t* src) {
  return static_cast<uint32_t>(src[0]) |
         (static_cast<uint32_t>(src[1]) << 8) |
         (static_cast<uint32_t>(src[2]) << 16) |
         (static_cast<uint32_t>(src[3]) << 24);
}

static uint8_t handFromHeader(uint8_t header) {
  return (header >> 2) & 0x01;
}

static void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!udpStarted) {
      udp.begin(0);
      udpStarted = true;
      Serial.printf("Wi-Fi connected: %s\n", WiFi.localIP().toString().c_str());
    }
    return;
  }

  udpStarted = false;
  static uint32_t lastWiFiAttemptMs = 0;
  const uint32_t nowMs = millis();
  if (nowMs - lastWiFiAttemptMs < 10000) {
    return;
  }
  lastWiFiAttemptMs = nowMs;

  Serial.printf("Connecting Wi-Fi SSID=%s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.disconnect(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

static void sendGatewayFrame(uint8_t connIndex, int8_t rssi, const uint8_t* payload, size_t len) {
  if (len != 17 && len != 11) {
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
  frame[7] = 1;  // flags: bit0 means source is BLE advertising.
  putU32LE(frame + 8, gatewaySequence++);
  putU32LE(frame + 12, micros());
  frame[16] = connIndex;
  frame[17] = static_cast<uint8_t>(rssi);
  memcpy(frame + GATEWAY_HEADER_LEN, payload, len);

  udp.beginPacket(PI_HOST, PI_UDP_PORT);
  udp.write(frame, GATEWAY_HEADER_LEN + len);
  udp.endPacket();
}

static bool expandSensorPayload(const uint8_t* uid, uint8_t* payload) {
  const uint8_t header = uid[1];
  const uint8_t hand = handFromHeader(header);
  if (hand > 1) {
    return false;
  }

  const uint16_t seq = getU16LE(uid + 2);
  if (seq == lastSensorSeq[hand]) {
    return false;
  }
  lastSensorSeq[hand] = seq;

  payload[0] = header;
  memcpy(payload + 1, uid + 2, 2);   // sequence
  memcpy(payload + 3, uid + 4, 4);   // timestamp_ms
  memcpy(payload + 7, uid + 8, 6);   // ax, ay, az
  const int16_t pitch = static_cast<int8_t>(uid[14]);
  const int16_t roll = static_cast<int8_t>(uid[15]);
  putU16LE(payload + 13, static_cast<uint16_t>(pitch));
  putU16LE(payload + 15, static_cast<uint16_t>(roll));
  return true;
}

static bool expandControlPayload(const uint8_t* uid, uint8_t* payload) {
  const uint8_t header = uid[1];
  const uint8_t hand = handFromHeader(header);
  if (hand > 1) {
    return false;
  }

  const uint16_t seq = getU16LE(uid + 2);
  const uint8_t repeatIndex = uid[10];
  const uint32_t key = (static_cast<uint32_t>(seq) << 8) | repeatIndex;
  if (key == lastControlKey[hand]) {
    return false;
  }
  lastControlKey[hand] = key;

  memcpy(payload, uid + 1, 11);
  return true;
}

static bool parseEddystoneUid(const NimBLEAdvertisedDevice* advertisedDevice, uint8_t* uid) {
  if (!advertisedDevice->haveServiceData()) {
    return false;
  }

  const std::string serviceData = advertisedDevice->getServiceData(EDDYSTONE_UUID);
  if (serviceData.size() < 18) {
    return false;
  }

  const uint8_t* data = reinterpret_cast<const uint8_t*>(serviceData.data());
  if (data[0] != 0x00) {
    return false;
  }

  memcpy(uid, data + 2, 16);
  return uid[0] == ADV_SENSOR || uid[0] == ADV_CONTROL;
}

class AdvertisingScanCallbacks : public NimBLEScanCallbacks {
 public:
  void onResult(const NimBLEAdvertisedDevice* advertisedDevice) override {
    uint8_t uid[16] = {0};
    if (!parseEddystoneUid(advertisedDevice, uid)) {
      return;
    }

    uint8_t payload[17] = {0};
    const int8_t rssi = advertisedDevice->getRSSI();
    const uint8_t hand = handFromHeader(uid[1]);
    if (hand > 1) {
      return;
    }

    bool ok = false;
    size_t payloadLen = 0;
    if (uid[0] == ADV_SENSOR) {
      ok = expandSensorPayload(uid, payload);
      payloadLen = 17;
    } else if (uid[0] == ADV_CONTROL) {
      ok = expandControlPayload(uid, payload);
      payloadLen = 11;
    }
    if (!ok) {
      return;
    }

    lastRssi[hand] = rssi;
    lastPacketMs[hand] = millis();
    sendGatewayFrame(hand, rssi, payload, payloadLen);
  }

  void onScanEnd(const NimBLEScanResults& results, int reason) override {
    Serial.printf("scan ended reason=%d seen=%d; restarting\n", reason, results.getCount());
    NimBLEDevice::getScan()->start(0, false, true);
  }
};

static AdvertisingScanCallbacks scanCallbacks;

static void printHeartbeat() {
  static uint32_t lastPrintMs = 0;
  const uint32_t nowMs = millis();
  if (nowMs - lastPrintMs < 5000) {
    return;
  }
  lastPrintMs = nowMs;

  Serial.printf("gateway seq=%lu wifi=%s mode=advertising\n",
                static_cast<unsigned long>(gatewaySequence),
                WiFi.status() == WL_CONNECTED ? "up" : "down");
  for (uint8_t hand = 0; hand < 2; hand++) {
    Serial.printf("  [%s] age_ms=%lu rssi=%d last_sensor_seq=%u\n",
                  hand == 0 ? "left" : "right",
                  lastPacketMs[hand] == 0 ? 0 : static_cast<unsigned long>(nowMs - lastPacketMs[hand]),
                  lastRssi[hand],
                  lastSensorSeq[hand]);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  connectWiFi();

  NimBLEDevice::init("microbit-adv-gateway");
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);

  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setScanCallbacks(&scanCallbacks, true);
  scan->setActiveScan(false);
  scan->setDuplicateFilter(false);
  scan->setInterval(45);
  scan->setWindow(45);
  scan->start(0, false, true);
  Serial.println("BLE advertising gateway started");
}

void loop() {
  connectWiFi();
  printHeartbeat();
  delay(50);
}
