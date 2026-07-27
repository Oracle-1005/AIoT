# GENERATED FILE -- DO NOT EDIT (build_playlist_wrapper.py)
# AIoT Smart Conducting -- five-track internal Sonic Pi playlist.

use_debug false
use_cue_logging false
use_osc "127.0.0.1", 4561
set_sched_ahead_time! 1.0
GC.disable

set :playlist_epoch, (Time.now.to_f * 1000000).to_i
set :playlist_dead, false
set :playlist_command_results, []
set :playlist_order, [:soy, :wim, :faded, :lemon, :rolling]
set :playing, false
set :active_piece, :none

run_file "G:/code/AIoT/AIoT/music/sonic_pi/build/aiot_track_soy.rb"
run_file "G:/code/AIoT/AIoT/music/sonic_pi/build/aiot_track_wim.rb"
run_file "G:/code/AIoT/AIoT/music/sonic_pi/build/aiot_track_faded.rb"
run_file "G:/code/AIoT/AIoT/music/sonic_pi/build/aiot_track_lemon.rb"
run_file "G:/code/AIoT/AIoT/music/sonic_pi/build/aiot_track_rolling.rb"

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
  if piece == :soy
    "shape_of_you"
  elsif piece == :wim
    "world_is_mine"
  elsif piece == :faded
    "faded"
  elsif piece == :lemon
    "lemon"
  elsif piece == :rolling
    "rolling_girl"
  else
    nil
  end
end

define :playlist_style_order do |piece|
  if piece == :soy
    [:acoustic_pop, :tropical_house, :festival_edm]
  elsif piece == :wim
    [:piano_pop, :vocaloid_electro, :rock_band]
  elsif piece == :faded
    [:piano_ballad, :synthwave, :festival]
  elsif piece == :lemon
    [:acoustic_ballad, :modern_pop, :cinematic_rock, :lofi_night]
  elsif piece == :rolling
    [:piano_drama, :electro_punk, :vocaloid_rock, :lofi_breakbeat]
  else
    nil
  end
end

define :playlist_track_feedback do |piece|
  if piece == :soy
    osc "/music/track", "shape_of_you", "Shape of You (Ed Sheeran)", "C# Minor", 93, 4, 96
  elsif piece == :wim
    osc "/music/track", "world_is_mine", "World is Mine (Hatsune Miku)", "Unknown", 140, 4, 132
  elsif piece == :faded
    osc "/music/track", "faded", "Faded (Alan Walker)", "F Minor", 78, 4, 90
  elsif piece == :lemon
    osc "/music/track", "lemon", "Lemon (Kenshi Yonezu)", "Unknown", 93, 4, 87
  elsif piece == :rolling
    osc "/music/track", "rolling_girl", "Rolling Girl (Hatsune Miku)", "Unknown", 77, 4, 98
  else
    nil
  end
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
  if piece == :soy
    set :soy_current_bpm, 96.0
    set :soy_target_bpm, 96.0
    set :soy_master_amp, 0.44
    set :soy_target_master_amp, 0.44
    set :soy_current_style, :acoustic_pop
    set :soy_layer_melody, true
    set :soy_layer_harmony, true
    set :soy_layer_bass, true
    set :soy_layer_rhythm, true
  elsif piece == :wim
    set :wim_current_bpm, 132.0
    set :wim_target_bpm, 132.0
    set :wim_master_amp, 0.43
    set :wim_target_master_amp, 0.43
    set :wim_current_style, :piano_pop
    set :wim_layer_melody, true
    set :wim_layer_harmony, true
    set :wim_layer_bass, true
    set :wim_layer_rhythm, true
  elsif piece == :faded
    set :faded_current_bpm, 90.0
    set :faded_target_bpm, 90.0
    set :faded_master_amp, 0.46
    set :faded_target_master_amp, 0.46
    set :faded_current_style, :piano_ballad
    set :faded_layer_melody, true
    set :faded_layer_harmony, true
    set :faded_layer_bass, true
    set :faded_layer_rhythm, true
  elsif piece == :lemon
    set :lemon_current_bpm, 87.0
    set :lemon_target_bpm, 87.0
    set :lemon_master_amp, 0.38
    set :lemon_target_master_amp, 0.38
    set :lemon_current_style, :acoustic_ballad
    set :lemon_layer_melody, true
    set :lemon_layer_harmony, true
    set :lemon_layer_bass, true
    set :lemon_layer_rhythm, true
  elsif piece == :rolling
    set :rolling_current_bpm, 98.0
    set :rolling_target_bpm, 98.0
    set :rolling_master_amp, 0.34
    set :rolling_target_master_amp, 0.34
    set :rolling_current_style, :piano_drama
    set :rolling_layer_melody, true
    set :rolling_layer_harmony, true
    set :rolling_layer_bass, true
    set :rolling_layer_rhythm, true
  else
    nil
  end
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
  sleep 0.2
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
