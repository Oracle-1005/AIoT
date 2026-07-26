# Sonic Pi OSC Contract

This document defines the only extra interface required when the project uses
Sonic Pi as the live music execution engine.

Scope:

- No frontend REST field is removed.
- No existing Pi, Micro:bit, model, database, or LED protocol is changed.
- The backend only needs an additional OSC adapter after gesture recognition.

## Runtime Topology

```text
Camera + Micro:bit
        |
        v
Backend gesture pipeline
        |
        +--> REST/WebSocket state for frontend display
        |
        +--> OSC commands to Sonic Pi
```

Sonic Pi and the backend should run on the same PC during the roadshow.

| Direction | Protocol | Address | Purpose |
|---|---|---|---|
| Backend -> Sonic Pi | OSC over UDP | `127.0.0.1:4560` | Send transport, BPM, accent, and music state commands |
| Sonic Pi -> Backend | OSC over UDP | `127.0.0.1:4561` | Send beat, bar, current state, and command acknowledgements |

## Backend To Sonic Pi

### `/conductor/transport`

Transport controls playback.

```text
/conductor/transport command_id action
```

| Field | Type | Example | Notes |
|---|---|---|---|
| `command_id` | string | `cmd-0001` | Backend-generated id for ack matching |
| `action` | string | `start` | Supported: `start`, `resume`, `play`, `pause`, `stop`, `cutoff`, `reset`, `next`, `previous` |

### `/conductor/state`

Bulk state update for continuous parameters.

```text
/conductor/state command_id bpm master_amp drum_amp drum_density bass_amp harmony_amp melody_amp energy reverb_mix cutoff [style]
```

| Field | Range | Notes |
|---|---:|---|
| `bpm` | `72..148` | Target tempo; Sonic Pi smooths toward it |
| `master_amp` | `0.0..1.3` | Overall output level |
| `drum_amp` | `0.0..1.3` | Drum layer level |
| `drum_density` | `0.0..1.0` | Percussion activity and hi-hat intensity |
| `bass_amp` | `0.0..1.2` | Bass layer level |
| `harmony_amp` | `0.0..1.2` | Chord layer level |
| `melody_amp` | `0.0..1.3` | Main melody level |
| `energy` | `0.0..1.0` | Overall performance intensity |
| `reverb_mix` | `0.0..0.9` | Reverb mix |
| `cutoff` | `55..130` | Synth filter cutoff |
| `style` | `piano/strings/brass` | **Optional 12th arg (appended, additive).** Melody timbre; cycled by the micro:bit right-A `style_switch` button. Old receivers ignoring extra args keep working (Ruby parallel assignment discards it). |

### `/conductor/bpm`

Single-parameter BPM update.

```text
/conductor/bpm command_id bpm
```

Use this for `tempo_up`, `tempo_down`, or live beat-rate estimates.

### `/conductor/accent`

Triggers a one-shot accent, usually from a downbeat or wrist strike.

```text
/conductor/accent command_id strength type
```

| Field | Type | Example |
|---|---|---|
| `strength` | float | `0.9` |
| `type` | string | `right_wrist_strike` |

### `/conductor/layer`

Hard layer gate (2026-07-26, for the New World zone-conducting demo). Flips
the named layer's play gate **immediately** — bypasses the parameter
smoother, unlike amp fades. Independent of `/conductor/state` layer amps:
a muted layer stays muted across subsequent state sends.

```text
/conductor/layer command_id layer enabled
```

| Field | Type | Example |
|---|---|---|
| `layer` | string | `melody` — one of `melody`, `harmony`, `bass`, `drums` (the Shape of You script maps `drums` to its rhythm layer) |
| `enabled` | float | `1.0` = on, `0.0` = off |

### `/conductor/style`

Style preset switch (Shape of You: `acoustic_pop` / `tropical_house` / `festival_edm`;
World is Mine: `piano_pop` / `vocaloid_electro` / `rock_band` — all applied
per-note so the switch is audible immediately).

```text
/conductor/style command_id style
```

| Field | Type | Example |
|---|---|---|
| `style` | string | `next` — or `previous`, or a preset name |

## Sonic Pi To Backend

The provided Sonic Pi script sends these feedback paths.

