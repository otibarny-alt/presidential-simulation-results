2027 PRESIDENTIAL SIMULATION RESULTS DASHBOARD - V1
==================================================
TRAINING / SIMULATION ONLY — NOT OFFICIAL ELECTION RESULTS.

PURPOSE
This is a separate Presidential Results Dashboard modeled on the supplied
Presidential Results Dashboard, but it does NOT read presidential results submissions from Kobo.

Its live result source is the voting simulation itself.

WHAT IT SHOWS
- National -> County -> Constituency -> Ward drill-down.
- Presidential candidate rankings and vote-share percentages.
- Candidate selections.
- Voters who deliberately skipped the Presidential category.
- Presidential category participants.
- Registered voters from agents_login.csv.
- Participation / Registered Voters percentage.
- Skipped / Registered Voters percentage.
- Expected streams, opened streams and closed streams.
- Polling-centre opening/closing progress.
- Per-stream Registered Voters, Participants, Candidate Selections and Skips.
- Recent stream opening/closing activity.

PRIVACY
The dashboard feed does not expose voter National IDs. The voting simulation API returns
aggregated stream-level results only.

REQUIRED CHANGE TO THE VOTING SIMULATION
Deploy:
2027_TRAINING_E_BALLOT_PROTOTYPE_V22_15_PRESIDENTIAL_DASHBOARD_API.zip

On the VOTING SIMULATION Render service add:
DASHBOARD_API_KEY=<a long random shared secret>

Then deploy this dashboard as a SEPARATE Render Web Service and add:
SIMULATION_BASE_URL=https://your-voting-simulation-service.onrender.com
SIMULATION_DASHBOARD_API_KEY=<the exact same shared secret>
FLASK_SECRET_KEY=<long random secret>
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<Werkzeug password hash>

Optional:
CACHE_SECONDS=15

BUILD COMMAND
pip install -r requirements.txt

START COMMAND
gunicorn app:app

IMPORTANT
SIMULATION_BASE_URL must point to the voting simulation service, not the Candidate Registration Portal.

This dashboard remains a monitoring and visualization component for the non-binding
TRAINING / SIMULATION system only.


LIVE CURRENT-VOTE MODE (V2)
---------------------------
This dashboard is designed to pair with Training E-Ballot Prototype V22.74 or later.
That simulation version publishes anonymous presidential simulation ballot events to the shared PostgreSQL database and exposes them through /api/dashboard/president.
No National ID, phone number, or membership number is sent to this dashboard.
The dashboard refreshes headline totals/candidate tallies every 5 seconds; Refresh Now forces an immediate source refresh.
Set CACHE_SECONDS=3 (recommended) on the dashboard service.
Deploy the voting simulation update first, then this dashboard update.

V5 EMAIL RESULTS
----------------
- Adds Email Results to Presidential Candidate Tallies.
- Generates and attaches a filtered Presidential Simulation Results PDF.
- Includes candidate totals, vote shares, turnout/reporting metadata and the
  existing Counties With 25% or More statistics.
- Configure the SMTP variables shown in .env.example on the dashboard service.
