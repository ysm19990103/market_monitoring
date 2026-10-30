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

## If a credential is accidentally committed

Revoke or rotate the credential at its provider immediately. Remove it from current files and, where required, Git history, logs, and artifacts. Deleting the current file alone does not remove earlier copies. Never put the exposed value in a public issue.
