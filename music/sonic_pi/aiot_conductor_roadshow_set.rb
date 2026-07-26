# AIoT Smart Conducting Performance System
# Sonic Pi roadshow set: From the New World (layer-conducting demo) + Ode to Joy + Canon in D
#
# Recommended for the roadshow:
# - Paste aiot_loader.rb (NOT this file) into Sonic Pi and press Run; this file is
#   then read from disk via run_file. (Sonic Pi's Run path truncates any buffer
#   whose OSC packet exceeds 16384 bytes -- this file is ~20 KB and would never start.)
# - After editing this file, just press Run again; no re-paste needed.
# - The set starts with From the New World and keeps looping.
# - Frontend Previous / Next buttons switch tracks in a loop.
#
# OSC control from the PC backend:
# /conductor/transport command_id action
#   action: start, resume, play, pause, stop, cutoff, reset, next, previous
# /conductor/state command_id bpm master_amp drum_amp drum_density bass_amp harmony_amp melody_amp energy reverb_mix cutoff [style]
#   style (optional 12th arg): piano / strings / brass -- cycled by the micro:bit right-A style_switch button
# /conductor/bpm command_id bpm
# /conductor/accent command_id strength type
# /conductor/layer command_id layer enabled
#   layer: melody / harmony / bass / drums; enabled: 0/1 -- hard layer gate (instant on/off, bypasses the smoother)
#
# OSC feedback to the PC backend:
# /music/track piece_id title key total_bars beats_per_bar default_bpm
# /music/beat bar beat bpm beat_strength
# /music/bar bar section
# /music/state playing bpm section energy
# /music/layers melody harmony bass drums   (0/1 per layer, every 0.5s)
# /music/ack command_id result

use_debug false
use_cue_logging false
use_osc "127.0.0.1", 4561

set :piece_order, [:new_world, :ode_to_joy, :canon_in_d]
set :piece_index, 0
set :piece_id, :new_world
set :playing, true
set :style, "piano"  # style_switch cycle: piano -> strings -> brass
set :beats_per_bar, 4
# Hard layer gates (via /conductor/layer, 1=on 0=off; independent of *_amp, state messages cannot override them)
set :layer_melody_on, true
set :layer_harmony_on, true
set :layer_bass_on, true
set :layer_drums_on, true

# -- From the New World: Dvorak Symphony No.9, IV. Allegro con fuoco (conductor arrangement) --
# Melody: one eighth note per beat, 32 notes = 8-bar theme; one chord every 2 beats, 16 chords fill the 8-bar loop
# loop_total_bars=8 -> current_section is always :finale, keeping the whole piece at high energy
set :new_world_title, "From the New World (Dvorak 9, IV. Allegro con fuoco)"
set :new_world_key, "E Minor"
set :new_world_bpm, 138.0
set :new_world_loop_total_bars, 8
set :new_world_master_amp, 0.85
set :new_world_drum_amp, 0.85
set :new_world_drum_density, 0.75
set :new_world_bass_amp, 0.7
set :new_world_harmony_amp, 0.6
set :new_world_melody_amp, 0.9
set :new_world_energy, 0.78
set :new_world_reverb_mix, 0.3
set :new_world_cutoff, 110.0
set :new_world_melody_notes, [
  # Theme A (bars 1-4): opening tutti hit + stepwise motif + dominant preparation
  :e4, :e4, :e3, :e3,  :e4, :d4, :c4, :b3,
  :a3, :b3, :c4, :d4,  :b3, :b3, :b3, :b3,
  # Theme B (bars 5-8): leaping fanfare + dominant half cadence (loop back into theme A)
  :e4, :g4, :e4, :b3,  :a3, :b3, :a3, :g3,
  :e4, :g4, :b4, :e5,  :b4, :b4, :b4, :b4
]
set :new_world_chords, [
  chord(:e2, :minor), chord(:e2, :minor),   # bar 1
  chord(:e2, :minor), chord(:e2, :minor),   # bar 2
  chord(:a2, :minor), chord(:c3, :major),   # bar 3
  chord(:b2, :major), chord(:b2, :major),   # bar 4
  chord(:c3, :major), chord(:g2, :major),   # bar 5
  chord(:a2, :minor), chord(:e2, :minor),   # bar 6
  chord(:c3, :major), chord(:a2, :minor),   # bar 7
  chord(:b2, :major), chord(:b2, :major)    # bar 8
]

