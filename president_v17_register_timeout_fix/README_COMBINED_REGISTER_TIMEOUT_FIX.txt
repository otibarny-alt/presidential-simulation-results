COMBINED REGISTER TIMEOUT FIX

The result dashboard now allows up to 120 seconds for the voting service to
read and deduplicate the PostgreSQL master register and Kobo membership data.

Earlier builds stopped after 30 seconds. On a cold Render worker, that timeout
occurred before the combined register breakdown was returned, leaving every
dashboard card at its initial zero.

County-first presentation remains enforced. After the first successful load,
the voting service and dashboard caches make subsequent county refreshes much
faster.
