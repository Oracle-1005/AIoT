# AIoT Smart Conducting -- safe loader (multi-machine)
# Open this file in Sonic Pi and press Run exactly once.
# This stable entry loads one song only, avoiding the full playlist's many
# always-resident live_loops. Use this for live demos.

aiot_track = [
  "G:/code/AIoT/AIoT/music/sonic_pi/aiot_conductor_shape_of_you.rb",
  "D:/CC/AIoT/music/sonic_pi/aiot_conductor_shape_of_you.rb",
].uniq.find { |path| File.exist?(path) }

if aiot_track
  run_file aiot_track
else
  puts "AIOT LOADER ERROR: track file not found. Edit the paths in this loader."
end
