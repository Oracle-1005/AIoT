"""Build the dual-piece ("duo") Sonic Pi conductor from the two source scripts.

方案A (locked 2026-07-26 22:05): both pieces run inside ONE Sonic Pi run.
Each source script is namespaced with a piece prefix (soy_/wim_) so the 11
same-named defines, the top-level locals (style_order / loop_beats /
track_N_events) and the timeline state keys no longer collide; an
:active_piece gate freezes and silences whichever piece is not selected.

Ownership split:
  - piece files   -> /conductor/bpm, /conductor/volume, /conductor/state,
                     /conductor/style, /conductor/layer (applied only when
                     the piece is active), beat/state/layers reporting
                     (self-gated), the MIDI score itself (frozen when inactive)
  - wrapper file  -> /conductor/transport ONLY (start/stop/next/previous/
                     reset), /music/track feedback (on switch + 1 Hz align)

:playing stays a GLOBAL (unprefixed) key: start/stop conduct whichever
piece is active. Switching pieces pause/resumes each score mid-position
(per-piece layer/style/BPM memory - "不串").

Outputs (all pure ASCII, regenerate after editing the sources):
  build/aiot_duo_soy.rb     - Shape of You, namespaced soy_
  build/aiot_duo_wim.rb     - World is Mine, namespaced wim_
  build/aiot_conductor_duo.rb - wrapper: run_file both + transport owner

Usage:  python build_duo_wrapper.py
Then:   ruby -c each output (Sonic Pi bundled ruby works).
The loader (aiot_loader.rb) should run_file the wrapper, not a piece.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD_DIR = HERE / "build"

# Absolute paths baked into the generated wrapper (forward slashes for
# Sonic Pi on Windows). Fix here if the repo ever moves.
WRAPPER_RUN_FILES = {
    "soy": "D:/CC/AIoT/music/sonic_pi/build/aiot_duo_soy.rb",
    "wim": "D:/CC/AIoT/music/sonic_pi/build/aiot_duo_wim.rb",
}

PIECES = {
    "soy": {
        "source": HERE / "aiot_conductor_shape_of_you.rb",
        "output": BUILD_DIR / "aiot_duo_soy.rb",
        "piece_name": "shape_of_you",
        # /music/track feedback args - must match backend SONIC_PI_TRACKS.
        "track_args": ('"shape_of_you"', '"Shape of You (Ed Sheeran)"',
                       '"C# Minor"', "93", "4", "96"),
        # transport reset defaults, copied from the source's reset branch
        # (aiot_conductor_shape_of_you.rb live_loop :osc_transport_receiver).
        "reset": [
            ("current_bpm", "96.0"),
            ("target_bpm", "96.0"),
            ("master_amp", "0.52"),
            ("target_master_amp", "0.52"),
            ("current_style", ":tropical_house"),
            ("layer_melody", "true"),
            ("layer_harmony", "true"),
            ("layer_bass", "true"),
            ("layer_rhythm", "true"),
        ],
    },
    "wim": {
        "source": HERE / "aiot_conductor_world_is_mine.rb",
        "output": BUILD_DIR / "aiot_duo_wim.rb",
        "piece_name": "world_is_mine",
        "track_args": ('"world_is_mine"', '"World is Mine (Hatsune Miku)"',
                       '"Unknown"', "140", "4", "132"),
        "reset": [
            ("current_bpm", "132.0"),
            ("target_bpm", "132.0"),
            ("master_amp", "0.50"),
            ("target_master_amp", "0.50"),
            ("current_style", ":rock_band"),
            ("layer_melody", "true"),
            ("layer_harmony", "true"),
            ("layer_bass", "true"),
            ("layer_rhythm", "true"),
        ],
    },
}

# Timeline state keys that are per-piece. :playing stays global on purpose.
STATE_KEYS = [
    "target_master_amp",  # longest first so alternation never short-matches
    "target_bpm",
    "current_style",
    "current_bpm",
    "master_amp",
    "beat_count",
    "bar_count",
    "track_id",
    "layer_melody",
    "layer_harmony",
    "layer_bass",
    "layer_rhythm",
]

# Same-named defines (11) plus top-level locals that would collide.
WORD_IDENTS = [
    "layer_enabled_for_role",
    "perform_event_track",
    "play_rhythm_event",
    "wait_until_playing",
    "play_voice_event",
    "wait_music_beats",
    "approach_value",
    "report_layers",
    "report_state",
    "voice_config",
    "clamp_value",
    "style_order",
    "loop_beats",
]

# Piece receivers that must consume-but-ignore commands while inactive.
GATED_RECEIVERS = [
    "osc_state_receiver",
    "osc_bpm_receiver",
    "osc_volume_receiver",
    "osc_style_receiver",
    "osc_layer_receiver",
]


def _sub_count(pattern: str, repl: str, text: str, count: int,
               label: str, flags: int = 0) -> str:
    """regex sub with an exact-match-count assertion (fail the build loudly)."""
    new_text, n = re.subn(pattern, repl, text, flags=flags)
    if n != count:
        raise SystemExit(
            f"BUILD FAIL: {label}: expected {count} replacement(s), got {n}"
        )
    return new_text


def namespace_piece(prefix: str, meta: dict) -> str:
    source = meta["source"].read_text(encoding="ascii")
    piece_name = meta["piece_name"]

    # 1) per-piece timeline state keys:  set :current_bpm -> set :soy_current_bpm
    text = re.sub(
        r":(" + "|".join(STATE_KEYS) + r")\b",
        ":" + prefix + r"_\1",
        source,
    )

    # 2) same-named defines + top-level locals
    text = re.sub(
        r"\b(" + "|".join(WORD_IDENTS) + r")\b",
        prefix + r"_\1",
        text,
    )

    # 3) event arrays: track_3_events -> soy_track_3_events
    text = re.sub(
        r"\btrack_(\d+)_events\b",
        prefix + r"_track_\1_events",
        text,
    )

    # 4) live_loop names
    text = re.sub(
        r"\blive_loop(\s+):(\w+)",
        r"live_loop\1:" + prefix + r"_\2",
        text,
    )

    # 5) cue/sync symbols (OSC string args are untouched: they start with ")
    text = re.sub(
        r"\b(cue|sync)(\s+):(\w+)",
        r"\1\2:" + prefix + r"_\3",
        text,
    )

    # 6) transport receiver is stripped - the wrapper owns /conductor/transport.
    text = _sub_count(
        r"^live_loop :" + prefix + r"_osc_transport_receiver do\n.*?^end\n",
        "",
        text,
        1,
        f"{prefix}: strip transport receiver",
        flags=re.MULTILINE | re.DOTALL,
    )

    # 7) active-piece gates (injected AFTER namespacing so :active_piece and
    #    :playing stay global).

    # 7a) wait_until_playing: also wait while this piece is not active
    text = _sub_count(
        r"while get\(:playing\) != true",
        "while (get(:playing) != true) or (get(:active_piece) != :"
        + prefix + ")",
        text,
        1,
        f"{prefix}: gate wait_until_playing",
    )

    # 7b) wait_music_beats: freeze the score while inactive (spacing differs
    #     between the two sources, hence the flexible == match)
    text = _sub_count(
        r"if get\(:playing\) *== *true",
        "if (get(:playing) == true) and (get(:active_piece) == :"
        + prefix + ")",
        text,
        1,
        f"{prefix}: gate wait_music_beats",
    )

    # 7c) note gate: never voice a note while inactive
    text = _sub_count(
        r"if " + prefix + r"_layer_enabled_for_role role",
        "if (" + prefix + "_layer_enabled_for_role role) "
        "and (get(:active_piece) == :" + prefix + ")",
        text,
        1,
        f"{prefix}: gate play_voice_event",
    )

    # 7d) drum gate
    text = _sub_count(
        r"if get\(:" + prefix + r"_layer_rhythm\) *== *true",
        "if (get(:" + prefix + "_layer_rhythm) == true) "
        "and (get(:active_piece) == :" + prefix + ")",
        text,
        1,
        f"{prefix}: gate play_rhythm_event",
    )

    # 7e/7f) feedback self-gates: an inactive piece never reports state/layers
    for define_name in ("report_state", "report_layers"):
        pattern = (
            r"define :" + prefix + r"_" + define_name + r" do\n(.*?)\nend\n"
        )
        match = re.search(pattern, text, flags=re.DOTALL)
        if not match:
            raise SystemExit(
                f"BUILD FAIL: {prefix}: cannot locate {define_name} body"
            )
        body = match.group(1)
        wrapped = (
            f"define :{prefix}_{define_name} do\n"
            f"  if get(:active_piece) == :{prefix}\n"
            f"{body}\n"
            f"  end\n"
            f"end\n"
        )
        text = _sub_count(pattern, wrapped.replace("\\", "\\\\"), text, 1,
                          f"{prefix}: self-gate {define_name}",
                          flags=re.DOTALL)

    # 7g) state_reporter's direct /music/style osc (the only report that does
    #     not go through report_*): postfix gate
    text = _sub_count(
        r'osc "/music/style", "' + piece_name + r'", get\(:'
        + prefix + r'_current_style\)\.to_s',
        'osc "/music/style", "' + piece_name + '", get(:'
        + prefix + '_current_style).to_s if get(:active_piece) == :' + prefix,
        text,
        1,
        f"{prefix}: gate state_reporter style osc",
    )

    # 8) command receivers: sync always (consume), apply only when active.
    lines = text.split("\n")
    for receiver in GATED_RECEIVERS:
        header = f"live_loop :{prefix}_{receiver} do"
        try:
            start = lines.index(header)
        except ValueError:
            raise SystemExit(
                f"BUILD FAIL: {prefix}: receiver not found: {header}"
            )
        sync_idx = None
        for i in range(start + 1, len(lines)):
            if re.search(r'=\s*sync "/osc\*/conductor/', lines[i]):
                sync_idx = i
                break
            if lines[i] == "end":
                break
        if sync_idx is None:
            raise SystemExit(
                f"BUILD FAIL: {prefix}: sync line not found in {receiver}"
            )
        end_idx = None
        for i in range(sync_idx + 1, len(lines)):
            if lines[i] == "end":
                end_idx = i
                break
        if end_idx is None:
            raise SystemExit(
                f"BUILD FAIL: {prefix}: closing end not found in {receiver}"
            )
        lines = (
            lines[: sync_idx + 1]
            + [f"  if get(:active_piece) == :{prefix}"]
            + lines[sync_idx + 1 : end_idx]
            + ["  end"]
            + lines[end_idx:]
        )
    text = "\n".join(lines)

    header_comment = (
        "# GENERATED FILE -- DO NOT EDIT\n"
        f"# Built by build_duo_wrapper.py from {meta['source'].name}\n"
        f"# Piece prefix: {prefix}_ (defines, state keys, live_loops, locals).\n"
        "# Silent + frozen unless get(:active_piece) == :" + prefix + ".\n"
        "# /conductor/transport is owned by aiot_conductor_duo.rb.\n"
        "# Regenerate after editing the source: python build_duo_wrapper.py\n"
        "\n"
    )
    return header_comment + text


WRAPPER_TEMPLATE = '''# GENERATED FILE -- DO NOT EDIT (build_duo_wrapper.py)
# AIoT Smart Conducting -- DUO conductor: Shape of You + World is Mine in
# ONE Sonic Pi run. Only get(:active_piece) sounds; the other piece is
# frozen mid-score (pause/resume, per-piece layer/style/BPM memory).
#
#   /conductor/transport start|stop   -> global :playing (this wrapper)
#   /conductor/transport next|prev    -> switch :active_piece + /music/track
#   /conductor/transport reset        -> active piece back to score defaults
#   /conductor/bpm|volume|style|layer|state -> active piece only (piece-side)
#
# Load via aiot_loader.rb (the Run button OSC packet limit is 16384 bytes;
# this file and the two piece files are read from disk via run_file).

use_debug false
use_cue_logging false
use_osc "127.0.0.1", 4561
set_sched_ahead_time! 0.75

set :playing, true
set :active_piece, :__DEFAULT__

run_file "__SOY_PATH__"
run_file "__WIM_PATH__"

duo_piece_order = [:soy, :wim]

define :duo_track_feedback do |piece|
  if piece == :wim
    osc "/music/track", __WIM_TRACK_ARGS__
  else
    osc "/music/track", __SOY_TRACK_ARGS__
  end
end

define :duo_report_active do
  if get(:active_piece) == :wim
    wim_report_state
    osc "/music/style", "world_is_mine", get(:wim_current_style).to_s
    wim_report_layers
  else
    soy_report_state
    osc "/music/style", "shape_of_you", get(:soy_current_style).to_s
    soy_report_layers
  end
end

live_loop :duo_transport_receiver do
  use_real_time
  command_id, action = sync "/osc*/conductor/transport"
  action_text = action.to_s.downcase
  if ["start", "resume", "play"].include?(action_text)
    set :playing, true
    duo_report_active
    osc "/music/ack", command_id, "transport:#{action_text}"
  elsif ["pause", "stop", "cutoff"].include?(action_text)
    set :playing, false
    duo_report_active
    osc "/music/ack", command_id, "transport:#{action_text}"
  elsif ["next", "next_track", "previous", "prev", "previous_track"].include?(action_text)
    index = duo_piece_order.index(get(:active_piece)) || 0
    if ["previous", "prev", "previous_track"].include?(action_text)
      index = (index - 1) % duo_piece_order.length
    else
      index = (index + 1) % duo_piece_order.length
    end
    set :active_piece, duo_piece_order[index]
    duo_track_feedback get(:active_piece)
    duo_report_active
    osc "/music/ack", command_id, "transport:#{action_text}"
  elsif action_text == "reset"
    set :playing, true
    if get(:active_piece) == :wim
      # score defaults from aiot_conductor_world_is_mine.rb (reset branch)
__WIM_RESET__
    else
      # score defaults from aiot_conductor_shape_of_you.rb (reset branch)
__SOY_RESET__
    end
    duo_report_active
    osc "/music/ack", command_id, "transport:reset"
  else
    osc "/music/ack", command_id, "transport_unsupported:#{action_text}"
  end
end

# Keeps the backend aligned on the current track (heals any lost switch)
# and doubles as a liveness signal, 1 Hz.
live_loop :duo_track_reporter do
  use_real_time
  duo_track_feedback get(:active_piece)
  sleep 1.0
end
'''


def build_wrapper() -> str:
    text = WRAPPER_TEMPLATE
    text = text.replace("__DEFAULT__", "soy")
    text = text.replace("__SOY_PATH__", WRAPPER_RUN_FILES["soy"])
    text = text.replace("__WIM_PATH__", WRAPPER_RUN_FILES["wim"])
    for prefix, meta in PIECES.items():
        tag = "__" + prefix.upper()
        text = text.replace(tag + "_TRACK_ARGS__", ", ".join(meta["track_args"]))
        reset_lines = "\n".join(
            f"      set :{prefix}_{key}, {value}" for key, value in meta["reset"]
        )
        text = text.replace(tag + "_RESET__", reset_lines)
    if "__" in text.replace("# ", ""):
        leftovers = [
            line for line in text.split("\n")
            if "__" in line and not line.lstrip().startswith("#")
        ]
        if leftovers:
            raise SystemExit(f"BUILD FAIL: unfilled template slots: {leftovers}")
    return text


def main() -> None:
    BUILD_DIR.mkdir(exist_ok=True)
    outputs: list[Path] = []
    for prefix, meta in PIECES.items():
        namespaced = namespace_piece(prefix, meta)
        namespaced.encode("ascii")  # hard fail if anything non-ASCII crept in
        meta["output"].write_text(namespaced, encoding="ascii", newline="\n")
        outputs.append(meta["output"])
        print(f"built {meta['output'].name}: {len(namespaced)} bytes")

    wrapper = build_wrapper()
    wrapper.encode("ascii")
    wrapper_path = BUILD_DIR / "aiot_conductor_duo.rb"
    wrapper_path.write_text(wrapper, encoding="ascii", newline="\n")
    outputs.append(wrapper_path)
    print(f"built {wrapper_path.name}: {len(wrapper)} bytes")

    print("\nnext: ruby -c each file, e.g.")
    for path in outputs:
        print(f'  ruby -c "{path}"')


if __name__ == "__main__":
    sys.exit(main())
