---
**SWS3025 Group Project Proposal**

| | | | |
|:---|:---|:---|:---|
| **Group Leader:** | 王祎哲 | **Username:** | t0939395 |
| **Project Group:** | P01 | | |
| **Member 1:** | 王玺达 | **Username:** | t0939390 |
| **Member 2:** | 王清源 | **Username:** | t0939384 |
| **Member 3:** | 王俊智 | **Username:** | t0939382 |
| **Member 4:** | 罗子超 | **Username:** | t0939291 |
| **Project Title:** | AIoT Smart Conducting Performance System | | |

---

## [DESCRIPTION OF PROBLEM]

Music performance and music education often require expressive body movement, especially hand gestures used by conductors to communicate tempo, intensity, entrances, pauses, and emotional changes. However, most digital music systems are still controlled through keyboards, mice, touch screens, or fixed physical instruments. These interfaces can trigger sound, but they do not naturally capture the expressive conducting gestures that humans use in live performance.

In an organisational context such as a school, music workshop, music club, or performance training environment, students may practise conducting movements without receiving immediate data-driven feedback. The relationship between gesture, musical intention, and musical output is often difficult to demonstrate objectively. In an individual consumer context, users who want to explore interactive music creation usually lack an affordable system that can sense body movement, analyse it with AI, and convert it into real-time music control.

This project addresses the problem by creating an AIoT smart conducting performance system. The system will capture the user's conducting gestures, analyse the movement using a local machine learning model, and convert recognised musical intentions into music-control actions. It will also record sensor data and prediction results so that users can view the complete AIoT process through a frontend dashboard.

---

## [DESCRIPTION OF PROPOSED SOLUTION]

We propose to build an AIoT Smart Conducting Performance System. The core interaction is a contactless conducting experience: the user moves both hands in front of a camera, and the system interprets these movements as musical conducting intentions. The camera will be the main spatial sensing input for capturing two-hand position, movement direction, speed, distance, and gesture trajectory.

Two Micro:bit v2 devices will be worn on the user's wrists using elastic straps, each streaming tri-axial accelerometer data (acc_x, acc_y, acc_z) to the PC via BLE UART at 50 Hz. The Micro:bit data serves three purposes. First, hand identity matching (anti-interference): in a classroom or demonstration environment, the camera may capture bystanders' hands in addition to the conductor's; the system correlates each detected hand's motion trajectory with the Micro:bit acceleration signal, identifies the hand whose velocity pattern best matches the Micro:bit's acceleration peaks as the conductor's, and filters out the rest. Second, downbeat confirmation: a rapid downward acceleration peak on the right-hand Micro:bit provides a high-confidence beat-point signal that remains reliable even when the camera suffers from motion blur or poor lighting. Third, gesture intensity measurement: the magnitude of acceleration change (jerk) quantifies the force of crescendo and cutoff gestures, providing a lighting-independent intensity signal that camera-based position tracking alone may misjudge. The camera remains the primary spatial sensor; Micro:bit data acts as a fused secondary modality for identity anchoring, motion confirmation, and intensity quantification.

The IoT hardware prototype consists of three layers: a USB webcam for hand-motion capture, two wrist-worn Micro:bit v2 devices streaming accelerometer data via BLE, and actuator outputs including browser-based music playback via Web Audio API plus a Raspberry Pi 5 GPIO-driven RGB LED matrix panel for real-time visual feedback. This setup demonstrates sensor data collection, local processing, and real-time actuation in an AIoT system.

The AI component will use a lightweight local machine learning model to recognise conducting-related actions and infer musical intentions. Candidate action classes include downbeat, crescendo, decrescendo, cutoff, style switch, idle, tempo up, and tempo down. The system will not simply map a single movement to a fixed rule; instead, it will analyse movement features such as hand height, speed, trajectory, gesture duration, movement intensity, and Micro:bit acceleration signals to classify the user's intention. The recognised intention can then be translated into music parameters such as tempo, volume, energy, density, style, or segment control.

The software engineering deliverable will include a backend with a database. The backend will receive sensor data, store raw records and processed features, run or call the AI inference module, store prediction results, and generate music-control actions. The database will keep historical sensor data, gesture labels, prediction outputs, and actuation records. This allows the system to demonstrate not only real-time control, but also persistent IoT data storage and analysis.

The frontend application will be a web dashboard designed for roadshow demonstration. It will show the live camera or gesture status, real-time sensor values, AI prediction result, confidence or status indicator, current music state, selected style, and recent database records. The first version will focus on a reliable live dashboard. If time permits, an optional calibration or training-data collection page may be added so that users can record sample gestures and improve personalisation.

An optional enhancement is an uploaded song or score analysis module. This module is not part of the minimum core deliverable. If implemented, it may analyse a music file or score to detect tempo, beat points, sections, and energy changes, then generate adjustable control points for the user to conduct. This will be treated as an innovation extension after the core free-conducting mode is stable.

---

## [LIST OF ADDITIONAL EQUIPMENT]

The standard project equipment already includes two Micro:bit v2 boards, one Raspberry Pi 5 8GB board, one sensor kit, and Micro:bit battery holders. (An ESP32 board is also provided but will not be used — the Pi 5 directly drives the LED Matrix via GPIO, simplifying the architecture.) The following additional equipment is required for the proposed system:

1. USB webcam or Raspberry Pi Camera, for camera-based two-hand gesture capture.
2. Wrist straps, elastic bands, or Velcro bands, for attaching Micro:bit devices to the user's wrist, hand, or a conducting stick during demonstration.
3. One 16 x 64 RGB LED matrix panel if available; otherwise, two 8 x 32 RGB LED matrix panels, for real-time visual feedback and music visualisation when a gesture or music-control action is recognised.

Suggested sourcing websites: Cytron Singapore, element14, SGBotic, Shopee Singapore, or RS Singapore.
