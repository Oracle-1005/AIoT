#!/usr/bin/env python3
"""AIoT Smart Conductor System — Raspberry Pi Entry Point.

Orchestrates BLE micro:bit connections, camera capture, sensor fusion,
feature extraction, TCP transport, and LED control.

Usage:
    python main.py [--config config.yaml]

Press Ctrl+C for graceful shutdown.
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

# Add parent to path so imports work when run from the project directory
sys.path.insert(0, str(Path(__file__).parent))

from utils.config import load_config, save_default_config
from ble.ble_manager import BleManager
from sensors.microbit import MicrobitSensor, MicrobitSample
from sensors.camera import CameraSensor
from fusion.engine import FusionEngine
from fusion.ring_buffer import TimestampedSample
from features.instant import InstantFeatureComputer
from features.window import SlidingWindowComputer, WindowConfig
from messages.builder import MessageBuilder
from transport.tcp_client import TcpJsonlClient

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    """Configure logging format and level."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class AppController:
    """Top-level application controller.

    Wires together all subsystems and manages the main event loop.
    """

    def __init__(self, config_path: str = "config.yaml"):
        # Load configuration
        if not Path(config_path).exists():
            logger.info("Config file not found. Creating default: %s", config_path)
            save_default_config(config_path)

        self._config = load_config(config_path)
        setup_logging(self._config["general"].get("log_level", "INFO"))

        logger.info("=== AIoT Smart Conductor System ===")
        logger.info("Session: %s", self._config["general"].get("pi_id", "unknown"))

        # ---- Subsystems (initialized in start()) ----
        self._ble_manager: BleManager | None = None
        self._camera_sensor: CameraSensor | None = None
        self._fusion_engine: FusionEngine | None = None
        self._feature_computer: InstantFeatureComputer | None = None
        self._window_computer: SlidingWindowComputer | None = None
        self._message_builder: MessageBuilder | None = None
        self._tcp_client: TcpJsonlClient | None = None
        self._microbit_sensors: dict[str, MicrobitSensor] = {}

        # LED controller (optional)
        self._led_controller = None  # Lazy import to avoid rpi_ws281x dependency

        # Running state
        self._running = False
        self._start_time_ns: int = 0

        # Stats
        self._fused_frame_count = 0
        self._window_count = 0
        self._event_count = 0
        self._status_count = 0

    # ---- Start / Stop ----

    async def start(self) -> None:
        """Initialize all subsystems and begin data flow."""

        # ---- Message Builder ----
        self._message_builder = MessageBuilder(
            schema_version=self._config["general"]["schema_version"],
            pi_id=self._config["general"]["pi_id"],
        )
        logger.info("Message builder initialized. session_id=%s", self._message_builder.session_id)

        # ---- TCP Client ----
        tcp_cfg = self._config["pi_to_pc"]
        self._tcp_client = TcpJsonlClient(
            host=tcp_cfg["host"],
            port=tcp_cfg["port"],
            reconnect_delay_s=tcp_cfg["reconnect_delay_s"],
            max_queue_size=tcp_cfg["max_queue_size"],
            connect_timeout_s=tcp_cfg["connect_timeout_s"],
        )
        await self._tcp_client.start()

        # ---- Fusion Engine ----
        self._fusion_engine = FusionEngine(self._config["fusion"])
        self._fusion_engine.set_fused_frame_callback(self._on_fused_frame)

        # ---- Feature Computers ----
        self._feature_computer = InstantFeatureComputer()
        self._window_computer = SlidingWindowComputer(
            WindowConfig(
                duration_ms=self._config["fusion"]["window_ms"],
                hop_ms=self._config["fusion"]["hop_ms"],
            )
        )

        # ---- BLE Manager ----
        self._ble_manager = BleManager(
            device_configs=self._config["microbits"],
            on_packet=self._on_ble_packet,
        )

        # ---- Micro:bit Sensors ----
        fusion_cfg = self._config["fusion"]
        for device_cfg in self._config["microbits"]:
            device_id = device_cfg["device_id"]
            address = device_cfg.get("address", "").strip()

            if not address:
                logger.warning("[%s] No BLE address configured. Skipping.", device_id)
                continue

            # Register with fusion engine
            self._fusion_engine.register_device(device_id, device_cfg["hand"])

            # Create sensor
            sensor = MicrobitSensor(
                device_id=device_id,
                hand=device_cfg["hand"],
                address=address,
                ble_manager=self._ble_manager,
                on_sample=self._on_microbit_sample,
                sync_config=fusion_cfg,
                loss_window_size=fusion_cfg.get("loss_window_size", 100),
            )
            self._microbit_sensors[device_id] = sensor

        # ---- BLE Scan and Connect ----
        scan_timeout = self._config["microbit"].get("ble_scan_timeout_s", 5.0)
        connected = await self._ble_manager.scan_and_connect_all(scan_timeout)
        logger.info("BLE connections: %d/%d", connected, len(self._microbit_sensors))

        # ---- Start Micro:bit Sensors ----
        for device_id, sensor in self._microbit_sensors.items():
            if self._ble_manager.is_connected(device_id):
                await sensor.start()
                logger.info("[%s] Sensor started.", device_id)

        # ---- Camera Sensor ----
        try:
            cam_cfg = self._config["camera"]
            self._camera_sensor = CameraSensor(
                width=cam_cfg["width"],
                height=cam_cfg["height"],
                fps=cam_cfg["fps"],
                max_hands=cam_cfg["max_hands"],
                frame_queue_size=cam_cfg.get("frame_queue_size", 10),
            )
            self._camera_sensor.start()
            logger.info("Camera sensor started.")
        except Exception as e:
            logger.warning("Camera initialization failed: %s. Running without camera.", e)
            self._camera_sensor = None

        # ---- LED Controller (optional) ----
        led_cfg = self._config["led"]
        if led_cfg.get("enabled", False):
            try:
                from led.controller import LedController
                self._led_controller = LedController(
                    gpio=led_cfg.get("gpio", 18),
                    panel_count=led_cfg.get("panel_count", 2),
                    led_per_panel=led_cfg.get("led_per_panel", 256),
                    brightness_limit=led_cfg.get("brightness_limit", 0.25),
                )
                logger.info("LED controller initialized.")
            except ImportError:
                logger.warning("rpi_ws281x not available. LED control disabled.")
            except Exception as e:
                logger.warning("LED init failed: %s", e)
        else:
            logger.info("LED control disabled in config.")

        # ---- Mark running ----
        self._running = True
        self._start_time_ns = time.monotonic_ns()
        logger.info("=== System started ===")

    async def stop(self) -> None:
        """Gracefully shutdown all subsystems."""
        logger.info("Shutting down...")
        self._running = False

        # Stop camera
        if self._camera_sensor:
            self._camera_sensor.stop()

        # Stop micro:bit sensors
        for device_id, sensor in self._microbit_sensors.items():
            await sensor.stop()

        # Disconnect BLE
        if self._ble_manager:
            await self._ble_manager.disconnect_all()

        # Stop TCP
        if self._tcp_client:
            await self._tcp_client.stop()

        # Clear LEDs
        if self._led_controller:
            try:
                self._led_controller.clear()
            except Exception:
                pass

        logger.info("=== System stopped ===")

    # ---- Main loops ----

    async def run(self) -> None:
        """Main event loop. Polls camera and runs periodic tasks."""
        if not self._running:
            return

        # Launch periodic tasks
        periodic_tasks = [
            asyncio.create_task(self._fusion_loop()),
            asyncio.create_task(self._status_loop()),
        ]

        if self._led_controller:
            periodic_tasks.append(asyncio.create_task(self._led_animation_loop()))

        try:
            await asyncio.gather(*periodic_tasks)
        except asyncio.CancelledError:
            pass

    async def _fusion_loop(self) -> None:
        """Main fusion loop: camera poll → fuse → internal window → events.

        Runs at fused_frame_max_hz (typically 25 Hz). For each camera frame:
          1. Build camera dict and trigger FusionEngine.on_camera_frame()
          2. Fused frames are emitted via callback → TcpJsonlClient
          3. Fused frames are fed to SlidingWindowComputer internally
          4. When a window is complete, detect events and emit control_event
        """
        logger.info("Fusion loop started.")
        target_interval = 1.0 / self._config["pi_to_pc"].get("fused_frame_max_hz", 25)

        while self._running:
            try:
                if self._camera_sensor:
                    frame = self._camera_sensor.get_frame(timeout=0.02)
                    if frame is not None:
                        camera_dict = {
                            "frame_id": frame.frame_id,
                            "sensor_timestamp_ns": frame.sensor_timestamp_ns,
                            "width": frame.width,
                            "height": frame.height,
                            "fps": self._config["camera"]["fps"],
                            "processing_latency_ms": frame.processing_latency_ms,
                            "hands": frame.hands,
                        }
                        fused = self._fusion_engine.on_camera_frame(camera_dict)

                        # Feed fused frame to internal window computer for event detection
                        if fused and self._window_computer:
                            window_result = self._window_computer.add_frame(fused)
                            if window_result:
                                # Detect events from window statistics
                                event_data = self._detect_event_from_window(window_result)
                                if event_data:
                                    self._event_count += 1
                                    event_msg = self._message_builder.build_control_event(event_data)
                                    self._tcp_client.send(event_msg)
                                    self._window_count += 1
                                    logger.info(
                                        "control_event: type=%s hand=%s strength=%.2f",
                                        event_data["event"]["type"],
                                        event_data["event"]["hand"],
                                        event_data["event"]["strength"],
                                    )
                else:
                    # No camera — sleep to avoid busy loop
                    pass

                await asyncio.sleep(target_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Fusion loop error: %s", e, exc_info=True)
                await asyncio.sleep(0.1)

        logger.info("Fusion loop stopped.")

    async def _status_loop(self) -> None:
        """Emit status messages at 1Hz."""
        logger.info("Status loop started.")
        interval = self._config["general"].get("status_interval_s", 1.0)

        while self._running:
            try:
                status_data = self._build_status()
                msg = self._message_builder.build_status(status_data)
                self._tcp_client.send(msg)
                self._status_count += 1

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Status loop error: %s", e)
                await asyncio.sleep(interval)

        logger.info("Status loop stopped.")

    async def _led_animation_loop(self) -> None:
        """Update LED animation at ~50Hz."""
        if self._led_controller is None:
            return

        logger.info("LED animation loop started.")
        interval = 1.0 / 50.0

        while self._running:
            try:
                self._led_controller.update()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(interval)

        logger.info("LED animation loop stopped.")

    # ---- Callbacks ----

    def _on_ble_packet(self, device_id: str, raw_data: bytearray, pi_receive_ns: int) -> None:
        """Called by BleManager on every BLE notification.

        Routes the raw packet to the appropriate MicrobitSensor.

        Args:
            device_id: Logical device ID.
            raw_data: Raw bytearray from BLE notification.
            pi_receive_ns: Pi monotonic_ns when notification arrived.
        """
        sensor = self._microbit_sensors.get(device_id)
        if sensor is None:
            logger.warning("Received packet for unknown device: %s", device_id)
            return

        sensor.handle_raw_packet(raw_data, pi_receive_ns)

    def _on_microbit_sample(self, sample: MicrobitSample) -> None:
        """Called by MicrobitSensor when a valid sample is ready.

        Computes instant features and pushes to fusion engine.

        Args:
            sample: Fully processed MicrobitSample.
        """
        # Compute instant features
        sample_dict = sample.to_dict()

        if self._feature_computer:
            instant_features = self._feature_computer.compute_microbit_features(
                sample.device_id,
                sample_dict,
                sample.pi_aligned_timestamp_ns,
            )
            sample_dict["instant_features"] = instant_features

        # Push to fusion engine
        self._fusion_engine.on_microbit_sample(sample_dict)

    def _on_fused_frame(self, fused_frame: dict) -> None:
        """Called by FusionEngine when a fused_frame is produced.

        Builds the full message and sends it to PC via TCP.

        Args:
            fused_frame: The fused_frame dict from FusionEngine.
        """
        self._fused_frame_count += 1

        # Build full message
        msg = self._message_builder.build_fused_frame(fused_frame)

        # Enqueue for TCP send
        self._tcp_client.send(msg)

    def _detect_event_from_window(self, window_result: dict) -> dict | None:
        """Detect control events from sliding window statistics.

        Uses simple rule-based detection on window_features data internally.
        The window data is NOT sent to PC — only the detected events are.

        Args:
            window_result: Dict from SlidingWindowComputer.add_frame().

        Returns:
            Event data dict ready for MessageBuilder.build_control_event(),
            or None if no event detected.
        """
        mb_features = window_result.get("microbit_features", {})
        cm = window_result.get("cross_modal_features", {})
        fusion_cfg = self._config["fusion"]

        left = mb_features.get("left_hand", {})
        right = mb_features.get("right_hand", {})

        max_jerk = max(
            left.get("max_jerk_g_s", 0),
            right.get("max_jerk_g_s", 0),
        )

        threshold = fusion_cfg.get("jerk_threshold_g_s", 5.0)
        if max_jerk < threshold:
            return None

        # Determine dominant hand
        if left.get("max_jerk_g_s", 0) >= right.get("max_jerk_g_s", 0):
            hand = "left"
            strength = min(left.get("max_jerk_g_s", 0) / (threshold * 2), 1.0)
        else:
            hand = "right"
            strength = min(right.get("max_jerk_g_s", 0) / (threshold * 2), 1.0)

        # Event type based on strength
        if strength > 0.7:
            event_type = f"{hand}_wrist_strike"
        else:
            event_type = "downbeat"

        # Build event data
        return {
            "event_id": f"evt-{self._event_count + 1:05d}",
            "event": {
                "type": event_type,
                "hand": hand,
                "confidence": min(strength, 1.0),
                "strength": round(strength, 3),
            },
            "music_control": {
                "estimated_bpm": cm.get("estimated_bpm", 120),
                "tempo_delta": 0.0,
                "volume": round(strength * 0.8, 3),
                "intensity": round(strength, 3),
                "articulation": 0.5,
            },
            "led_control": {
                "pattern": f"{hand}_pulse",
                "brightness": round(strength * 0.5, 3),
                "duration_ms": 120,
            },
        }

    # ---- Status builder ----

    def _build_status(self) -> dict:
        """Aggregate status from all subsystems.

        Returns:
            Status data dict ready for MessageBuilder.build_status().
        """
        # Camera status
        camera_status = {
            "connected": False,
            "configured_fps": self._config["camera"]["fps"],
            "actual_fps": 0.0,
            "dropped_frames": 0,
            "last_frame_age_ms": 0.0,
            "processing_latency_ms": 0.0,
        }
        if self._camera_sensor:
            camera_status = self._camera_sensor.get_status()

        # Micro:bit status
        left_status = {
            "device_id": "MB_LEFT",
            "transport": "ble",
            "connected": False,
            "rssi_dbm": 0,
            "sample_rate_hz": 0.0,
            "recent_loss_ratio": 0.0,
            "clock_ready": False,
            "sync_rtt_ms": 0.0,
            "last_sample_age_ms": 0.0,
        }
        right_status = {
            "device_id": "MB_RIGHT",
            "transport": "ble",
            "connected": False,
            "rssi_dbm": 0,
            "sample_rate_hz": 0.0,
            "recent_loss_ratio": 0.0,
            "clock_ready": False,
            "sync_rtt_ms": 0.0,
            "last_sample_age_ms": 0.0,
        }

        for device_id, sensor in self._microbit_sensors.items():
            s = sensor.get_status()
            if sensor.hand == "left":
                left_status.update(s)
            elif sensor.hand == "right":
                right_status.update(s)

        # Network status
        network_status = {"pc_connected": False}
        if self._tcp_client:
            network_status = self._tcp_client.get_status()

        # LED status
        led_status = {"connected": False}
        if self._led_controller:
            led_status = self._led_controller.get_status()

        # Fusion status
        fusion_status = self._fusion_engine.get_status() if self._fusion_engine else {}

        return {
            "camera": camera_status,
            "microbits": {
                "left": left_status,
                "right": right_status,
            },
            "network": network_status,
            "led": led_status,
            "_fusion": fusion_status,
            "_counts": {
                "fused_frames": self._fused_frame_count,
                "windows": self._window_count,
                "events": self._event_count,
                "statuses": self._status_count,
            },
        }


# ---- Entry Point ----

def parse_args():
    parser = argparse.ArgumentParser(
        description="AIoT Smart Conductor System — Raspberry Pi"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to YAML configuration file (default: config.yaml)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # Change to the project directory so config.yaml is found
    import os
    project_dir = Path(__file__).parent
    os.chdir(project_dir)

    app = AppController(args.config)

    # Set up signal handling for graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Received shutdown signal.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await app.start()
        # Run until stopped
        runner = asyncio.create_task(app.run())
        stopper = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            [runner, stopper],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received.")
    except Exception as e:
        logger.exception("Fatal error: %s", e)
    finally:
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
