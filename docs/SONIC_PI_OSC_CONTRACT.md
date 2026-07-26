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
| `layer` | string | `melody` — one of `melody`, `harmony`, `bass`, `drums` |
| `enabled` | float | `1.0` = on, `0.0` = off |

## Sonic Pi To Backend

The provided Sonic Pi script sends these feedback paths.

| OSC path | Arguments | Purpose |
|---|---|---|
| `/music/track` | `piece_id, title, key, total_bars, beats_per_bar, default_bpm` | Current track metadata after startup or track switching |
| `/music/beat` | `bar, beat, bpm, beat_strength` | Beat-accurate feedback for frontend/LED display |
| `/music/bar` | `bar, section` | Section and bar counter |
| `/music/state` | `playing, bpm, section, energy` | Actual music execution state |
| `/music/layers` | `melody, harmony, bass, drums` | Layer gate states (0/1 each), every 0.5 s and after each `/conductor/layer` — rb is authoritative |
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

Primary script:

```text
music/sonic_pi/aiot_conductor_roadshow_set.rb
```

**Do NOT paste the roadshow set directly into a Sonic Pi buffer.** Sonic Pi's Run
button ships the buffer to the engine as a single OSC packet, and the engine reads
at most **16384 bytes per packet** (`udp_server.rb` `recvfrom(16384)`). The roadshow
set is ~20 KB, so the packet is silently truncated and the run never starts
(`spider.log` shows `undefined method '%' for nil` from `oscdecode.rb`). The script
itself is also required to be **pure ASCII** (it is read from disk by the engine).

Instead paste the tiny loader once:

```text
music/sonic_pi/aiot_loader.rb
```

The loader is one `run_file` call that reads the roadshow set from disk — no size
limit crosses the wire, and after editing the set you just press Run again (no
re-paste).

It starts with From the New World (hard layer gates for the zone-conducting demo)
and lets the frontend switch tracks in a loop:

```text
From the New World -> Ode to Joy -> Canon in D -> From the New World -> ...
```

Single-piece scripts:

```text
music/sonic_pi/aiot_conductor_ode_to_joy.rb
music/sonic_pi/aiot_conductor_canon_in_d.rb
```

Paste one full Ruby script into Sonic Pi and press `Run`. The single-piece scripts
are small enough for direct paste; the roadshow loader and both single-piece
scripts can play standalone before backend OSC integration is ready, and they keep
the same OSC control paths.
