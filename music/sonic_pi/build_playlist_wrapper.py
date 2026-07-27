"""Build the five-track Sonic Pi playlist conductor from the song sources.

All five songs run inside one Sonic Pi run. Each source is namespaced with a
piece prefix so defines, event arrays and state keys cannot collide. An
:active_piece gate freezes and silences every song except the selected one.

Ownership split:
  - song files    -> score playback and self-gated feedback
  - wrapper file  -> every /conductor/* command, ACK/idempotency, track switch

:playing stays a GLOBAL (unprefixed) key: start/stop conduct whichever
song is active. Switching songs freezes and later resumes each score with its
own layer/style/BPM memory.

Outputs (all pure ASCII, regenerate after editing the sources):
  build/aiot_track_*.rb          - namespaced song files
  build/aiot_conductor_playlist.rb - playlist command owner

Usage:  python build_playlist_wrapper.py
Then:   ruby -c each output (Sonic Pi bundled ruby works).
The loader should run_file the playlist wrapper, not an individual song.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD_DIR = HERE / "build"

PIECES = {
    "soy": {
        "source": HERE / "aiot_conductor_shape_of_you.rb",
        "output": BUILD_DIR / "aiot_track_soy.rb",
        "piece_name": "shape_of_you",
        "track_args": ('"shape_of_you"', '"Shape of You (Ed Sheeran)"',
                       '"C# Minor"', "93", "4", "96"),
        "styles": ["acoustic_pop", "tropical_house", "festival_edm"],
        "rhythm_gate": True,
        "reset": [
            ("current_bpm", "96.0"),
            ("target_bpm", "96.0"),
            ("master_amp", "0.44"),
            ("target_master_amp", "0.44"),
            ("current_style", ":acoustic_pop"),
            ("layer_melody", "true"),
            ("layer_harmony", "true"),
            ("layer_bass", "true"),
            ("layer_rhythm", "true"),
        ],
    },
    "wim": {
        "source": HERE / "aiot_conductor_world_is_mine.rb",
        "output": BUILD_DIR / "aiot_track_wim.rb",
        "piece_name": "world_is_mine",
        "track_args": ('"world_is_mine"', '"World is Mine (Hatsune Miku)"',
                       '"Unknown"', "140", "4", "132"),
        "styles": ["piano_pop", "vocaloid_electro", "rock_band"],
        "rhythm_gate": True,
        "reset": [
            ("current_bpm", "132.0"),
            ("target_bpm", "132.0"),
            ("master_amp", "0.43"),
            ("target_master_amp", "0.43"),
            ("current_style", ":piano_pop"),
            ("layer_melody", "true"),
            ("layer_harmony", "true"),
            ("layer_bass", "true"),
            ("layer_rhythm", "true"),
        ],
    },
    "faded": {
        "source": HERE / "aiot_conductor_faded.rb",
        "output": BUILD_DIR / "aiot_track_faded.rb",
        "piece_name": "faded",
        "track_args": ('"faded"', '"Faded (Alan Walker)"',
                       '"F Minor"', "78", "4", "90"),
        "styles": ["piano_ballad", "synthwave", "festival"],
        "rhythm_gate": False,
        "reset": [
            ("current_bpm", "90.0"),
            ("target_bpm", "90.0"),
            ("master_amp", "0.46"),
            ("target_master_amp", "0.46"),
            ("current_style", ":piano_ballad"),
            ("layer_melody", "true"),
            ("layer_harmony", "true"),
            ("layer_bass", "true"),
            ("layer_rhythm", "true"),
        ],
    },
    "lemon": {
        "source": HERE / "aiot_conductor_lemon.rb",
        "output": BUILD_DIR / "aiot_track_lemon.rb",
        "piece_name": "lemon",
        "track_args": ('"lemon"', '"Lemon (Kenshi Yonezu)"',
                       '"Unknown"', "93", "4", "87"),
        "styles": [
            "acoustic_ballad", "modern_pop", "cinematic_rock", "lofi_night",
        ],
        "rhythm_gate": True,
        "reset": [
            ("current_bpm", "87.0"),
            ("target_bpm", "87.0"),
            ("master_amp", "0.38"),
            ("target_master_amp", "0.38"),
            ("current_style", ":acoustic_ballad"),
            ("layer_melody", "true"),
            ("layer_harmony", "true"),
            ("layer_bass", "true"),
            ("layer_rhythm", "true"),
        ],
    },
    "rolling": {
        "source": HERE / "aiot_conductor_rolling_girl.rb",
        "output": BUILD_DIR / "aiot_track_rolling.rb",
        "piece_name": "rolling_girl",
        "track_args": ('"rolling_girl"', '"Rolling Girl (Hatsune Miku)"',
                       '"Unknown"', "77", "4", "98"),
        "styles": [
            "piano_drama", "electro_punk", "vocaloid_rock", "lofi_breakbeat",
        ],
        "rhythm_gate": True,
        "reset": [
            ("current_bpm", "98.0"),
            ("target_bpm", "98.0"),
            ("master_amp", "0.34"),
            ("target_master_amp", "0.34"),
            ("current_style", ":piano_drama"),
            ("layer_melody", "true"),
            ("layer_harmony", "true"),
            ("layer_bass", "true"),
            ("layer_rhythm", "true"),
        ],
    },
}

WRAPPER_RUN_FILES = {
    prefix: meta["output"].resolve().as_posix()
    for prefix, meta in PIECES.items()
}

# Timeline state keys that are per-song. :playing stays global.
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

# Same-named defines and top-level locals that would collide.
WORD_IDENTS = [
    "layer_enabled_for_role",
    "perform_event_track",
    "play_drum_event",
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
    "pickup_beats",
    "melody_events",
    "harmony_events",
    "bass_events",
    "rhythm_events",
]

CONTROL_RECEIVERS = [
    "osc_transport_receiver",
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

    # 6) The playlist wrapper owns every /conductor/* command.
    for receiver in CONTROL_RECEIVERS:
        text = _sub_count(
            r"^live_loop :" + prefix + r"_" + receiver + r" do\n.*?^end\n",
            "",
            text,
            1,
            f"{prefix}: strip {receiver}",
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

    # 7b2) Park inactive pieces with a low-frequency musical sleep. A previous
    #     build used sync :aiot_tick here; after a pause or song switch, many
    #     parked score threads could resume from stale logical time and Sonic Pi
    #     would kill them with "thread got too far behind time".
    text = _sub_count(
        r"(while \(get\(:playing\) != true\) or "
        r"\(get\(:active_piece\) != :" + prefix + r"\)\n[ \t]+)sleep 0\.25",
        r"\1sleep 0.5",
        text,
        1,
        f"{prefix}: slow-park wait_until_playing",
    )
    text = _sub_count(
        r"(else\n[ \t]+)sleep 0\.25",
        r"\1sleep 0.5",
        text,
        1,
        f"{prefix}: slow-park wait_music_beats",
    )

    # NOTE: an earlier revision rewrote the musical waits here to
    # "real-time seconds" (use_real_time + sleep step*60/BPM). That was
    # WRONG and has been reverted: in Sonic Pi, sleep's arg is always in
    # BEATS (converted via the thread's current bpm) and use_real_time
    # merely sets sched_ahead=0 -- so track threads lost their 0.75 s
    # schedule-ahead (scsynth "late" spam) and bpm-mode threads got wrong
    # durations. Virtual-mode sleeps are already deadline-based and
    # jitter-immune (see core.rb sleep: fatal only when >sat+1 s behind).

    # 7c) note gate: never voice a note while inactive
    text = _sub_count(
        r"if " + prefix + r"_layer_enabled_for_role role",
        "if (" + prefix + "_layer_enabled_for_role role) "
        "and (get(:active_piece) == :" + prefix + ")",
        text,
        1,
        f"{prefix}: gate play_voice_event",
    )

    # 7d) drum gate. Faded gates all roles in perform_event_track instead.
    if meta["rhythm_gate"]:
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

    header_comment = (
        "# GENERATED FILE -- DO NOT EDIT\n"
        f"# Built by build_playlist_wrapper.py from {meta['source'].name}\n"
        f"# Piece prefix: {prefix}_ (defines, state keys, live_loops, locals).\n"
        "# Silent + frozen unless get(:active_piece) == :" + prefix + ".\n"
        "# /conductor/* is owned by aiot_conductor_playlist.rb.\n"
        "# Regenerate after editing the source: python build_playlist_wrapper.py\n"
        "\n"
    )
    return header_comment + text


WRAPPER_TEMPLATE = '''# GENERATED FILE -- DO NOT EDIT (build_playlist_wrapper.py)
# AIoT Smart Conducting -- five-track internal Sonic Pi playlist.

use_debug false
use_cue_logging false
use_osc "127.0.0.1", 4561
set_sched_ahead_time! 2.0
GC.disable

set :playlist_epoch, (Time.now.to_f * 1000000).to_i
set :playlist_dead, false
set :playlist_command_results, []
set :playlist_order, __PIECE_ORDER__
set :playing, false
set :active_piece, :none

__RUN_FILES__

set :active_piece, :soy
set :playing, false

define :playlist_clamp do |value, low, high|
  [[value.to_f, low].max, high].min
end

define :playlist_state_key do |piece, suffix|
  (piece.to_s + "_" + suffix.to_s).to_sym
end

define :playlist_cached_result do |command_id|
  command_text = command_id.to_s
  match = (get(:playlist_command_results) || []).find do |entry|
    entry[0] == command_text
  end
  match ? match[1] : nil
end

define :playlist_finish_command do |command_id, result|
  command_text = command_id.to_s
  result_text = result.to_s
  recent = (get(:playlist_command_results) || []).reject do |entry|
    entry[0] == command_text
  end
  set :playlist_command_results,
      ([[command_text, result_text]] + recent)[0, 64]
  osc "/music/ack", command_text, result_text
end

define :playlist_piece_name do |piece|
__PIECE_NAME_CASES__
end

define :playlist_style_order do |piece|
__STYLE_CASES__
end

define :playlist_track_feedback do |piece|
__TRACK_FEEDBACK__
end

define :playlist_layers_feedback do |piece|
  osc "/music/layers",
      get(playlist_state_key(piece, "layer_melody")) == true ? 1 : 0,
      get(playlist_state_key(piece, "layer_harmony")) == true ? 1 : 0,
      get(playlist_state_key(piece, "layer_bass")) == true ? 1 : 0,
      get(playlist_state_key(piece, "layer_rhythm")) == true ? 1 : 0
end

define :playlist_report_active do
  piece = get(:active_piece)
  playlist_track_feedback piece
  playlist_layers_feedback piece
  osc "/music/style", playlist_piece_name(piece),
      get(playlist_state_key(piece, "current_style")).to_s
end

define :playlist_reset_piece do |piece|
__RESET_CASES__
end

define :playlist_resolve_style do |piece, requested_style|
  order = playlist_style_order piece
  requested = requested_style.to_s.downcase
  current = get(playlist_state_key(piece, "current_style"))
  current_index = order.index(current) || 0
  if ["previous", "prev"].include?(requested)
    order[(current_index - 1) % order.length]
  elsif requested == "next"
    order[(current_index + 1) % order.length]
  elsif requested == "piano"
    order[0]
  elsif requested == "strings"
    order[[1, order.length - 1].min]
  elsif requested == "brass"
    order[[2, order.length - 1].min]
  elsif order.include?(requested.to_sym)
    requested.to_sym
  else
    nil
  end
end

define :playlist_apply_style do |piece, requested_style|
  selected = playlist_resolve_style piece, requested_style
  if selected
    set playlist_state_key(piece, "current_style"), selected
    osc "/music/style", playlist_piece_name(piece), selected.to_s
  end
  selected
end

live_loop :playlist_transport_receiver do
  use_real_time
  command_id, action = sync "/osc*/conductor/transport"
  if get(:playlist_dead) != true
    cached = playlist_cached_result command_id
    if cached
      osc "/music/ack", command_id, cached
    else
      action_text = action.to_s.downcase
      if ["start", "resume", "play"].include?(action_text)
        set :playing, true
        result = "transport:#{action_text}"
      elsif ["pause", "stop", "cutoff"].include?(action_text)
        set :playing, false
        result = "transport:#{action_text}"
      elsif action_text == "reset"
        playlist_reset_piece get(:active_piece)
        set :playing, true
        result = "transport:reset"
      elsif ["next", "previous", "prev"].include?(action_text)
        order = get(:playlist_order)
        old_piece = get(:active_piece)
        old_index = order.index(old_piece) || 0
        offset = action_text == "next" ? 1 : -1
        new_piece = order[(old_index + offset) % order.length]
        set :active_piece, new_piece
        cue :aiot_tick
        result = "transport:#{action_text}:#{new_piece}"
      else
        result = "transport_unsupported:#{action_text}"
      end
      playlist_report_active
      playlist_finish_command command_id, result
    end
  end
end

live_loop :playlist_state_receiver do
  use_real_time
  command_id, bpm, master_amp, drum_amp, drum_density,
    bass_amp, harmony_amp, melody_amp, energy,
    reverb_mix, cutoff, requested_style = sync "/osc*/conductor/state"
  if get(:playlist_dead) != true
    cached = playlist_cached_result command_id
    if cached
      osc "/music/ack", command_id, cached
    else
      piece = get(:active_piece)
      set playlist_state_key(piece, "target_bpm"),
          playlist_clamp(bpm, 60, 150)
      set playlist_state_key(piece, "target_master_amp"),
          playlist_clamp(master_amp, 0.0, 1.0)
      playlist_apply_style piece, requested_style
      playlist_finish_command command_id, "state"
    end
  end
end

live_loop :playlist_bpm_receiver do
  use_real_time
  command_id, bpm = sync "/osc*/conductor/bpm"
  if get(:playlist_dead) != true
    cached = playlist_cached_result command_id
    if cached
      osc "/music/ack", command_id, cached
    else
      piece = get(:active_piece)
      target = playlist_clamp(bpm, 60, 150)
      set playlist_state_key(piece, "target_bpm"), target
      playlist_finish_command command_id, "bpm:#{target.round(1)}"
    end
  end
end

live_loop :playlist_volume_receiver do
  use_real_time
  command_id, volume = sync "/osc*/conductor/volume"
  if get(:playlist_dead) != true
    cached = playlist_cached_result command_id
    if cached
      osc "/music/ack", command_id, cached
    else
      piece = get(:active_piece)
      target = playlist_clamp(volume, 0.0, 1.0)
      set playlist_state_key(piece, "target_master_amp"), target
      playlist_finish_command command_id, "volume:#{target.round(2)}"
    end
  end
end

live_loop :playlist_style_receiver do
  use_real_time
  command_id, requested_style = sync "/osc*/conductor/style"
  if get(:playlist_dead) != true
    cached = playlist_cached_result command_id
    if cached
      osc "/music/ack", command_id, cached
    else
      piece = get(:active_piece)
      selected = playlist_apply_style piece, requested_style
      if selected
        sample :elec_blip2, amp: 0.18
        result = "style:#{selected}"
      else
        result = "style_unsupported:#{requested_style}"
      end
      playlist_finish_command command_id, result
    end
  end
end

live_loop :playlist_layer_receiver do
  use_real_time
  command_id, requested_layer, enabled = sync "/osc*/conductor/layer"
  if get(:playlist_dead) != true
    cached = playlist_cached_result command_id
    if cached
      osc "/music/ack", command_id, cached
    else
      layer_text = requested_layer.to_s.downcase
      layer_text = "rhythm" if layer_text == "drums"
      enabled_value = !["0", "0.0", "false", "off"].include?(
        enabled.to_s.downcase
      )
      if ["melody", "harmony", "bass", "rhythm"].include?(layer_text)
        piece = get(:active_piece)
        set playlist_state_key(piece, "layer_" + layer_text), enabled_value
        playlist_layers_feedback piece
        result = "layer:#{layer_text}:#{enabled_value ? 'on' : 'off'}"
      else
        result = "layer_unsupported:#{layer_text}"
      end
      playlist_finish_command command_id, result
    end
  end
end

live_loop :playlist_accent_receiver do
  use_real_time
  command_id, strength, accent_type = sync "/osc*/conductor/accent"
  if get(:playlist_dead) != true
    piece = get(:active_piece)
    rhythm_enabled = get(playlist_state_key(piece, "layer_rhythm")) == true
    if get(:playing) == true && rhythm_enabled
      accent_amp = playlist_clamp(strength, 0.0, 1.2) *
        get(playlist_state_key(piece, "master_amp")).to_f
      accent_text = accent_type.to_s.downcase
      if ["downbeat", "bilateral_strike"].include?(accent_text)
        sample :bd_tek, amp: accent_amp * 0.9
        sample :drum_cymbal_closed, amp: accent_amp * 0.35,
               finish: 0.08
      else
        sample :drum_cymbal_closed, amp: accent_amp * 0.55,
               finish: 0.1
      end
    end
    osc "/music/ack", command_id, "accent"
  end
end

live_loop :playlist_ping_receiver do
  use_real_time
  command_id, = sync "/osc*/conductor/ping"
  if get(:playlist_dead) != true
    osc "/music/pong", command_id, get(:playlist_epoch)
  end
end

live_loop :playlist_track_reporter do
  use_real_time
  if get(:playlist_dead) != true
    playlist_track_feedback get(:active_piece)
    osc "/music/output", "internal"
  end
  sleep 1.0
end

live_loop :playlist_ticker do
  use_real_time
  cue :aiot_tick
  sleep 1.0
end

live_loop :playlist_reboot_watchdog do
  epoch = sync :playlist_reboot
  if epoch.to_i != get(:playlist_epoch).to_i
    set :playlist_dead, true
    set :playing, false
    set :active_piece, :none
  end
end

cue :playlist_reboot, get(:playlist_epoch)
playlist_report_active
set :playing, true
'''

SAFE_LOADER_TEMPLATE = '''# AIoT Smart Conducting -- generated safe loader
# Open this file in Sonic Pi and press Run exactly once.
# This stable entry loads one song only, avoiding the full playlist's many
# always-resident live_loops. Use this for live demos.

aiot_track = [
  \"__SAFE_TRACK_PATH__\",
  \"G:/code/AIoT/AIoT/music/sonic_pi/aiot_conductor_shape_of_you.rb\",
  \"D:/CC/AIoT/music/sonic_pi/aiot_conductor_shape_of_you.rb\",
].uniq.find { |path| File.exist?(path) }

if aiot_track
  run_file aiot_track
else
  puts \"AIOT LOADER ERROR: track file not found. Edit the paths in this loader.\"
end
'''

PLAYLIST_LOADER_TEMPLATE = '''# AIoT Smart Conducting -- generated playlist loader
# High-load five-track playlist. Use only for stress testing.
# Fully quit Sonic Pi before loading this after the safe loader.

aiot_playlist = [
  \"__WRAPPER_PATH__\",
  \"G:/code/AIoT/AIoT/music/sonic_pi/build/aiot_conductor_playlist.rb\",
  \"D:/CC/AIoT/music/sonic_pi/build/aiot_conductor_playlist.rb\",
].uniq.find { |path| File.exist?(path) }

if aiot_playlist
  run_file aiot_playlist
else
  puts \"AIOT LOADER ERROR: playlist file not found. Edit the paths in this loader.\"
end
'''


def _ruby_symbols(values: list[str]) -> str:
    return "[" + ", ".join(f":{value}" for value in values) + "]"


def _case_lines(expression: str, rows: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for index, (prefix, body) in enumerate(rows):
        keyword = "if" if index == 0 else "elsif"
        lines.append(f"  {keyword} {expression} == :{prefix}")
        lines.append(body)
    lines.extend(["  else", "    nil", "  end"])
    return "\n".join(lines)


def build_wrapper() -> str:
    run_files = "\n".join(
        f'run_file "{WRAPPER_RUN_FILES[prefix]}"' for prefix in PIECES
    )
    piece_order = _ruby_symbols(list(PIECES))
    piece_names = _case_lines(
        "piece",
        [
            (prefix, f'    "{meta["piece_name"]}"')
            for prefix, meta in PIECES.items()
        ],
    )
    style_cases = _case_lines(
        "piece",
        [
            (prefix, "    " + _ruby_symbols(meta["styles"]))
            for prefix, meta in PIECES.items()
        ],
    )
    track_cases = _case_lines(
        "piece",
        [
            (
                prefix,
                '    osc "/music/track", ' + ", ".join(meta["track_args"]),
            )
            for prefix, meta in PIECES.items()
        ],
    )

    reset_rows: list[tuple[str, str]] = []
    for prefix, meta in PIECES.items():
        body = "\n".join(
            f"    set :{prefix}_{key}, {value}" for key, value in meta["reset"]
        )
        reset_rows.append((prefix, body))
    reset_cases = _case_lines("piece", reset_rows)

    text = WRAPPER_TEMPLATE
    replacements = {
        "__RUN_FILES__": run_files,
        "__PIECE_ORDER__": piece_order,
        "__PIECE_NAME_CASES__": piece_names,
        "__STYLE_CASES__": style_cases,
        "__TRACK_FEEDBACK__": track_cases,
        "__RESET_CASES__": reset_cases,
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    leftovers = [
        line for line in text.splitlines()
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
        namespaced.encode("ascii")
        meta["output"].write_text(namespaced, encoding="ascii", newline="\n")
        outputs.append(meta["output"])
        print(f"built {meta['output'].name}: {len(namespaced)} bytes")

    wrapper = build_wrapper()
    wrapper.encode("ascii")
    wrapper_path = BUILD_DIR / "aiot_conductor_playlist.rb"
    wrapper_path.write_text(wrapper, encoding="ascii", newline="\n")
    outputs.append(wrapper_path)
    print(f"built {wrapper_path.name}: {len(wrapper)} bytes")

    playlist_loader = PLAYLIST_LOADER_TEMPLATE.replace(
        "__WRAPPER_PATH__", wrapper_path.resolve().as_posix()
    )
    playlist_loader.encode("ascii")
    playlist_loader_path = HERE / "aiot_loader_playlist.rb"
    playlist_loader_path.write_text(
        playlist_loader,
        encoding="ascii",
        newline="\n",
    )
    outputs.append(playlist_loader_path)
    print(
        f"built {playlist_loader_path.name}: "
        f"{len(playlist_loader)} bytes"
    )

    safe_track_path = PIECES["soy"]["source"].resolve().as_posix()
    loader = SAFE_LOADER_TEMPLATE.replace(
        "__SAFE_TRACK_PATH__", safe_track_path
    )
    loader.encode("ascii")
    loader_path = HERE / "aiot_loader.rb"
    loader_path.write_text(loader, encoding="ascii", newline="\n")
    outputs.append(loader_path)
    print(f"built {loader_path.name}: {len(loader)} bytes")

    print("\nnext: ruby -c each file, e.g.")
    for path in outputs:
        print(f'  ruby -c "{path}"')


if __name__ == "__main__":
    sys.exit(main())
