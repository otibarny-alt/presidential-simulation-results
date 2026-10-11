V22 - PRESIDENTIAL RESULTS USING GOVERNOR LOGIC

- Uses the authoritative Voters Register count API.
- Normalizes county/constituency/ward names before counting.
- Retries temporary 502/503/504 failures and retains successful cached counts.
- County totals are the sum of authoritative constituency totals.
- Counts candidate votes, skipped votes and participants from certified closed
  streams only.
- Matches county_main full stream keys to certified labels such as Stream 01.
- Reports total expected, opened, closed and not-started streams per filter.
