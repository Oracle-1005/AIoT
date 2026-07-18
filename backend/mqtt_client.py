"""Legacy compatibility stub.

MQTT belonged to the removed ESP32 design and is no longer used.  Pi/PC and
LED communication now use TCP + JSON Lines through pi_gateway.py.
"""

class LegacyMQTTClient:
    connected = False
    def start(self) -> bool: return False
    def stop(self) -> None: return None
    def publish_prediction(self, _result) -> bool: return False

mqtt_client = LegacyMQTTClient()
MQTT_ENABLED = False
MQTT_HOST = "disabled"
MQTT_PORT = 0
