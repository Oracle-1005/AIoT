# GENERATED FILE -- DO NOT EDIT (build_duo_wrapper.py)
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
set :active_piece, :soy

run_file "D:/CC/AIoT/music/sonic_pi/build/aiot_duo_soy.rb"
run_file "D:/CC/AIoT/music/sonic_pi/build/aiot_duo_wim.rb"

duo_piece_order = [:soy, :wim]

define :duo_track_feedback do |piece|
  if piece == :wim
    osc "/music/track", "world_is_mine", "World is Mine (Hatsune Miku)", "Unknown", 140, 4, 132
  else
    osc "/music/track", "shape_of_you", "Shape of You (Ed Sheeran)", "C# Minor", 93, 4, 96
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
      set :wim_current_bpm, 132.0
      set :wim_target_bpm, 132.0
      set :wim_master_amp, 0.50
      set :wim_target_master_amp, 0.50
      set :wim_current_style, :rock_band
      set :wim_layer_melody, true
      set :wim_layer_harmony, true
      set :wim_layer_bass, true
      set :wim_layer_rhythm, true
    else
      # score defaults from aiot_conductor_shape_of_you.rb (reset branch)
      set :soy_current_bpm, 96.0
      set :soy_target_bpm, 96.0
      set :soy_master_amp, 0.52
      set :soy_target_master_amp, 0.52
      set :soy_current_style, :tropical_house
      set :soy_layer_melody, true
      set :soy_layer_harmony, true
      set :soy_layer_bass, true
      set :soy_layer_rhythm, true
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
