# Non-US IDH Trial Watch

Public RSS 2.0 feed for safusidenib and HMPL-306 / ranosidenib clinical trial metadata.

Feed: https://jessica-lsd.github.io/non-us-idh-trial-watch/feed.xml

Coverage and latest check: https://jessica-lsd.github.io/non-us-idh-trial-watch/

## Coverage is partial

This is not comprehensive surveillance of all non-US registries. Priority sources were tested, and gaps are explicit in `sources.json` and the public coverage page.

* ClinicalTrials.gov API v2: discovery with alternate names, pagination and full details. Include trials with at least one explicitly listed non-US country; exclude US-only and unknown geography. This is supplementary coverage, not direct national-registry coverage.
* Japan jRCT: direct monitoring of two verified known safusidenib records (jRCT2080225243 and jRCT2071240033). Free-word searches returned unrelated records during verification, so automated new-trial discovery is **unsupported**, not reported as a successful search. jRCT2071220111, found on a sponsor index, failed asset verification and was excluded rather than treated as a safusidenib trial.
* China ChiCTR: one known AB-218 record, distinct from China CDE. Detail parsing is validated on each run; a missing identifier/asset/title/indication/phase is a failure. Discovery unsupported.
* China CDE/NMPA: tested search endpoint returned HTTP 202 JavaScript challenge. Unsupported.
* EU CTIS: verified POST search (`/ctis-public-api/search`) with each asset alias separately, pagination and GET details (`/retrieve/{ctNumber}`). Initial GET search was blocked, but the correct POST method succeeded. Two HMPL-306 trials returned in positive-control testing; a nonsense term returned no trials. Public portal API is undocumented and can change. Full document contents are not monitored; results availability and structured metadata are monitored. Public registry trial links use the EUCT query parameter.
* WHO ICTRP: official portal states crawling service unavailable. No automated integration; manual XML export is not a daily monitor.
* ANZCTR: HTTP 403 in testing. ISRCTN: JavaScript/cookie interstitial. Other national registries: not independently implemented or verified. See coverage page.

No CAPTCHA bypass or assertion that an accessible homepage verifies a source. Local verification is dated 2026-10-26; current implemented-source results and failures are written on every run. Static unsupported-source entries explicitly retain the test date and are not fresh daily checks. A failed source retains its last good data and cannot erase records or produce a false no-change claim. If every implemented source fails, the workflow fails without publishing.

## Operation

Daily GitHub Actions target: **06:17 UTC**, plus manual dispatch and code pushes. Scheduled runs can be delayed; GitHub may disable inactive public-repository schedules after 60 days. Watch the timestamp and Actions notifications. No API keys or paid services are required. Enable Pages with **GitHub Actions** as the publishing source. The workflow commits durable observations before deploying the `docs` artifact, so change history survives runner replacement. Concurrent runs are serialized; failed state pushes prevent deployment. Avoid editing the repository during an active check.

Baseline items represent existing trials, not newly registered studies. RSS `pubDate` is the observation timestamp; registry registration, first-posted, last-updated, start and completion dates are separately labeled when available. Missing values say “Not supplied.” All indications and phases are in scope, including healthy-volunteer work.

Aliases include safusidenib, DS-1001/DS-1001b, AB-218 and punctuation/case variants; HMPL-306, HMPL306 and ranosidenib. References: [Nuvation Bio pipeline](https://nuvationbio.com/pipeline/), [safusidenib trial protocol with aliases](https://cdn.clinicaltrials.gov/large-docs/19/NCT05303519/Prot_000.pdf), [HUTCHMED pipeline](https://www.hutch-med.com/pipeline-and-products/our-pipeline/).

## Deduplication and material changes

Exact shared registry identifiers or exact normalized sponsor protocol ID plus asset connect registrations, including transitive matches. Similar titles alone never merge trials. Each item retains all source IDs and registry links. Cross-registry conflicts retain attribution. Newly added source evidence can create an update when material fields differ. Source removals are not interpreted as withdrawals; records remain last-known and their checked-at values remain in `data/state.json`.

Material: title, indication, phase, recruitment, enrollment, country, study dates, outcomes, eligibility, interventions and results availability. Registry refresh dates and formatting alone are ignored. Changed values include before/after in RSS descriptions. Reversions produce new GUIDs; reruns without material changes do not. State and complete event history persist; the latest 1,000 events appear in RSS, latest 30 on the page.

## Tests

Python 3.11+ standard library only:

```sh
python -m unittest -v
python watch.py
python validate_feed.py docs/feed.xml
python validate_feed.py https://jessica-lsd.github.io/non-us-idh-trial-watch/feed.xml
```

RSS interoperability checks cover RSS 2.0, UTF-8 XML, channel metadata, absolute HTTPS links, unique GUIDs, RFC 2822 item dates and escaped HTML. These checks establish feed format compatibility; they do not assert a successful import into a signed-in Feeder account.

To add a known national record, update `sources.json`, verify its parser against live data, and run tests. Do not relabel an unsupported source as verified until both search and details have been tested with positive and negative controls. Website/anti-bot changes can break HTML parsers; current coverage always takes precedence over this README.
