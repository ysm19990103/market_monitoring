# Manual operation and source verification — 2026-11-03

The collection workflow was disabled in GitHub before this PR was created. The PR removes both `schedule` and collection-on-`push`; `workflow_dispatch` remains. Keep the workflow disabled until this PR is approved and merged. Re-enabling the old version would restore daily runs. Package installation does not register any background task.

## Findings and changes

The committed November 3 coverage file reported FDA's four endpoints as HTTP 404, Lilly as HTTP 403, ANVISA as a link-pattern failure, NMPA as HTTP 412 and TGA as a timeout. A fresh local check accessed all four FDA endpoints and Lilly's feed without credentials or altered browser identity. These historical status codes therefore do not establish permanent removal or a single root cause.

| Source | Verified public endpoint / observation | Change and remaining limit |
|---|---|---|
| FDA press | [FDA's RSS directory](https://www.fda.gov/about-fda/contact-fda/subscribe-podcasts-and-news-feeds) still advertises the configured [RSS](https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml). It returns legacy HTTP article links. | Upgrade only `www.fda.gov` feed links to HTTPS. Previously all 20 discovered links were rejected by the HTTPS-only policy. Add the official [press listing](https://www.fda.gov/news-events/fda-newsroom/press-announcements) as a bounded fallback for ordinary request/parser failures. No alternative on access denial or rate limiting. |
| FDA safety | [Drug Safety Communications](https://www.fda.gov/drugs/drug-safety-and-availability/drug-safety-communications) remains published. | Restrict discovery to the article table and parse its US numeric dates explicitly. Zero recent relevant items can be valid; the current list is not an exhaustive archive. |
| FDA GLP-1 policy pages | [Compounding](https://www.fda.gov/drugs/drug-alerts-and-statements/fda-clarifies-policies-compounders-national-glp-1-supply-begins-stabilize) and [unapproved products](https://www.fda.gov/drugs/drug-alerts-and-statements/fdas-concerns-unapproved-glp-1-drugs-used-weight-loss) both returned readable bodies locally. | Retain the canonical URLs. Do not replace specific policy pages with a generic news feed or infer recovery on all runners. Rolling-page baselines and content-change rules are unchanged. |
| Lilly | [Official feed directory](https://investor.lilly.com/rss-news-feeds) links to `news-releases.xml?items=10`. Both the old `items=100` request and this published URL returned 10 entries locally. | Use the published URL and retain feed-window warnings. Two relevant recent article bodies were retrieved locally. A future 403 remains an access restriction, not an XML parser error; no browser impersonation, mirror or CAPTCHA workaround is added. |
| TGA | [Official RSS directory](https://www.tga.gov.au/news/email-subscriptions/rss-feeds) publishes [Safety updates RSS](https://tga.gov.au/feeds/article/safety-updates.xml). | Use that same-topic feed, with the original listing as a bounded alternative. Both returned HTTP 503 locally. Availability remains unresolved; retries are bounded and respect `Retry-After`. |
| ANVISA | The old URL redirects to the [current news page](https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa). The page and year archive render a `Carregando` (loading) shell without article links in the retrieved HTML. | Update the canonical URL and distinguish `dynamic_listing` from no matching news. No claim of recovery; no unverified private API is added. |
| NMPA | The configured official page returned HTTP 412. | Report `access_restricted` and stop, without retrying alternate routes. |
| Other sources | Novo, EMA, MHRA, CMS, PMDA, Health Canada and Europe PMC are retained. | Current-list/feed-window limits remain visible. EMA EPAR article-body extraction is still limited even when the feed loads. |

Published directory links were checked through web retrieval and direct unauthenticated requests. Runtime checks use the same identifiable `IncretinWatch/0.1 (primary-source research)` user agent, HTTPS allowlist, response-size cap and bounded retries. A 404 from a runner is recorded as `http_not_found`, not asserted to mean permanent unavailability. Server/network failures, access restrictions, parser errors and article-body failures are reported separately. Explicit HTTP 200 challenge pages are not treated as content.

## Reproducible verification

```bash
cd incretin-watch
python -m pip install .
python -m unittest discover -s tests -v
incretin-watch --check-sources --as-of 2026-11-03 --output .cache/source-check
```

The offline fixtures are synthetic and reproduce RSS/Atom, FDA listing/date structure, challenge responses, malformed/empty feeds and request failures. Tests verify same-article deduplication across RSS and HTML fallback, missing-body retry behavior, 304 cache reuse without serving stale data after a denial, credential URL rejection, bounded retries, redacted diagnostics, configuration packaging and byte-preserved state. A regression found and fixed a duplicate trigger caused by FDA's date-prefixed HTML link title. RSS publication dates are no longer treated as modification dates through feedparser's legacy fallback.

`--check-sources` does not read or write deduplication state, generate event reports, or mark anything emitted. It produces only health JSON and run metadata; HTTP cache stays local. The PR diagnostic in GitHub Actions uses this mode with read-only permissions and no persisted checkout credentials. The three-version test matrix is separate from source availability. Live health may change between runs; CI completion alone does not establish full coverage.

Local validation: **55 offline tests passed**. A clean wheel is also checked outside the source tree. GitHub Actions results and a source-by-source live snapshot will be recorded here after the PR run completes.

## State and privacy

The existing `reports/` history and `state/state.json` are not modified by this PR. Source IDs, article identity rules and the deduplication schema remain unchanged. Local operators should retain their existing state file across upgrades. The package bundles only public-source configuration and code, not reports, caches, state, API keys, private databases or personal contact information.

No personal API key is needed. Collection/report analysis remains local apart from requests for public source content. Diagnostics record controlled categories/status codes rather than arbitrary exception messages or response bodies. Credential-bearing URLs are rejected. GitHub report persistence remains opt-in and uses only GitHub's built-in ephemeral repository token on `main`. Do not enable shell tracing, upload caches or add personal configuration to public commits.