set :ode_to_joy_title, "Ode to Joy Conductor Mix"
set :ode_to_joy_key, "C Major"
set :ode_to_joy_bpm, 108.0
set :ode_to_joy_loop_total_bars, 24
set :ode_to_joy_master_amp, 0.8
set :ode_to_joy_drum_amp, 0.75
set :ode_to_joy_drum_density, 0.7
set :ode_to_joy_bass_amp, 0.55
set :ode_to_joy_harmony_amp, 0.45
set :ode_to_joy_melody_amp, 0.85
set :ode_to_joy_energy, 0.62
set :ode_to_joy_reverb_mix, 0.25
set :ode_to_joy_cutoff, 95.0
set :ode_to_joy_melody_notes, [
  :e4, :e4, :f4, :g4, :g4, :f4, :e4, :d4,
  :c4, :c4, :d4, :e4, :e4, :d4, :d4, nil,
  :e4, :e4, :f4, :g4, :g4, :f4, :e4, :d4,
  :c4, :c4, :d4, :e4, :d4, :c4, :c4, nil,
  :d4, :d4, :e4, :c4, :d4, :e4, :f4, :e4,
  :c4, :d4, :e4, :f4, :e4, :d4, :c4, :d4,
  :g3, nil, :e4, :e4, :f4, :g4, :g4, :f4,
  :e4, :d4, :c4, :c4, :d4, :e4, :d4, :c4
]
set :ode_to_joy_chords, [
  chord(:c3, :major),
  chord(:g2, :major),
  chord(:a2, :minor),
  chord(:f2, :major),
  chord(:c3, :major),
  chord(:g2, :major),
  chord(:f2, :major),
  chord(:c3, :major)
]

set :canon_in_d_title, "Canon in D Conductor Mix"
set :canon_in_d_key, "D Major"
set :canon_in_d_bpm, 96.0
set :canon_in_d_loop_total_bars, 32
set :canon_in_d_master_amp, 0.8
set :canon_in_d_drum_amp, 0.58
set :canon_in_d_drum_density, 0.45
set :canon_in_d_bass_amp, 0.62
set :canon_in_d_harmony_amp, 0.58
set :canon_in_d_melody_amp, 0.82
set :canon_in_d_energy, 0.55
set :canon_in_d_reverb_mix, 0.38
set :canon_in_d_cutoff, 102.0
set :canon_in_d_melody_notes, [
  :fs4, :e4, :d4, :cs4, :b3, :a3, :b3, :cs4,
  :d4, :a3, :b3, :fs3, :g3, :d3, :g3, :a3,
  :fs4, :g4, :a4, :fs4, :g4, :a4, :b4, :cs5,
  :d5, :cs5, :b4, :a4, :g4, :fs4, :g4, :e4,
  :fs4, :e4, :d4, :cs4, :d4, :e4, :fs4, :a4,
  :b4, :a4, :g4, :fs4, :e4, :d4, :e4, :cs4,
  :d4, :fs4, :a4, :d5, :cs5, :a4, :fs4, :e4,
  :d4, :a3, :b3, :fs3, :g3, :d3, :g3, :a3
]
set :canon_in_d_chords, [
  chord(:d3, :major),
  chord(:a2, :major),
  chord(:b2, :minor),
  chord(:fs2, :minor),
  chord(:g2, :major),
  chord(:d3, :major),
  chord(:g2, :major),
  chord(:a2, :major)
]

define :clamp do |value, low, high|
  [[value.to_f, low].max, high].min
end

define :approach do |current, target, amount|
  current + ((target - current) * amount)
end

# style -> melody synth (style_switch button cycle)
define :style_melody_synth do |style|
  case style.to_s
  when "strings"
    :prophet
  when "brass"
    :zawa
  else
    :pretty_bell
  end
end

define :piece_value do |name|
  get("#{get(:piece_id)}_#{name}".to_sym)
end

define :main_amp do
  get(:master_amp).to_f
end

define :playable? do
  get(:playing) == true
end

define :current_beat_number do
  (get(:beat_count).to_i % get(:beats_per_bar).to_i) + 1
end

define :loop_bar_number do
  total_bars = [get(:loop_total_bars).to_i, 1].max
  get(:bar_count).to_i % total_bars
end

define :current_section do
  bar = loop_bar_number
  total_bars = [get(:loop_total_bars).to_i, 1].max
  if bar < 4
    :intro
  elsif bar < (total_bars * 0.5).to_i
    :theme
  elsif bar < total_bars - 4
    :build
  else
    :finale
  end
end

