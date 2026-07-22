# Sonic Pi Roadshow Music

This folder contains the roadshow music script for the AIoT Smart Conducting Performance System.

## Recommended Piece

`aiot_conductor_ode_to_joy.rb`

The piece is a Sonic Pi arrangement of the public-domain melody "Ode to Joy".
It is suitable for the project because it is recognizable, stable for live demos,
and easy to control with conducting gestures.

## How To Run

1. Open Sonic Pi on the PC.
2. Open `aiot_conductor_ode_to_joy.rb` in a text editor.
3. Copy the full script into a Sonic Pi buffer.
4. Press `Run`.

The script plays by itself, so it can be tested before the backend OSC adapter is ready.

## Future Backend Control

Detailed contract: `../../docs/SONIC_PI_OSC_CONTRACT.md`

The script already listens for the OSC paths planned in the design document:

```text
/conductor/transport command_id action
/conductor/state command_id bpm master_amp drum_amp drum_density bass_amp harmony_amp melody_amp energy reverb_mix cutoff
/conductor/bpm command_id bpm
/conductor/accent command_id strength type
```

It also sends basic feedback paths back to the PC backend:

```text
/music/beat
/music/bar
/music/state
/music/ack
```

When the backend Sonic Pi OSC adapter is added, these paths can be used without
rewriting the music script.
