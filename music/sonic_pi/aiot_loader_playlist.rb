# AIoT Smart Conducting -- playlist loader (multi-machine)
# High-load five-track playlist. Use only for stress testing.
# Fully quit Sonic Pi before loading this after the safe loader.

aiot_playlist = [
  "G:/code/AIoT/AIoT/music/sonic_pi/build/aiot_conductor_playlist.rb",
  "D:/CC/AIoT/music/sonic_pi/build/aiot_conductor_playlist.rb",
].uniq.find { |path| File.exist?(path) }

if aiot_playlist
  run_file aiot_playlist
else
  puts "AIOT LOADER ERROR: playlist file not found. Edit the paths in this loader."
end
