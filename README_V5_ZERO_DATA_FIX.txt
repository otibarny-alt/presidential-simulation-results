PRESIDENTIAL DASHBOARD V5 — ZERO-DATA AND GEOGRAPHIC MATCHING FIX

What was corrected
------------------
- Uses a pooled HTTP session with short connection/read timeouts.
- Keeps the last valid snapshot during a temporary Render/database outage
  instead of replacing the dashboard with fabricated zero values.
- Validates that the upstream response contains a real stream snapshot.
- Matches streams using county + constituency + ward + polling station + stream,
  preventing identically named streams in different places from overwriting one
  another.

Required Render environment variables
-------------------------------------
SIMULATION_BASE_URL=https://voting-simulation-system.onrender.com
SIMULATION_DASHBOARD_API_KEY=<exactly the same value as DASHBOARD_API_KEY on the voting service>

If either value is missing or the keys differ, /api/summary will return an
explicit configuration/authorization error. Correct the environment variables
and redeploy the presidential dashboard.

