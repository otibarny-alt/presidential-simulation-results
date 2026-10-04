PRESIDENTIAL DASHBOARD V10

- Extends the voting-system API read window from 12 seconds to 100 seconds so
  the first Kobo membership-register synchronization can complete.
- Runs Gunicorn with a 120-second worker timeout and four threads.
- Reuses the last successful dashboard snapshot during a temporary timeout.
- Replaces the technical HTTPSConnectionPool message with a clear retry notice.