define :section_gain do |intro_gain, theme_gain, build_gain, finale_gain|
  section = current_section
  if section == :intro
    intro_gain
  elsif section == :theme
    theme_gain
  elsif section == :build
    build_gain
  else
    finale_gain
  end
end

define :reset_sequence_ticks do
  tick_reset(:melody)
  tick_reset(:bass_chords)
  tick_reset(:harmony_chords)
end

define :report_music_track do
  osc "/music/track",
      get(:piece_id).to_s,
      piece_value(:title),
      piece_value(:key),
      get(:loop_total_bars).to_i,
      get(:beats_per_bar).to_i,
      piece_value(:bpm).to_f
end

define :report_music_state do
  set :section, current_section
  playing_flag = playable? ? 1 : 0
  osc "/music/state",
      playing_flag,
      get(:current_bpm).round(1),
      get(:section).to_s,
      get(:energy).round(2)
end

define :report_music_layers do
  osc "/music/layers",
      (get(:layer_melody_on) ? 1 : 0),
      (get(:layer_harmony_on) ? 1 : 0),
      (get(:layer_bass_on) ? 1 : 0),
      (get(:layer_drums_on) ? 1 : 0)
end

define :report_music_beat do |strength = 1.0|
  osc "/music/beat",
      get(:bar_count).to_i,
      current_beat_number,
      get(:current_bpm),
      strength
end

define :apply_piece_defaults do
  set :current_bpm, piece_value(:bpm).to_f
  set :target_bpm, piece_value(:bpm).to_f
  set :master_amp, piece_value(:master_amp).to_f
  set :target_master_amp, piece_value(:master_amp).to_f
  set :drum_amp, piece_value(:drum_amp).to_f
  set :target_drum_amp, piece_value(:drum_amp).to_f
  set :drum_density, piece_value(:drum_density).to_f
  set :target_drum_density, piece_value(:drum_density).to_f
  set :bass_amp, piece_value(:bass_amp).to_f
  set :target_bass_amp, piece_value(:bass_amp).to_f
  set :harmony_amp, piece_value(:harmony_amp).to_f
  set :target_harmony_amp, piece_value(:harmony_amp).to_f
  set :melody_amp, piece_value(:melody_amp).to_f
  set :target_melody_amp, piece_value(:melody_amp).to_f
  set :energy, piece_value(:energy).to_f
  set :target_energy, piece_value(:energy).to_f
  set :reverb_mix, piece_value(:reverb_mix).to_f
  set :target_reverb_mix, piece_value(:reverb_mix).to_f
  set :cutoff, piece_value(:cutoff).to_f
  set :target_cutoff, piece_value(:cutoff).to_f
  set :loop_total_bars, piece_value(:loop_total_bars).to_i
  set :section, :intro
  set :bar_count, 0
  set :beat_count, 0
  reset_sequence_ticks
end

define :select_piece do |index|
  order = get(:piece_order)
  safe_index = index.to_i % order.length
  set :piece_index, safe_index
  set :piece_id, order[safe_index]
  apply_piece_defaults
  report_music_track
  report_music_state
end

define :play_transport_start_now do
  if get(:piece_id) == :new_world
    sample :drum_tom_lo_hard, amp: 1.1 * main_amp, cutoff: 120
    use_synth :saw
    with_fx :reverb, mix: get(:reverb_mix), room: 0.7 do
      play :e4, release: 0.45, amp: 0.9 * main_amp, cutoff: get(:cutoff)
      play :e3, release: 0.45, amp: 0.7 * main_amp, cutoff: get(:cutoff)
    end
  elsif get(:piece_id) == :canon_in_d
    sample :elec_blip, amp: 0.5 * main_amp, rate: 0.75
    use_synth :pretty_bell
    with_fx :reverb, mix: get(:reverb_mix), room: 0.65 do
      play :d4, release: 0.55, amp: 0.8 * main_amp, cutoff: get(:cutoff)
    end
  else
    sample :bd_haus, amp: 1.05 * main_amp, cutoff: 120
    use_synth :blade
    with_fx :reverb, mix: get(:reverb_mix), room: 0.65 do
      play :e4, release: 0.35, amp: 0.8 * main_amp, cutoff: get(:cutoff)
    end
  end
end

select_piece 0
play_transport_start_now
report_music_beat 1.0

