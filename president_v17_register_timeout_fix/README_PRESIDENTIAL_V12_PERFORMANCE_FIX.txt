PRESIDENTIAL RESULTS DASHBOARD V12 — PERFORMANCE FIX

- Uses a 120-second local snapshot cache instead of refetching every 3 seconds.
- Retains the 100-second cold-start allowance and 120-second Gunicorn timeout.
- Retains stale successful data when a later refresh fails.

Deploy after Voting System V23.74.
