# RC4 test results

Main tests: 57 passed (26 test_app, 14 test_native, 17 test_rc4).
Additional browser suite: 2 attempted, 1 passed, 1 error.
- Hungary fixture passed using available HTML fallback; browser rendering not proven.
- Estonia fixture error: browser_unavailable; Chromium runtime could not launch in preparation environment.
Python compileall: passed. node --check app/static/app.js: passed.
Original net.py reproduced exact DecodingError with a synthetic gzip wire response. RC4 gzip/deflate tests pass and decoded size cap is enforced.
New tests cover plain/gzip/deflate transport, decompressed cap, 429, long error body, identity retry, TED currency/schema/timeout, German archive dates, Apify authorization/encryption/no-disclosure/blank-token/validation/deletion/origin/running-job checks and clear-selection regression.
No live portal or paid Actor execution; no Docker build, clean dependency install, Render deploy or visual browser QA. All fixtures are synthetic or mocked.