live_loop :osc_transport_receiver do
  use_real_time
  command_id, action = sync "/osc*/conductor/transport"
  action_text = action.to_s.downcase
  was_playing = playable?

  if ["start", "resume", "play"].include?(action_text)
    set :playing, true
    unless was_playing
      play_transport_start_now
      report_music_beat 1.0
    end
  elsif ["pause", "stop", "cutoff"].include?(action_text)
    set :playing, false
  elsif action_text == "reset"
    set :playing, true
    select_piece get(:piece_index)
    play_transport_start_now
    report_music_beat 1.0
  elsif ["next", "track_next", "next_track"].include?(action_text)
    set :playing, true
    select_piece get(:piece_index).to_i + 1
    play_transport_start_now
    report_music_beat 1.0
  elsif ["previous", "prev", "track_previous", "previous_track"].include?(action_text)
    set :playing, true
    select_piece get(:piece_index).to_i - 1
    play_transport_start_now
    report_music_beat 1.0
  end

  report_music_state
  osc "/music/ack", command_id, "transport:#{action_text}"
end

live_loop :osc_state_receiver do
  use_real_time
  command_id, bpm, master_amp, drum_amp, drum_density,
    bass_amp, harmony_amp, melody_amp, energy,
    reverb_mix, cutoff, style = sync "/osc*/conductor/state"

  set :target_bpm, clamp(bpm, 72, 148)
  set :target_master_amp, clamp(master_amp, 0.0, 1.3)
  set :target_drum_amp, clamp(drum_amp, 0.0, 1.3)
  set :target_drum_density, clamp(drum_density, 0.0, 1.0)
  set :target_bass_amp, clamp(bass_amp, 0.0, 1.2)
  set :target_harmony_amp, clamp(harmony_amp, 0.0, 1.2)
  set :target_melody_amp, clamp(melody_amp, 0.0, 1.3)
  set :target_energy, clamp(energy, 0.0, 1.0)
  set :target_reverb_mix, clamp(reverb_mix, 0.0, 0.9)
  set :target_cutoff, clamp(cutoff, 55, 130)
  set :style, style.to_s unless style.nil?  # old backends without the 12th arg keep current style
  osc "/music/ack", command_id, "state"
end

live_loop :osc_bpm_receiver do
  use_real_time
  command_id, bpm = sync "/osc*/conductor/bpm"
  set :target_bpm, clamp(bpm, 72, 148)
  osc "/music/ack", command_id, "bpm"
end

live_loop :osc_accent_receiver do
  use_real_time
  command_id, strength, accent_type = sync "/osc*/conductor/accent"
  cue :manual_accent, strength: clamp(strength, 0.0, 1.2), accent_type: accent_type.to_s
  osc "/music/ack", command_id, "accent"
end

live_loop :osc_layer_receiver do
  use_real_time
  command_id, layer, enabled = sync "/osc*/conductor/layer"
  # Hard layer cut: flip the gate boolean immediately; next note/sample obeys (no smoother involved)
  layer_key = "layer_#{layer.to_s}_on".to_sym
  if [:layer_melody_on, :layer_harmony_on, :layer_bass_on, :layer_drums_on].include?(layer_key)
    set layer_key, (enabled.to_f > 0.5)
  end
  report_music_layers
  osc "/music/ack", command_id, "layer:#{layer.to_s}"
end

live_loop :parameter_smoother do
  use_real_time
  set :current_bpm, approach(get(:current_bpm).to_f, get(:target_bpm).to_f, 0.18)
  set :master_amp, approach(get(:master_amp).to_f, get(:target_master_amp).to_f, 0.25)
  set :drum_amp, approach(get(:drum_amp).to_f, get(:target_drum_amp).to_f, 0.25)
  set :drum_density, approach(get(:drum_density).to_f, get(:target_drum_density).to_f, 0.25)
  set :bass_amp, approach(get(:bass_amp).to_f, get(:target_bass_amp).to_f, 0.25)
  set :harmony_amp, approach(get(:harmony_amp).to_f, get(:target_harmony_amp).to_f, 0.25)
  set :melody_amp, approach(get(:melody_amp).to_f, get(:target_melody_amp).to_f, 0.25)
  set :energy, approach(get(:energy).to_f, get(:target_energy).to_f, 0.25)
  set :reverb_mix, approach(get(:reverb_mix).to_f, get(:target_reverb_mix).to_f, 0.25)
  set :cutoff, approach(get(:cutoff).to_f, get(:target_cutoff).to_f, 0.25)
  sleep 0.5
end

