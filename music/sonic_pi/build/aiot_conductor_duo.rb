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

# GC strategy: NO forced collections, EVER (verified 2026-07-27, three
# thread deaths in three runs). A forced major GC (GC.start, as the
# metronome tried today) stops the whole Ruby VM >1.75 s on this
# machine/heap; every track thread whose virtual sleep deadline lands
# inside the pause dies (TimingError at core.rb sleep). Two deaths in ONE
# run proved the pauses recur at every tick, not just at boot. GC.disable
# restores yesterday's 19/19-clean configuration; its known cost is heap
# growth ~100 MB/min (2.8 GB in 25 min, measured) -- handle that by
# restarting Sonic Pi between demo sets (~every 20-30 min, already in the
# demo playbook), never by calling GC.start.
GC.disable
# Boot parked: :playing flips true only at the BOTTOM of this file, after
# both pieces are loaded and every thread is parked on sync (sync-parked
# threads have no virtual deadline and cannot die, no matter what pause
# the OS throws at the load burst).
set :playing, false
set :active_piece, :soy
# Epoch fence against zombie run families. Sonic Pi v4.6 spawns one child
# run per run_file, and Stop/re-Run does NOT kill the previous family's
# run_file children -- they keep playing with their own Time-State store
# and their OSC receivers still fire (double music, phantom track reverts;
# diagnosed 2026-07-27). Cues are the only spider-global channel, so each
# new run broadcasts :duo_reboot with its epoch; older families whose
# stored epoch differs silence + gate themselves off permanently.
set :duo_dead, false
set :duo_epoch, Time.now.to_i

# Load while NOTHING plays (boot-parked above), parked piece first as
# belt-and-suspenders. No GC.start anywhere in this file -- see above.
run_file "D:/CC/AIoT/music/sonic_pi/build/aiot_duo_wim.rb"
run_file "D:/CC/AIoT/music/sonic_pi/build/aiot_duo_soy.rb"

duo_piece_order = [:soy, :wim]

puts "============================================================"
puts "DUO CONDUCTOR RUNNING (Shape of You + World is Mine)"
puts "If you see this banner TWICE without a Stop in between, a"
puts "zombie run survived -- quit Sonic Pi completely and re-Run."
puts "============================================================"

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
  # Dedup + dead guard: if a zombie family is still alive, every family's
  # receiver wakes for the same OSC cue (cues are spider-global). Dedup
  # covers same-run double handling; :duo_dead (set by the epoch watchdog)
  # makes superseded families ignore all future commands.
  if (command_id.to_s != get(:duo_last_command_id).to_s) and (get(:duo_dead) != true)
    set :duo_last_command_id, command_id
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
      set :wim_current_style, :piano_pop
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
      set :soy_current_style, :festival_edm
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
end

# Keeps the backend aligned on the current track (heals any lost switch)
# and doubles as a liveness signal, 1 Hz. Dead families stay silent.
live_loop :duo_track_reporter do
  use_real_time
  if (get(:duo_dead) != true) and ([:soy, :wim].include? get(:active_piece))
    duo_track_feedback get(:active_piece)
  end
  sleep 1.0
end

# 5 Hz heartbeat. Inactive piece threads park on sync :aiot_tick (zero
# virtual-time advance -- a sleep-nap park drifts and Sonic Pi kills the
# thread with "Timing error: can't keep up" within ~1 s on Windows).
# NO GC metronome here -- forced GC.start pauses killed three track
# threads on 2026-07-27 (see the GC.disable note at the top).
live_loop :duo_ticker do
  use_real_time
  cue :aiot_tick
  sleep 0.2
end

# Epoch watchdog: a NEWER run family announces itself via :duo_reboot;
# if its epoch is not ours, this family has been superseded by a re-Run --
# go permanently silent (own store only; the new family is unaffected).
live_loop :duo_reboot_watchdog do
  epoch = sync :duo_reboot
  if epoch.to_i != get(:duo_epoch).to_i
    set :duo_dead, true
    set :playing, false
    set :active_piece, :none
  end
end

# Announce this family LAST so every watchdog (ours and any zombie's) is
# already parked on sync. Our own watchdog sees the matching epoch and
# stays alive; zombies see a foreign epoch and shut down.
cue :duo_reboot, get(:duo_epoch)

# Boot complete -- pieces loaded, ticker + receivers + watchdog running,
# every piece thread parked on sync (deadline-free). Start playback NOW.
set :playing, true
