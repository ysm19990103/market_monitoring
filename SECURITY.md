# Security and privacy

This repository contains software and reports derived from public sources. Keep personal, confidential, and patient-level data out of source files, reports, workflow logs, artifacts, issues, and pull requests.

## Credentials and local data

- Collection uses the configured public sources, and event analysis runs locally. No external model integration or personal credential configuration is required.
- Never place a real credential in a commit, example, configuration file, report, command argument, or log. Do not enable shell tracing or print environment variables in workflows.
- The repository ignores common local environment and credential files. Ignore rules do not protect already tracked files or prevent a forced add; inspect staged changes before committing.
- Manual GitHub runs can opt in to saving reports on `main` using GitHub's built-in repository authentication. They do not reference user-supplied secrets. No collection schedule is configured in the proposed version.

## Publication review

On 2026-10-30, the publication review covered all 3 existing commits on the sole branch (26 distinct historical file blobs), commit metadata, 4 Actions job logs, and the report artifact (4 files). No real API keys, tokens, private keys, or private contact details were found in that reviewed content. Scanner findings were generated application/Git hashes and a deliberately dummy credential in a URL rejection test.

This review is a point-in-time check, not a guarantee about future changes. Only public-source data should be collected and published by the scheduled job.

### Recheck on 2026-11-02

The pre-publication recheck covered `main` at `48a7a8ef35cc826e739130b81e5696d43cceaa1b`: all 8 reachable commits on the sole branch, all 51 distinct historical file blobs, and commit metadata. The current snapshot contained 38 tracked files, including 19 report files and the deduplication state. Every retrieved historical blob matched its Git object hash. No tags, pull requests, issues, or releases were present.

All 6 existing Actions runs were reviewed: 10 complete job logs and all 4 retained artifact ZIPs (16 text files). Each ZIP matched GitHub's recorded SHA-256 digest. The review included the reports produced after the earlier review, through 2026-11-01 at 14:07:26 Asia/Shanghai.

Pattern scans for provider credentials, private keys, authorization values, credential-bearing URLs, contact details, personal paths and high-entropy strings were followed by review of the matches, workflow configuration, code, report structure and historical changes. No actual credentials, private contact details, personal datasets or patient-level records were found. Matches were test placeholders, Git/application hashes, GitHub object/artifact identifiers, no-reply commit attribution, and legacy empty environment-variable references. Authentication values in Actions logs were masked. The current source and workflow contain no personal API credential references or external model integration. Normal GitHub account/author attribution remains visible in commit history.

The 32 current automated tests passed locally. Existing CI also passed on Python 3.11, 3.12 and 3.13. The reporting workflow is limited to scheduled runs, manual dispatch and relevant pushes to `main`; it explicitly requests `contents: write` for report persistence. Pull-request tests request only `contents: read`. Repository Actions are enabled, with a read-only default token policy and the workflow's explicit write permission. Artifacts contain only report exports and source health, not caches or local environment files.

The latest reviewed report contained 8 new/substantially updated events and suppressed 26 duplicates. Its 17 configured sources comprised 7 OK, 8 partial and 2 failed sources (NMPA and ANVISA). Successful workflow execution therefore does not imply complete source coverage. These gaps are already disclosed in the reports; publication does not resolve them. The configured daily schedule remains 00:17 UTC / 08:17 Asia/Shanghai and may run late.

This is a point-in-time review of accessible repository history, logs and artifacts, not a guarantee for future changes or an inspection of secret-store values. No history rewrite or log/artifact deletion was needed.

### Publication and live verification on 2026-11-02

Repository visibility was changed to **public** and confirmed both in repository settings and through the repository API (`private: false`, `visibility: public`).

[Post-publication workflow run 41396930980](https://github.com/ysm19990103/market_monitoring/actions/runs/41396930980) completed successfully on `main`. All 32 tests passed, collection and report generation completed, the report artifact uploaded successfully, and the built-in GitHub authentication pushed the reports and deduplication state in commit `82b5ac1b9f82b9a551858242215d2af1bb4b6b2b`.

The new output, log, commit metadata and artifact were also checked. Cumulative reviewed scope through that report commit was 10 commits, 57 distinct historical blobs, 11 job logs from 7 runs, and 5 verified artifact ZIPs containing 20 text files. No actual credentials or private data were found; the additional numeric scan match was an artifact identifier.

The new report was generated at **2026-11-02 13:56:56 Asia/Shanghai**, with 3 new/substantially updated events and 24 suppressed duplicates. Source health was **5 OK, 4 partial, 8 failed** out of 17 sources. Failures were FDA's four configured endpoints (HTTP 404), Lilly (HTTP 403), NMPA (HTTP 412), ANVISA (article-pattern mismatch) and TGA (timeout). These are unresolved collection limitations; the successful workflow does not establish full coverage or establish why source availability changed. See [the latest source health](incretin-watch/reports/coverage.json) for current details. Rule-based interpretation and uncertain dates still require human review.

### Manual operation and source repair review — 2026-11-03

The existing collection workflow was disabled manually in GitHub before preparing this PR. The proposed workflow removes daily scheduling and collection-on-push, retains manual dispatch, and requires an explicit `persist_reports` choice on `main` to save reports/state. Do not re-enable the old workflow before merging the trigger removal.

The proposed code/configuration, synthetic fixtures, documentation, workflow changes, existing report/state snapshot and all 65 distinct reachable historical blobs were scanned for provider tokens, private-key material and credential assignments. No actual credentials were found. Manual review found no private datasets or private contact information in the change; credential-like URLs in tests contain only dummy values. This review does not inspect repository secret-store values and does not guarantee future source content.

The built wheel contains 14 package/metadata files, including only the public default configuration and application code; it excludes repository reports, deduplication state, HTTP cache and local environment files. It was exercised from an empty directory. The offline suite has 55 passing tests. Existing tracked reports and state are byte-unchanged. The new `--check-sources` mode does not even read state, and PR diagnostics use read-only GitHub permissions with checkout credentials not persisted. Only source-health JSON and run metadata are uploaded.

Error reports now use controlled failure categories and HTTP status codes instead of arbitrary exception strings. URLs containing user credentials or recognized credential parameters are rejected. Explicit access restrictions, rate limits and human-verification pages do not trigger alternate endpoints. Requests remain HTTPS-only; FDA's published legacy HTTP article links are upgraded only for the verified FDA hostname. No API key, private database, browser fingerprint spoofing or remote model service is introduced.

Source recovery and remaining limitations are documented in [SOURCE_VERIFICATION.md](incretin-watch/docs/SOURCE_VERIFICATION.md). A successful test/diagnostic workflow is not a claim of complete source coverage.

## If a credential is accidentally committed

Revoke or rotate the credential at its provider immediately. Remove it from current files and, where required, Git history, logs, and artifacts. Deleting the current file alone does not remove earlier copies. Never put the exposed value in a public issue.