live_loop :beat_clock do
  use_bpm get(:current_bpm)

  unless playable?
    sleep 0.1
    next
  end

  beat = current_beat_number
  bar = get(:bar_count).to_i
  set :section, current_section
  beat_strength = beat == 1 ? 1.0 : 0.45

  cue :beat, beat: beat, bar: bar, strength: beat_strength
  osc "/music/beat", bar, beat, get(:current_bpm), beat_strength

  if beat == get(:beats_per_bar).to_i
    set :bar_count, bar + 1
    set :section, current_section
    osc "/music/bar", bar + 1, get(:section).to_s
  end

  set :beat_count, get(:beat_count).to_i + 1
  sleep 1
end

live_loop :drums do
  data = sync :beat
  use_bpm get(:current_bpm)

  if playable? && get(:layer_drums_on)
    amp = get(:drum_amp).to_f * main_amp * section_gain(0.3, 0.72, 1.0, 1.16)
    energy = get(:energy).to_f
    density = get(:drum_density).to_f
    beat = data[:beat]
    section = current_section

    if get(:piece_id) == :new_world
      # Timpani / concert-bass-drum drive: heavy hits on beats 1+3, double tom flourish on beat 4
      sample :drum_tom_lo_hard, amp: amp * (beat == 1 ? 1.15 : 0.5), rate: 0.85 if beat == 1 || beat == 3
      sample :drum_tom_mid_hard, amp: amp * 0.5, rate: 0.9 if beat == 4
      sample :drum_tom_mid_hard, amp: amp * 0.62, rate: 0.72 if beat == 4
      sample :drum_cymbal_open, amp: amp * 0.5, sustain: 0.02, release: 0.3 if beat == 1
    elsif get(:piece_id) == :canon_in_d
      sample :bd_haus, amp: amp * (beat == 1 ? 0.95 : 0.38), cutoff: get(:cutoff) if section != :intro
      sample :sn_dub, amp: amp * (0.18 + density * 0.26), rate: 0.8 if section == :build && (beat == 2 || beat == 4)
      sample :drum_cymbal_closed, amp: amp * density * (0.16 + energy * 0.25), sustain: 0.01 if section != :intro || beat == 1
      sample :drum_cymbal_open, amp: amp * 0.38, sustain: 0.02, release: 0.16 if section == :finale && beat == 1
    else
      sample :bd_haus, amp: amp * (beat == 1 ? 1.35 : 0.75), cutoff: get(:cutoff)
      sample :sn_dub, amp: amp * (0.25 + density * 0.4) if section != :intro && (beat == 2 || beat == 4)
      sample :drum_cymbal_closed, amp: amp * density * (0.25 + energy * 0.35), sustain: 0.01 if section != :intro || beat == 1
      sample :drum_cymbal_open, amp: amp * 0.45, sustain: 0.02, release: 0.12 if section == :finale && beat == 1
    end
  end
end

live_loop :bass do
  use_bpm get(:current_bpm)

  if playable? && get(:layer_bass_on)
    next_chord = piece_value(:chords).tick(:bass_chords)
    root_note = next_chord[0]
    use_synth :fm
    with_fx :lpf, cutoff: get(:cutoff) do
      bass_level = get(:bass_amp).to_f * main_amp * section_gain(0.5, 0.82, 1.05, 1.16)
      if get(:piece_id) == :new_world
        # Bass strings staccato: root x3 + upper octave (2 beats)
        play root_note, release: 0.28, amp: bass_level, depth: 1.4
        sleep 0.5
        play root_note, release: 0.28, amp: bass_level * 0.8, depth: 1.4
        sleep 0.5
        play root_note, release: 0.28, amp: bass_level * 0.8, depth: 1.4
        sleep 0.5
        play root_note + 12, release: 0.3, amp: bass_level * 0.6, depth: 1.0
        sleep 0.5
      elsif get(:piece_id) == :canon_in_d
        play root_note, release: 0.55, amp: bass_level, depth: 1.2
        sleep 0.5
        play root_note + 12, release: 0.35, amp: bass_level * 0.46, depth: 0.7
        sleep 0.5
        play root_note + 7, release: 0.45, amp: bass_level * 0.58, depth: 0.8
        sleep 1
      else
        play root_note, release: 0.42, amp: bass_level, depth: 1.6
        sleep 0.5
        play root_note + 12, release: 0.24, amp: bass_level * 0.5, depth: 0.8
        sleep 0.5
        play root_note, release: 0.42, amp: bass_level * 0.75, depth: 1.2
        sleep 1
      end
    end
  else
    sleep 0.1
  end
end

