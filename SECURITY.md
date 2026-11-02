# Security and privacy

This repository contains software and reports derived from public sources. Keep personal, confidential, and patient-level data out of source files, reports, workflow logs, artifacts, issues, and pull requests.

## Credentials and local data

- Collection uses the configured public sources, and event analysis runs locally. No external model integration or personal credential configuration is required.
- Never place a real credential in a commit, example, configuration file, report, command argument, or log. Do not enable shell tracing or print environment variables in workflows.
- The repository ignores common local environment and credential files. Ignore rules do not protect already tracked files or prevent a forced add; inspect staged changes before committing.
- The scheduled workflow uses GitHub's built-in repository authentication to save reports. It does not reference user-supplied secrets.

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

## If a credential is accidentally committed

Revoke or rotate the credential at its provider immediately. Remove it from current files and, where required, Git history, logs, and artifacts. Deleting the current file alone does not remove earlier copies. Never put the exposed value in a public issue.
