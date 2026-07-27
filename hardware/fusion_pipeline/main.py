#!/usr/bin/env python3
"""AIoT Fusion Pipeline — ESP32 BLE Gateway + Camera → PC backend.

Unified entry point for the ESP32 micro:bit BLE broadcast → UDP → Pi
fusion pipeline as described in:

    hardware/raspberry_pi/MICROBIT_ESP32_CAMERA_DATA_FLOW.md

Architecture
------------
  ESP32 UDP (MBGW frames, :17778)  ──→  GatewayAdapter
      │                                     │ sensor_state │ control_event
      │                                     ▼               ▼
      │                            FusionEngine buffers   direct TCP send
      │                                     │
  Camera (Picamera2 + MediaPipe)  ──→  CameraAdapter
      │                                     │
      │                                     ▼ (camera frame triggers fusion)
      │                            FusionEngine.fuse()
      │                                     │
      │                                     ▼
      │                            TcpJsonlClient (:9000)  ──→  PC backend
      │
      └── 3 JSON Lines message types: fused_frame, control_event, status

Usage
-----
    cd ~/aiot_conductor/project/hardware/fusion_pipeline
    python main.py [--config config.yaml]

Press Ctrl+C for graceful shutdown.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

# Ensure hardware/ is on sys.path so we can import from pi_pc, sensors, etc.
_HARDWARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARDWARE))
# Also add sub-packages for the ESP32 gateway receiver
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "esp32_ble_gateway_to_Pi"))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "microbit_to_Pi"))

import yaml

from microbit_receiver.protocol import Hand

from fusion_pipeline.fusion_engine import FusionEngine
from fusion_pipeline.gateway_adapter import GatewayAdapter, MicrobitSample
from fusion_pipeline.radio_serial_adapter import RadioSerialAdapter
from fusion_pipeline.camera_adapter import CameraAdapter
from fusion_pipeline.tcp_client import TcpJsonlClient
from fusion_pipeline.preview_server import PreviewServer, PreviewState
from fusion_pipeline.led_consumer import LedConsumer

logger = logging.getLogger("fusion_pipeline")


# ── Defaults (overridden by config.yaml) ───────────────────────────────────

DEFAULT_CONFIG: dict = {
    "gateway": {
        "transport": "esp32_udp",
        "listen_host": "0.0.0.0",
        "listen_port": 17778,
        "serial_device": "/dev/serial/by-id/usb-ARM_BBC_micro:bit_CMSIS-DAP_9900000043114e45006590030000006a0000000097969901-if01",
        "serial_baud_rate": 115200,
        "serial_reconnect_delay_s": 1.0,
        "allowed_hands": ["left", "right"],
        "event_dedup_ttl_s": 10.0,
        "noise_filter": {
            "ema_alpha_accel": 0.85,
            "ema_alpha_orientation": 0.90,
            "median_window": 5,
            "outlier_threshold_mg": 500.0,
        },
    },
    "camera": {
        "width": 640,
        "height": 480,
        "fps": 30,
        "max_hands": 2,
        "frame_queue_size": 10,
        "pixel_format": "BGR888",
        "min_hand_detection_confidence": 0.35,
        "min_hand_presence_confidence": 0.35,
        "min_tracking_confidence": 0.40,
        "max_missing_frames": 4,
        "detection_window_seconds": 5.0,
        "buffer_max_age_s": 10.0,
        "clock_min_points": 10,
        "clock_max_points": 60,
    },
    "fusion": {
        "max_age_ms": 120,
        "buffer_max_age_s": 10.0,
        "jitter_buffer_ms": 250,
    },
    "tcp": {
        "host": "192.168.1.100",
        "port": 9000,
        "reconnect_delay_s": 2.0,
        "max_queue_size": 500,
        "connect_timeout_s": 5.0,
    },
    "video_stream": {
        # In-process MJPEG live view (see video_stream.py).  Lets a browser
        # watch the camera WHILE pi-fusion runs — the standalone previews
        # (8765/8790) can't, since the camera is single-owner.
        "enabled": False,
        "host": "0.0.0.0",
        "port": 8791,
        "fps": 10,
        "quality": 70,
        "annotate": True,
    },
    "general": {
        "pi_id": "raspberrypi-01",
        "schema_version": "1.0",
        "log_level": "INFO",
        "status_interval_s": 1.0,
        "fusion_poll_interval_s": 0.005,
    },
    "preview": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8790,
        "jpeg_quality": 70,
        "jpeg_every_n_frames": 2,
    },
    "led": {
        # WS2812B panels via ws2812-pio (/dev/leds0, GPIO19). Consumes
        # led_command downlink from the PC backend (INTERFACE_CONTRACT §8.1).
        # Requires write permission on /dev/leds0 for the service user.
        "enabled": False,
        "default_pattern": "breathing",
        "brightness_limit": 0.25,
        "refresh_hz": 50,
    },
}


# ── Config helpers ─────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Returns a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str) -> dict:
    """Load YAML config, merging with defaults."""
    cfg = DEFAULT_CONFIG.copy()
    config_path = Path(path)
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user)
    else:
        logger.warning("Config file %s not found — using defaults.", path)
    return cfg


# ── Application ────────────────────────────────────────────────────────────

class FusionApp:
    """Top-level application that wires GatewayAdapter + CameraAdapter +
    FusionEngine + TcpJsonlClient together.
    """

    def __init__(self, config: dict) -> None:
        self._cfg = config

        # Subsystems (created in start())
        self._gateway: GatewayAdapter | RadioSerialAdapter | None = None
        self._camera: CameraAdapter | None = None
        self._fusion: FusionEngine | None = None
        self._tcp: TcpJsonlClient | None = None
        self._preview_state: PreviewState | None = None
        self._preview_server: PreviewServer | None = None
        self._led: LedConsumer | None = None
        self._video = None  # MjpegStreamer | None — optional, config-gated

        self._running = False
        self._shutdown_event = asyncio.Event()

        # Counters
        self._fused_count = 0
        self._event_count = 0
        self._status_count = 0

        # Micro:bit anchor liveness for the camera preview overlay.
        # Stamped per accepted sample in _on_microbit_sample; the preview
        # JPEG encoder drops the hand skeleton when no side is fresh.
        self._mb_anchor_last_rx: dict[str, float] = {"left": 0.0, "right": 0.0}
        self._mb_anchor_max_age_s = 1.0

    # ── Start / Stop ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize all subsystems."""
        logger.info("=== AIoT Fusion Pipeline ===")

        preview_cfg = self._cfg.get("preview", {})
        if preview_cfg.get("enabled", False):
            self._preview_state = PreviewState()
            self._preview_server = PreviewServer(
                host=preview_cfg.get("host", "0.0.0.0"),
                port=int(preview_cfg.get("port", 8790)),
                state=self._preview_state,
            )
            try:
                self._preview_server.start()
            except Exception:
                logger.exception("Preview server failed to start; continuing without preview.")
                self._preview_server = None
                self._preview_state = None

        # ── TCP Client ────────────────────────────────────────────────
        tcp_cfg = self._cfg["tcp"]
        self._tcp = TcpJsonlClient(
            host=tcp_cfg["host"],
            port=tcp_cfg["port"],
            reconnect_delay_s=tcp_cfg["reconnect_delay_s"],
            max_queue_size=tcp_cfg["max_queue_size"],
            connect_timeout_s=tcp_cfg["connect_timeout_s"],
        )
        await self._tcp.start()

        # ── LED downlink consumer (optional, hardware-gated) ──────────
        led_cfg = self._cfg.get("led", {})
        if led_cfg.get("enabled", False):
            self._led = LedConsumer(
                enabled=True,
                default_pattern=led_cfg.get("default_pattern", "breathing"),
                brightness_limit=float(led_cfg.get("brightness_limit", 0.25)),
                music_panel=bool(led_cfg.get("music_panel", False)),
                music_stack_top_panel=int(led_cfg.get("music_stack_top", 0)),
            )
            self._tcp.set_downlink_handler(self._led.handle_message)

        # ── Fusion Engine ─────────────────────────────────────────────
        fusion_cfg = self._cfg["fusion"]
        self._fusion = FusionEngine(
            max_age_ms=fusion_cfg["max_age_ms"],
            buffer_max_age_s=fusion_cfg["buffer_max_age_s"],
            jitter_buffer_ms=fusion_cfg["jitter_buffer_ms"],
        )

        # ── Gateway Adapter ───────────────────────────────────────────
        gw_cfg = self._cfg["gateway"]
        allowed = {Hand.from_label(h) for h in gw_cfg["allowed_hands"]}
        gateway_callbacks = {
            "allowed_hands": allowed,
            "event_dedup_ttl_s": gw_cfg["event_dedup_ttl_s"],
            "noise_filter_config": gw_cfg.get("noise_filter", {}),
            "on_raw_sensor_state": self._on_raw_microbit_sample,
            "on_sensor_state": self._on_microbit_sample,
            "on_control_event": self._on_control_event,
        }
        gateway_transport = gw_cfg.get("transport", "esp32_udp")
        if gateway_transport == "microbit_radio_usb":
            self._gateway = RadioSerialAdapter(
                device=gw_cfg["serial_device"],
                baud_rate=int(gw_cfg.get("serial_baud_rate", 115200)),
                reconnect_delay_s=float(
                    gw_cfg.get("serial_reconnect_delay_s", 1.0)
                ),
                **gateway_callbacks,
            )
        elif gateway_transport == "esp32_udp":
            self._gateway = GatewayAdapter(
                listen_host=gw_cfg["listen_host"],
                listen_port=gw_cfg["listen_port"],
                **gateway_callbacks,
            )
        else:
            raise ValueError(
                f"Unsupported gateway.transport: {gateway_transport!r}"
            )
        await self._gateway.start()

        # ── Camera Adapter ────────────────────────────────────────────
        cam_cfg = self._cfg["camera"]
        self._camera = CameraAdapter(
            width=cam_cfg["width"],
            height=cam_cfg["height"],
            fps=cam_cfg["fps"],
            max_hands=cam_cfg["max_hands"],
            frame_queue_size=cam_cfg["frame_queue_size"],
            pixel_format=cam_cfg["pixel_format"],
            min_hand_detection_confidence=cam_cfg["min_hand_detection_confidence"],
            min_hand_presence_confidence=cam_cfg["min_hand_presence_confidence"],
            min_tracking_confidence=cam_cfg["min_tracking_confidence"],
            max_missing_frames=cam_cfg["max_missing_frames"],
            detection_window_seconds=cam_cfg["detection_window_seconds"],
            buffer_max_age_s=cam_cfg["buffer_max_age_s"],
            clock_min_points=cam_cfg["clock_min_points"],
            clock_max_points=cam_cfg["clock_max_points"],
            enable_preview_jpeg=bool(preview_cfg.get("enabled", False)),
            preview_jpeg_quality=int(preview_cfg.get("jpeg_quality", 70)),
            preview_jpeg_every_n_frames=int(preview_cfg.get("jpeg_every_n_frames", 2)),
            preview_anchor_provider=self._preview_anchor_active,
        )

        camera_ok = self._camera.start()
        if not camera_ok:
            logger.warning("Camera failed to start — running without camera.")
        else:
            logger.info("Camera started.")

        # ── Optional MJPEG video stream (in-process camera tap) ──────
        vs_cfg = self._cfg.get("video_stream", {})
        if camera_ok and vs_cfg.get("enabled"):
            from fusion_pipeline.video_stream import MjpegStreamer  # noqa: PLC0415

            self._video = MjpegStreamer(
                host=vs_cfg.get("host", "0.0.0.0"),
                port=vs_cfg.get("port", 8791),
                fps=vs_cfg.get("fps", 10),
                quality=vs_cfg.get("quality", 70),
                annotate=vs_cfg.get("annotate", True),
            )
            if self._video.start():
                self._camera.set_frame_image_callback(self._video.submit)
            else:
                self._video = None

        self._running = True
        if self._preview_state:
            self._preview_state.set_running(True)
        logger.info("=== Fusion Pipeline started ===")

    async def stop(self) -> None:
        """Gracefully shutdown all subsystems."""
        logger.info("Shutting down...")
        self._running = False
        self._shutdown_event.set()

        if self._video:
            if self._camera:
                self._camera.set_frame_image_callback(None)
            self._video.stop()
            self._video = None
        if self._camera:
            self._camera.stop()
        if self._gateway:
            await self._gateway.stop()
        if self._tcp:
            await self._tcp.stop()
        if self._led:
            self._led.close()
            self._led = None
        if self._preview_server:
            self._preview_server.stop()
        if self._preview_state:
            self._preview_state.set_running(False)

        logger.info(
            "=== Fusion Pipeline stopped. "
            "frames=%d events=%d statuses=%d ===",
            self._fused_count,
            self._event_count,
            self._status_count,
        )

    # ── Main Loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main event loop.

        Three concurrent activities:
          1. Camera poll → fusion → TCP send (at fusion_poll_interval_s)
          2. Control event drain → TCP send (every poll cycle)
          3. Status message → TCP send (every status_interval_s)
        """
        poll_s = self._cfg["general"]["fusion_poll_interval_s"]
        status_s = self._cfg["general"]["status_interval_s"]
        last_status = time.monotonic()
        led_cfg = self._cfg.get("led", {})
        led_interval_s = 1.0 / max(1.0, float(led_cfg.get("refresh_hz", 50)))
        last_led = 0.0

        logger.info(
            "Main loop started: poll=%.0f Hz, status=%.0f Hz",
            1.0 / poll_s,
            1.0 / status_s,
        )

        while self._running:
            try:
                # ── 1. Camera → jitter buffer → fusion ────────────────
                if self._camera and self._camera.is_running():
                    camera_frame = self._camera.poll_frame()
                    if camera_frame is not None:
                        if self._preview_state:
                            self._preview_state.set_camera(camera_frame)
                        self._fusion.enqueue_camera_frame(camera_frame)

                # Drain jitter buffer: pop frames whose delay has expired
                for fused in self._fusion.drain_ready_frames():
                    if self._tcp:
                        if self._preview_state:
                            self._preview_state.add_outbound(fused)
                        self._tcp.send(fused)
                        self._fused_count += 1

                # ── 2. Control events ─────────────────────────────────
                # Control events are emitted immediately via the
                # GatewayAdapter.on_control_event callback (fast path
                # — no queuing, no fusion delay).  See _on_control_event().

                # ── 3. Periodic status ────────────────────────────────
                now = time.monotonic()
                if now - last_status >= status_s:
                    status_msg = self._build_status()
                    if self._tcp:
                        if self._preview_state:
                            self._preview_state.add_outbound(status_msg)
                            self._preview_state.set_tcp_status(self._tcp.get_status())
                        self._tcp.send(status_msg)
                        self._status_count += 1
                    last_status = now

                # ── 4. LED animation frame (throttled to refresh_hz) ──
                if self._led is not None and now - last_led >= led_interval_s:
                    self._led.update()
                    last_led = now

                await asyncio.sleep(poll_s)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Main loop error")
                await asyncio.sleep(0.1)

        logger.info("Main loop stopped.")

    # ── Callbacks ─────────────────────────────────────────────────────

    def _on_raw_microbit_sample(self, item: dict) -> None:
        """GatewayAdapter -> preview before sequence tracking and filtering."""
        if self._preview_state:
            self._preview_state.set_raw_microbit(item)

    def _on_microbit_sample(self, sample: MicrobitSample) -> None:
        """GatewayAdapter → FusionEngine buffer."""
        side = str(getattr(sample, "source", "")).strip().lower()
        if side in self._mb_anchor_last_rx:
            self._mb_anchor_last_rx[side] = time.monotonic()
        if self._preview_state:
            self._preview_state.set_filtered_microbit(sample.to_dict())
        if self._fusion:
            self._fusion.push_microbit_sample(sample)

    def _preview_anchor_active(self) -> bool:
        """True while at least one micro:bit sample arrived recently.

        Feeds CameraSensor.preview_anchor_provider: no live anchor -> the
        MJPEG preview is encoded without the hand skeleton overlay.
        """
        now = time.monotonic()
        return any(
            last > 0.0 and (now - last) < self._mb_anchor_max_age_s
            for last in self._mb_anchor_last_rx.values()
        )

    def _on_control_event(self, event: dict) -> None:
        """GatewayAdapter → FusionEngine control event queue + direct send."""
        # Send immediately (fast path — don't wait for camera frame)
        if self._tcp:
            if self._preview_state:
                self._preview_state.add_outbound(event)
            self._tcp.send(event)
            self._event_count += 1

    # ── Status Builder ────────────────────────────────────────────────

    def _build_status(self) -> dict:
        """Aggregate status from gateway and camera."""
        gw_status = self._gateway.get_status() if self._gateway else {}
        cam_status = self._camera.get_status() if self._camera else {}
        return self._fusion.build_status(gw_status, cam_status)


# ── Entry Point ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AIoT Fusion Pipeline — ESP32 Gateway + Camera → PC"
    )
    p.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to YAML config (default: config.yaml)",
    )
    return p.parse_args()


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def async_main() -> None:
    args = parse_args()

    # Resolve config path relative to this file
    config_path = Path(__file__).resolve().parent / args.config

    cfg = load_config(str(config_path))
    setup_logging(cfg["general"].get("log_level", "INFO"))

    app = FusionApp(cfg)

    # ── Signal handling ───────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal() -> None:
        logger.info("Received shutdown signal.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass  # Windows

    try:
        await app.start()

        runner = asyncio.create_task(app.run())
        stopper = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            [runner, stopper],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received.")
    except Exception:
        logger.exception("Fatal error")
    finally:
        await app.stop()


def main() -> None:
    """Console entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")


if __name__ == "__main__":
    main()
