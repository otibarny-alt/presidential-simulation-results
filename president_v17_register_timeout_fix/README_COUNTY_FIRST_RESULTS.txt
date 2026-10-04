COUNTY-FIRST RESULTS PERFORMANCE UPDATE

- A county must be selected before any result or stream request is made.
- National/all-counties presentation is disabled.
- Initial page loading fetches only the small county list.
- Automatic refresh starts only after a county has been selected.
- Summary, stream, recent-stream and email endpoints reject requests without a county.
- Constituency and ward filters remain available within the selected county.

This prevents large nationwide result payloads from being rendered in the
browser and keeps each dashboard responsive as the register grows.
