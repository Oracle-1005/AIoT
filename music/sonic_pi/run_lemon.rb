# Lemon launcher (multi-machine): keep the large generated score
# outside Sonic Pi's editor buffer. Open this file in Sonic Pi and press Run.

aiot_track = [
  "G:/code/AIoT/AIoT/music/sonic_pi/aiot_conductor_lemon.rb",
  "D:/CC/AIoT/music/sonic_pi/aiot_conductor_lemon.rb",
].uniq.find { |path| File.exist?(path) }

if aiot_track
  run_file aiot_track
else
  puts "AIOT LOADER ERROR: track file not found. Edit the paths in this loader."
end