live_loop :harmony do
  use_bpm get(:current_bpm)

  if playable? && get(:layer_harmony_on)
    current_chord = piece_value(:chords).tick(:harmony_chords)
    is_canon = get(:piece_id) == :canon_in_d
    harmony_synth = is_canon ? :hollow : :prophet
    harmony_room = is_canon ? 0.85 : 0.75
    harmony_sustain = is_canon ? 1.6 : 1.5
    harmony_release = is_canon ? 0.75 : 0.5
    use_synth harmony_synth
    with_fx :reverb, mix: get(:reverb_mix), room: harmony_room do
      if get(:piece_id) == :new_world
        # Orchestral hits: full chord on beat 1, off-beat stab on beat 2 (2-beat cycle)
        play current_chord, sustain: 0.22, release: 0.3,
             amp: get(:harmony_amp).to_f * main_amp * 1.1,
             cutoff: get(:cutoff)
        sleep 1.5
        play current_chord, sustain: 0.18, release: 0.24,
             amp: get(:harmony_amp).to_f * main_amp * 0.7,
             cutoff: get(:cutoff)
        sleep 0.5
      else
        play current_chord, sustain: harmony_sustain,
             release: harmony_release,
             amp: get(:harmony_amp).to_f * main_amp * section_gain(0.55, 0.82, 1.0, 1.08),
             cutoff: get(:cutoff)
        sleep 2
      end
    end
  else
    sleep 0.1
  end
end

live_loop :melody do
  use_bpm get(:current_bpm)

  if playable? && get(:layer_melody_on)
    note_value = piece_value(:melody_notes).tick(:melody)
    if note_value
      section = current_section
      note_to_play = section == :finale ? note(note_value) + 12 : note_value

      if get(:piece_id) == :new_world
        # Brass unison: saw octave double (new_world is always :finale, so no extra octave shift here)
        use_synth :saw
        with_fx :reverb, mix: get(:reverb_mix), room: 0.6 do
          play note_value, release: 0.42, sustain: 0.05,
               amp: get(:melody_amp).to_f * main_amp * 1.05,
               cutoff: get(:cutoff)
          play note(note_value) - 12, release: 0.42, sustain: 0.05,
               amp: get(:melody_amp).to_f * main_amp * 0.55,
               cutoff: get(:cutoff)
        end
      elsif get(:piece_id) == :canon_in_d
        melody_synth = section == :finale ? :blade : style_melody_synth(get(:style))
        use_synth melody_synth
        echo_phase = 0.5
        echo_decay = 1.6
        intro_mix = 0.08
        main_mix = 0.16
        room_size = 0.82
        release_time = 0.46
      else
        use_synth style_melody_synth(get(:style))
        echo_phase = 0.375
        echo_decay = 1.2
        intro_mix = 0.12
        main_mix = 0.18
        room_size = 0.65
        release_time = 0.35
      end

      # new_world already played inside its own fx branch; other pieces share this echo/reverb tail
      if get(:piece_id) != :new_world
        echo_mix = section == :intro ? intro_mix : main_mix
        with_fx :echo, phase: echo_phase, decay: echo_decay, mix: echo_mix do
          with_fx :reverb, mix: get(:reverb_mix), room: room_size do
            play note_to_play, release: release_time,
                 amp: get(:melody_amp).to_f * main_amp * section_gain(0.72, 0.94, 1.08, 1.18),
                 cutoff: get(:cutoff)
          end
        end
      end
    end
    sleep 0.5
  else
    sleep 0.1
  end
end

live_loop :manual_accent_player do
  data = sync :manual_accent

  if playable?
    strength = data[:strength].to_f
    accent_type = data[:accent_type].to_s
    is_canon = get(:piece_id) == :canon_in_d
    cymbal_amp = is_canon ? 0.55 : 0.7
    kick_amp = is_canon ? 0.85 : 1.1
    sample :drum_cymbal_open, amp: cymbal_amp * strength * main_amp, sustain: 0.03, release: 0.22
    sample :bd_haus, amp: kick_amp * strength * main_amp, cutoff: 120

    if accent_type.include?("right") || accent_type.include?("strike")
      accent_synth = is_canon ? :pluck : :tb303
      accent_note = is_canon ? :d3 : :c2
      use_synth accent_synth
      play accent_note, release: 0.24, amp: strength * main_amp, cutoff: 110
    end
  end
end

live_loop :state_reporter do
  use_real_time
  report_music_track
  report_music_state
  report_music_layers
  sleep 0.5
end
