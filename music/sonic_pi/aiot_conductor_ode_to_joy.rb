# AIoT Smart Conducting Performance System
# Sonic Pi roadshow piece: Ode to Joy Conductor Mix
#
# Why this piece:
# - Public-domain melody, safe for classroom roadshow use.
# - Simple, recognizable, and easy to hear when BPM / volume / accents change.
# - Designed to react to future backend OSC commands.
#
# How to use:
# 1. Open Sonic Pi.
# 2. Paste this whole file into one buffer.
# 3. Press Run. The piece starts immediately for a quick sound check.
# 4. Use the frontend Music Control Center to pause / resume it during the demo.
#
# Optional OSC commands from the PC backend:
# /conductor/transport command_id action
# /conductor/state command_id bpm master_amp drum_amp drum_density bass_amp harmony_amp melody_amp energy reverb_mix cutoff
# /conductor/bpm command_id bpm
# /conductor/accent command_id strength type

use_debug false
use_cue_logging false
use_osc "127.0.0.1", 4561

set :playing, true
set :current_bpm, 108.0
set :target_bpm, 108.0
set :master_amp, 0.8
set :target_master_amp, 0.8
set :drum_amp, 0.75
set :target_drum_amp, 0.75
set :drum_density, 0.7
set :target_drum_density, 0.7
set :bass_amp, 0.55
set :target_bass_amp, 0.55
set :harmony_amp, 0.45
set :target_harmony_amp, 0.45
set :melody_amp, 0.85
set :target_melody_amp, 0.85
set :energy, 0.62
set :target_energy, 0.62
set :reverb_mix, 0.25
set :target_reverb_mix, 0.25
set :cutoff, 95.0
set :target_cutoff, 95.0
set :section, :intro
set :bar_count, 0
set :beat_count, 0
set :loop_total_bars, 24

define :clamp do |value, low, high|
  [[value.to_f, low].max, high].min
end

define :approach do |current, target, amount|
  current + ((target - current) * amount)
end

define :main_amp do
  get(:master_amp).to_f
end

define :playable? do
  get(:playing) == true
end

define :current_beat_number do
  (get(:beat_count).to_i % 4) + 1
end

define :loop_bar_number do
  get(:bar_count).to_i % get(:loop_total_bars).to_i
end

define :current_section do
  bar = loop_bar_number
  if bar < 4
    :intro
  elsif bar < 12
    :theme
  elsif bar < 20
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

define :report_music_state do
  set :section, current_section
  osc "/music/state",
      playable? ? 1 : 0,
      get(:current_bpm).round(1),
      get(:section).to_s,
      get(:energy).round(2)
end

define :report_music_beat do |strength = 1.0|
  osc "/music/beat",
      get(:bar_count).to_i,
      current_beat_number,
      get(:current_bpm),
      strength
end

define :play_transport_start_now do
  sample :bd_haus, amp: 1.05 * main_amp, cutoff: 120
  use_synth :blade
  with_fx :reverb, mix: get(:reverb_mix), room: 0.65 do
    play :e4, release: 0.35, amp: 0.8 * main_amp, cutoff: get(:cutoff)
  end
end

melody_notes = [
  :e4, :e4, :f4, :g4, :g4, :f4, :e4, :d4,
  :c4, :c4, :d4, :e4, :e4, :d4, :d4, nil,
  :e4, :e4, :f4, :g4, :g4, :f4, :e4, :d4,
  :c4, :c4, :d4, :e4, :d4, :c4, :c4, nil,
  :d4, :d4, :e4, :c4, :d4, :e4, :f4, :e4,
  :c4, :d4, :e4, :f4, :e4, :d4, :c4, :d4,
  :g3, nil, :e4, :e4, :f4, :g4, :g4, :f4,
  :e4, :d4, :c4, :c4, :d4, :e4, :d4, :c4
]

chords = [
  chord(:c3, :major),
  chord(:g2, :major),
  chord(:a2, :minor),
  chord(:f2, :major),
  chord(:c3, :major),
  chord(:g2, :major),
  chord(:f2, :major),
  chord(:c3, :major)
]

play_transport_start_now

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
    set :current_bpm, 108.0
    set :target_bpm, 108.0
    set :bar_count, 0
    set :beat_count, 0
    set :section, :intro
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
    reverb_mix, cutoff = sync "/osc*/conductor/state"

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

  if beat == 4
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

  if playable?
    amp = get(:drum_amp).to_f * main_amp * section_gain(0.3, 0.72, 1.0, 1.16)
    energy = get(:energy).to_f
    density = get(:drum_density).to_f
    beat = data[:beat]
    section = current_section

    sample :bd_haus, amp: amp * (beat == 1 ? 1.35 : 0.75), cutoff: get(:cutoff)
    sample :sn_dub, amp: amp * (0.25 + density * 0.4) if section != :intro && [2, 4].include?(beat)
    sample :drum_cymbal_closed, amp: amp * density * (0.25 + energy * 0.35), sustain: 0.01 if section != :intro || beat == 1
    sample :drum_cymbal_open, amp: amp * 0.45, sustain: 0.02, release: 0.12 if section == :finale && beat == 1
  end
end

live_loop :bass do
  use_bpm get(:current_bpm)

  if playable?
    next_chord = chords.tick(:bass_chords)
    root_note = next_chord[0]
    use_synth :fm
    with_fx :lpf, cutoff: get(:cutoff) do
      bass_level = get(:bass_amp).to_f * main_amp * section_gain(0.5, 0.82, 1.05, 1.16)
      play root_note, release: 0.42, amp: bass_level, depth: 1.6
      sleep 0.5
      play root_note + 12, release: 0.24, amp: bass_level * 0.5, depth: 0.8
      sleep 0.5
      play root_note, release: 0.42, amp: bass_level * 0.75, depth: 1.2
      sleep 1
    end
  else
    sleep 0.1
  end
end

live_loop :harmony do
  use_bpm get(:current_bpm)

  if playable?
    current_chord = chords.tick(:harmony_chords)
    use_synth :prophet
    with_fx :reverb, mix: get(:reverb_mix), room: 0.75 do
      play current_chord, sustain: 1.5, release: 0.5,
           amp: get(:harmony_amp).to_f * main_amp * section_gain(0.55, 0.82, 1.0, 1.08),
           cutoff: get(:cutoff)
    end
    sleep 2
  else
    sleep 0.1
  end
end

live_loop :melody do
  use_bpm get(:current_bpm)

  if playable?
    note_value = melody_notes.tick(:melody)
    if note_value
      section = current_section
      note_to_play = section == :finale ? note(note_value) + 12 : note_value
      use_synth :blade
      with_fx :echo, phase: 0.375, decay: 1.2, mix: section == :intro ? 0.12 : 0.18 do
        with_fx :reverb, mix: get(:reverb_mix), room: 0.65 do
          play note_to_play, release: 0.35,
               amp: get(:melody_amp).to_f * main_amp * section_gain(0.72, 0.94, 1.08, 1.18),
               cutoff: get(:cutoff)
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
    sample :drum_cymbal_open, amp: 0.7 * strength * main_amp, sustain: 0.03, release: 0.2
    sample :bd_haus, amp: 1.1 * strength * main_amp, cutoff: 120

    if accent_type.include?("right") || accent_type.include?("strike")
      use_synth :tb303
      play :c2, release: 0.2, amp: strength * main_amp, cutoff: 110
    end
  end
end

live_loop :state_reporter do
  use_real_time
  report_music_state
  sleep 0.5
end
