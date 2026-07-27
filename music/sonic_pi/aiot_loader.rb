# AIoT Smart Conducting -- Sonic Pi loader (paste THIS into a buffer, then press Run)
#
# Why a loader: the Run button ships the buffer to the Sonic Pi engine as one OSC
# packet, and the engine reads at most 16384 bytes per packet (udp_server.rb
# recvfrom(16384)) -- larger buffers are silently truncated and never run
# (spider.log shows "undefined method '%' for nil"). The duo conductor reads
# everything from disk; only this tiny loader crosses the wire.
#
# Workflow:
# 1. Paste this file into any Sonic Pi buffer once.
# 2. Press Run -- the DUO conductor starts (Shape of You + World is Mine in one
#    run; the frontend prev/next or /conductor/transport switches pieces).
# 3. After editing the .rb in the repo, just press Run again. No re-paste needed.
#
# If the repo lives elsewhere on this machine, fix the path below (keep "/" slashes).

run_file "D:/CC/AIoT/music/sonic_pi/build/aiot_conductor_duo.rb"