| OSC path | Arguments | Purpose |
|---|---|---|
| `/music/track` | `piece_id, title, key, total_bars, beats_per_bar, default_bpm` | Current track metadata after startup or track switching |
| `/music/beat` | `bar, beat, bpm, beat_strength` | Beat-accurate feedback for frontend/LED display |
| `/music/bar` | `bar, section` | Section and bar counter |
| `/music/state` | `playing, bpm, section, energy` | Actual music execution state |
| `/music/layers` | `melody, harmony, bass, drums` | Layer gate states (0/1 each), every 0.5 s and after each `/conductor/layer` — rb is authoritative |
| `/music/style` | `track_id, style` | Current style preset (both roadshow scripts), every 0.5 s and after each `/conductor/style` — rb is authoritative |
| `/music/ack` | `command_id, result` | Command acknowledgement |

The backend should use `/music/state` as the most reliable source for the final
displayed BPM after Sonic Pi is connected. Before Sonic Pi is connected, the
frontend may keep using the backend-estimated value.

> **LED music panel (2026-07-26)**: the backend also forwards `/music/beat` and
> `/music/state` to the Pi LED chain as `music_beat`/`music_state` downlink
> messages (INTERFACE_CONTRACT §8.4) driving the music-reactive spectrum panel.
> No Sonic Pi script change is required.

## Gesture Mapping Recommendation

| Gesture or event | Backend action |
|---|---|
| `downbeat`, `left_wrist_strike`, `right_wrist_strike` | Send `/conductor/accent`; set `playing=true` |
| `tempo_up` | Increase target BPM and send `/conductor/bpm` |
| `tempo_down` | Decrease target BPM and send `/conductor/bpm` |
| `crescendo` | Increase `master_amp`, `melody_amp`, and `energy`; send `/conductor/state` |
| `decrescendo` | Decrease `master_amp` and `energy`; send `/conductor/state` |
| `cutoff`, `stop`, `gesture_end` | Send `/conductor/transport ... cutoff` or `pause` |
| `resume`, `gesture_start` | Send `/conductor/transport ... start` |

## Frontend Contract

The frontend does not talk to Sonic Pi directly. It should continue to consume
backend state through REST polling or WebSocket.

Minimum frontend music state:

```json
{
  "playing": true,
  "bpm": 108,
  "volume": 0.8,
  "style": "sonic_pi",
  "current_gesture": "downbeat"
}
```

Optional fields after the OSC adapter is added:

```json
{
  "energy": 0.62,
  "section": "main",
  "sonic_pi_connected": true,
  "last_beat": 3,
  "last_bar": 12
}
```

## Roadshow Script

Primary scripts (2026-07-26: all tracks now get layer conducting + style
switching; From the New World was dropped in favour of these):

```text
music/sonic_pi/aiot_conductor_shape_of_you.rb
music/sonic_pi/aiot_conductor_world_is_mine.rb
```

Two MIDI transcriptions with the OSC contract built in. Shape of You: 96 BPM,
374-beat loop, styles `acoustic_pop` / `tropical_house` / `festival_edm`.
World is Mine: 132 BPM, 560-beat loop, styles `piano_pop` / `vocaloid_electro`
/ `rock_band`. Both have four layer-gated sections (`melody` = lead, `harmony` =
hook/chords, `bass`, `rhythm` = percussion — the backend's `drums` name maps to
it, and both scripts parse the backend's float `0.0`/`1.0` enabled values).

**Do NOT paste the set itself into a Sonic Pi buffer.** Sonic Pi's Run button
ships the buffer to the engine as a single OSC packet, and the engine reads at
most **16384 bytes per packet** (`udp_server.rb` `recvfrom(16384)`) — anything
larger is silently truncated and never runs (`spider.log` shows
`undefined method '%' for nil` from `oscdecode.rb`).

Instead paste the tiny loader once:

```text
music/sonic_pi/aiot_loader.rb
```

The loader is one `run_file` call that reads the set from disk — no size limit
crosses the wire, and after editing the set you just press Run again (no
re-paste). rb source files must stay **pure ASCII** (they are read from disk
under the system encoding). The loader currently points at the Shape of You
set; edit its last line to run World is Mine instead (a dual-track conductor
wrapper is planned).

Legacy scripts (Ode to Joy / Canon in D / From the New World single-piece and
roadshow sets) were retired from the working tree on 2026-07-26; they remain
in git history (last present at commit `7488cb3`).
