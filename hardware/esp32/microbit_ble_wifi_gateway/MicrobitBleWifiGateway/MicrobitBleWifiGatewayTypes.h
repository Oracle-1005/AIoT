#pragma once

#include <Arduino.h>
#include <NimBLEDevice.h>

struct MicrobitLink {
  const char* label;
  NimBLEAddress address;
  bool addressKnown;
  bool fixedAddress;
  const NimBLEAdvertisedDevice* advertisedDevice;
  uint8_t connIndex;
  NimBLEClient* client;
  NimBLERemoteCharacteristic* notifyChar;
  bool subscribed;
  uint32_t lastConnectAttemptMs;
  uint32_t lastPacketMs;
  int8_t lastRssi;
  uint8_t failedConnects;
};
