"""Public registry metadata watch. Python 3.11+, standard library only."""
import argparse
import copy
import datetime as dt
import email.utils
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
BASE = 'https://jessica-lsd.github.io/non-us-idh-trial-watch/'
ALIASES = {
    'safusidenib': ['safusidenib', 'DS-1001', 'DS-1001b', 'DS1001', 'AB-218', 'AB218', 'AB 218'],
    'HMPL-306': ['HMPL-306', 'HMPL306', 'HMPL 306', 'ranosidenib'],
}
ID_PATTERN = r'(?i)\b(?:NCT\d{8}|jRCT[a-z]?\d{10}|ChiCTR\d{10}|CTR\d{8}|ISRCTN\d{8}|ACTRN\d{14}|\d{4}-\d{6}-\d{2}(?:-\d{2})?)\b'
MATERIAL = ['title', 'indications', 'phase', 'status', 'enrollment', 'countries', 'start', 'primary_completion', 'completion', 'outcomes', 'eligibility', 'interventions', 'results']


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def norm(s):
    return re.sub(r'[^\w]', '', s.casefold())


def assets(s):
    # Boundaries prevent AB-218 from matching the unrelated drug JAB-21822.
    def pattern(alias):
        chunks=re.split(r'[\s-]+',alias)
        return r'(?<![A-Za-z0-9])'+r'[\s-]*'.join(re.escape(x) for x in chunks)+r'(?![A-Za-z0-9])'
    return sorted(k for k, vals in ALIASES.items() if any(re.search(pattern(v),s,re.I) for v in vals))


def request(url, data=None):
    for attempt in range(3):
        try:
            payload = json.dumps(data).encode() if data is not None else None
            req = urllib.request.Request(url, data=payload, headers={
                'User-Agent': 'IDHTrialWatch/1.0 (+https://github.com/Jessica-LSD/non-us-idh-trial-watch)',
                'Accept': 'application/json,text/html,application/xml',
                **({'Content-Type': 'application/json'} if payload else {})})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status != 200:
                    raise ValueError(f'HTTP {r.status}; response is not verified registry data')
                return r.read().decode('utf-8-sig')
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


class Tables(HTMLParser):
    """Extract visible table cells; discard script/style and commented templates."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.skip = [], None, None, 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th'):
            self.cell = []
        if tag == 'br' and self.cell is not None:
            self.cell.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag in ('td', 'th') and self.cell is not None:
            if self.row is not None:
                self.row.append(' '.join(' '.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if not self.skip and self.cell is not None:
            self.cell.append(data)


def field(rows, label):
    for row in rows:
        if row and re.search(label, row[0], re.I) and len(row) > 1:
            return row[-1].strip()
    return ''


def ids(text):
    return sorted(set(x.upper() for x in re.findall(ID_PATTERN, text)))


def ctgov():
    query = ' OR '.join('"' + a + '"' for vals in ALIASES.values() for a in vals)
    params = {'query.term': query, 'pageSize': 100, 'format': 'json'}
    records = []
    while True:
        data = json.loads(request('https://clinicaltrials.gov/api/v2/studies?' + urllib.parse.urlencode(params)))
        if 'studies' not in data or not isinstance(data['studies'], list):
            raise ValueError('ClinicalTrials.gov schema changed')
        for study in data['studies']:
            p = study['protocolSection']
            ident = p['identificationModule']
            interventions = p.get('armsInterventionsModule', {}).get('interventions', [])
            matched = assets(ident.get('briefTitle', '') + json.dumps(interventions, ensure_ascii=False))
            countries = sorted(set(x['country'] for x in p.get('contactsLocationsModule', {}).get('locations', []) if x.get('country')))
            # Include multinational trials with at least one explicitly listed non-US site.
            # Unknown geography is excluded rather than assumed non-US.
            if not matched or not any(c != 'United States' for c in countries):
                continue
            status = p['statusModule']
            design = p.get('designModule', {})
            date = lambda k: status.get(k, {}).get('date', '')
            rec = dict(source='ClinicalTrials.gov', id=ident['nctId'], ids=ids(json.dumps(ident)), assets=matched,
                protocol=ident.get('orgStudyIdInfo', {}).get('id', ''), title=ident['briefTitle'],
                indications=p.get('conditionsModule', {}).get('conditions', []), phase=design.get('phases', []),
                status=status.get('overallStatus', ''), enrollment=design.get('enrollmentInfo', {}), countries=countries,
                start=date('startDateStruct'), primary_completion=date('primaryCompletionDateStruct'), completion=date('completionDateStruct'),
                registered=date('studyFirstSubmitDateStruct') or status.get('studyFirstSubmitDate', ''),
                posted=date('studyFirstPostDateStruct'), updated=date('lastUpdatePostDateStruct'),
                outcomes=p.get('outcomesModule', {}), eligibility=p.get('eligibilityModule', {}),
                interventions=interventions, results=study.get('hasResults', 'resultsSection' in study),
                url='https://clinicaltrials.gov/study/' + ident['nctId'])
            records.append(rec)
        if not data.get('nextPageToken'):
            return records
        params['pageToken'] = data['nextPageToken']


def national_record(source, identifier, url, kind):
    text = request(url)
    rows = Tables(text).rows
    matched = assets(' '.join(' '.join(r) for r in rows))
    if identifier.upper() not in ids(' '.join(' '.join(r) for r in rows)) or not matched:
        raise ValueError(f'{identifier}: expected trial identifier/asset absent; possible challenge or layout change')
    if kind == 'jrct':
        title = field(rows, r'Scientific Title')
        condition = field(rows, r'Health Condition(?:\(s\))? or Problem')
        phase = field(rows, r'/\s*Phase\s*$')
        status = field(rows, r'Recruitment Status')
        registered = field(rows, r'^登録日$')
        updated = field(rows, r'最終.*更新|更新日|Last.*[Uu]pdate')
        start = field(rows, r'Date of First Enrolment|Date of First Enrollment')
        completion = field(rows, r'予定試験期間（終了日）')
        enrollment = field(rows, r'Target Sample Size')
        countries = ['Japan']
        protocol = field(rows, r'治験実施計画書.*番号|Protocol.*[Nn]umber')
    else:
        title = field(rows, r'^Public title') or field(rows, r'^Scientific title')
        condition = field(rows, r'Target disease|Health condition')
        phase = field(rows, r'Study phase')
        status = field(rows, r'Recruiting status')
        registered = field(rows, r'Date of Registration')
        updated = field(rows, r'Date of Last Refreshed')
        start = field(rows, r'Date of first enrollment')
        completion = ''
        enrollment = field(rows, r'Target sample size')
        countries = ['China']
        protocol = field(rows, r'Study subject ID')
    if not title or not phase or not condition:
        raise ValueError(f'{identifier}: required title/indication/phase missing')
    return dict(source=source, id=identifier, ids=ids(' '.join(' '.join(r) for r in rows)), assets=matched,
        protocol=protocol, title=title, indications=[condition], phase=[phase], status=status,
        enrollment=enrollment, countries=countries, start=start, completion=completion,
        primary_completion='', registered=registered, posted='', updated=updated,
        outcomes={k: field(rows, k) for k in ['Primary Outcome', 'Secondary Outcome']},
        eligibility=field(rows, r'Inclusion Criteria'), interventions=field(rows, r'Generic Name etc|Intervention'),
        results=field(rows, r'Summary Results'), url=url)


def ctis_search(term):
    records, page = [], 1
    while True:
        response = json.loads(request('https://euclinicaltrials.eu/ctis-public-api/search', {
            'searchCriteria': {'containAll': term}, 'pagination': {'page': page, 'size': 100}}))
        if not isinstance(response.get('data'), list) or 'pagination' not in response:
            raise ValueError('CTIS search schema changed')
        records += response['data']
        if not response['pagination'].get('nextPage'):
            if len(records) != response['pagination']['totalRecords']:
                raise ValueError('CTIS pagination count mismatch')
            return records
        page += 1
        if page > 1000:
            raise ValueError('CTIS pagination exceeded guard')


def ctis():
    found = {}
    # Search separately: do not assume undocumented Boolean syntax or synonym expansion.
    for term in sorted(set(a for vals in ALIASES.values() for a in vals)):
        for hit in ctis_search(term):
            found[hit['ctNumber']] = hit
    records = []
    for identifier, hit in sorted(found.items()):
        d = json.loads(request('https://euclinicaltrials.eu/ctis-public-api/retrieve/'+identifier))
        if d.get('ctNumber') != identifier:
            raise ValueError('CTIS detail identifier mismatch')
        p = d['authorizedApplication']['authorizedPartI']
        identifiers = p['trialDetails']['clinicalTrialIdentifiers']
        title = identifiers['publicTitle']
        matched = assets(title + json.dumps(p.get('products', []),ensure_ascii=False))
        if not matched:
            continue  # Reject broad search hits with no asset evidence in title/products.
        countries = sorted(set(x.rsplit(':',1)[0] for x in hit.get('trialCountries', [])))
        if not countries or not any(c != 'United States' for c in countries):
            continue
        info = p['trialDetails']['trialInformation']
        records.append(dict(source='EU CTIS',id=identifier,ids=ids(json.dumps(identifiers))+[identifier],
            assets=matched,protocol=identifiers.get('sponsorProtocolCode') or (identifiers.get('shortTitle','') if re.fullmatch(r'[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+){2,}',identifiers.get('shortTitle','')) else ''),title=title,
            indications=[hit['conditions']],phase=[hit['trialPhase']],status=d['ctStatus'],
            enrollment={'reported':hit.get('totalNumberEnrolled','')},countries=countries,
            start=d.get('startDateEU',''),completion=d.get('endDateEU',''),primary_completion='',
            registered='',posted=d.get('publishDate',''),updated=hit.get('lastPublicationUpdate',''),
            outcomes={'primary':hit.get('primaryEndPoint',''),'other':hit.get('endPoint','')},
            eligibility=info.get('populationOfTrialSubjects',{}),interventions=p.get('products',[]),
            results=bool(d.get('results')),url='https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT='+identifier))
    return records


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def identity_tokens(record):
    tokens = {'id:' + i.upper() for i in record['ids'] + [record['id']]}
    protocol = norm(record.get('protocol', ''))
    if len(protocol) >= 6:
        tokens.update('protocol:' + a + ':' + protocol for a in record['assets'])
    return tokens


def groups(records):
    groups_ = []
    for record in sorted(records, key=lambda r: (r['source'], r['id'])):
        tok = identity_tokens(record)
        hits = [g for g in groups_ if g['tokens'] & tok]
        group = {'tokens': tok, 'records': [record]}
        for hit in hits:
            group['tokens'] |= hit['tokens']
            group['records'] += hit['records']
            groups_.remove(hit)
        groups_.append(group)
    return groups_


def update(state, incoming, timestamp):
    state = copy.deepcopy(state)
    state.setdefault('records', {})
    state.setdefault('trials', {})
    state.setdefault('events', [])
    for record in incoming:
        record = copy.deepcopy(record)
        record['checked_at'] = record.pop('observed_at',timestamp)
        state['records'][record['source'] + ':' + record['id'].upper()] = record
    previous = state['trials']
    trials = {}
    for group in groups(list(state['records'].values())):
        rs = group['records']
        matches = [k for k,v in previous.items() if set(v['tokens']) & group['tokens']]
        key = sorted(matches)[0] if matches else sorted(group['tokens'])[0]
        # Retain provenance and conflicts. Date-only registry refreshes are not material.
        material = {r['source'] + ':' + r['id']: {k: r.get(k, '') for k in MATERIAL} for r in rs}
        old = previous.get(key)
        fields = MATERIAL if old is None else [k for k in MATERIAL if
            {s:v.get(k) for s,v in material.items()} != {s:v.get(k) for s,v in old['material'].items()}]
        if fields:
            seq = (old.get('sequence', 0) if old else 0) + 1
            event = dict(guid=fingerprint([key, seq, material]), key=key, observed=timestamp,
                kind='Baseline' if old is None and not previous else ('New trial' if old is None else 'Material change'),
                changes=fields, records=copy.deepcopy(rs), before=old['material'] if old else None)
            state['events'].append(event)
        else:
            seq = old.get('sequence', 0)
        trials[key] = dict(tokens=sorted(group['tokens']), material=material, sequence=seq)
    state['trials'] = trials
    state['updated_at'] = timestamp
    return state


def description(event):
    parts = [f'<p>{html.escape(event["kind"])} observed {html.escape(event["observed"])}. Changes: {html.escape(", ".join(event["changes"]))}.</p>']
    for r in event['records']:
        parts.append('<h3>' + html.escape(r['source'] + ' — ' + r['id']) + '</h3><dl>')
        fields = ['title','ids','protocol','indications','phase','status','enrollment','countries','start','primary_completion','completion','registered','posted','updated','checked_at']
        for k in fields:
            val = r.get(k) or 'Not supplied'
            val = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val)
            parts.append('<dt>' + html.escape(k.replace('_',' ').title()) + '</dt><dd>' + html.escape(val) + '</dd>')
        parts.append('</dl><p><a href="' + html.escape(r['url'],quote=True) + '">Registry record</a></p>')
        if event.get('before'):
            old = event['before'].get(r['source'] + ':' + r['id'])
            if old:
                changes = {k:{'before':old.get(k),'after':r.get(k)} for k in event['changes'] if old.get(k)!=r.get(k)}
                parts.append('<p>Changed values:</p><pre>' + html.escape(json.dumps(changes,ensure_ascii=False,indent=2)) + '</pre>')
    parts.append('<p>Coverage is partial. See <a href="'+BASE+'">registry coverage and check times</a>, including the last successful CDE browser capture and any automation failure. WHO ICTRP automation remains unsupported; jRCT monitoring covers known records only.</p>')
    return ''.join(parts)


def render(state, coverage, out, base):
    out.mkdir(parents=True, exist_ok=True)
    ET.register_namespace('atom','http://www.w3.org/2005/Atom')
    root = ET.Element('rss', version='2.0')
    channel = ET.SubElement(root,'channel')
    for k,v in [('title','Non-US IDH Trial Watch'),('link',base),('description','Safusidenib and HMPL-306 / ranosidenib trial metadata. Coverage is partial; see the linked coverage page.'),('language','en'),('ttl','1440'),('lastBuildDate',email.utils.format_datetime(dt.datetime.fromisoformat(state['updated_at'])))]:
        ET.SubElement(channel,k).text=v
    ET.SubElement(channel,'{http://www.w3.org/2005/Atom}link',href=base+'feed.xml',rel='self',type='application/rss+xml')
    for event in reversed(state['events'][-1000:]):
        item = ET.SubElement(channel,'item')
        rs=event['records']
        title=f'{event["kind"]}: {", ".join(sorted(set(a for r in rs for a in r["assets"])))} — {" / ".join(r["id"] for r in rs)}'
        ET.SubElement(item,'title').text=title
        ET.SubElement(item,'link').text=rs[0]['url']
        ET.SubElement(item,'guid',isPermaLink='false').text='urn:sha256:'+event['guid']
        ET.SubElement(item,'pubDate').text=email.utils.format_datetime(dt.datetime.fromisoformat(event['observed']))
        ET.SubElement(item,'description').text=description(event)
    ET.indent(root)
    ET.ElementTree(root).write(out/'feed.xml',encoding='utf-8',xml_declaration=True)
    (out/'coverage.json').write_text(json.dumps(coverage,indent=2,ensure_ascii=False),encoding='utf8')
    esc=lambda v:html.escape(str(v))
    rows=''.join('<tr><td>'+esc(c['source'])+'</td><td>'+esc(c['status'])+'</td><td>'+esc(c['detail'])+'</td><td>'+esc(c.get('checked_at',''))+'</td></tr>' for c in coverage)
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Non-US IDH Trial Watch</title><link rel="alternate" type="application/rss+xml" title="Non-US IDH Trial Watch" href="feed.xml"><style>body{font:17px/1.6 system-ui;max-width:1100px;margin:3em auto;padding:0 24px;color:#18323a;background:#f6faf9}h1{font-size:2.3rem}a{color:#006b67}table{border-collapse:collapse;background:white;width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid #d4e2df;vertical-align:top}code{overflow-wrap:anywhere}aside{background:#fff0cc;padding:16px}details{background:white;padding:16px;margin:12px 0}dt{font-weight:bold}dd{overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Non-US IDH Trial Watch</h1><p>Safusidenib and HMPL-306 (ranosidenib)</p>'''
    page+='<p><a href="feed.xml">Subscribe to RSS in Feeder</a> · <a href="coverage.json">Coverage data</a> · <a href="https://github.com/Jessica-LSD/non-us-idh-trial-watch">Source and daily runs</a></p><p>Feed URL: <code>'+esc(base+'feed.xml')+'</code></p>'
    page+='<aside>Partial coverage. Unsupported sources are not monitored. Known-record monitoring does not discover all new trials. A reachable homepage does not verify a registry integration. ClinicalTrials.gov is supplementary and does not replace national registries.</aside>'
    page+='<p>Last run: '+esc(state['updated_at'])+'. Daily check target: 06:17 UTC; GitHub scheduling can be delayed. Check run history if this timestamp is more than 48 hours old.</p>'
    page+='<h2>Registry coverage</h2><table><tr><th>Source</th><th>Current status</th><th>Scope / limitation</th><th>Checked (UTC)</th></tr>'+rows+'</table>'
    page+='<h2>Scope and change rules</h2><p>All indications and phases, including healthy-volunteer studies. Multinational trials qualify when a non-US country is explicitly listed. Unknown geography and US-only studies are excluded from discovery. Baseline items describe existing records, not newly registered trials. Item dates are observation dates; registry dates retain their labels. Updates to title, indication, phase, recruitment, enrollment, geography, study dates, outcomes, eligibility, intervention or results create items. Registry refresh dates and page formatting alone do not. Failures preserve the last good data and are shown above. Cross-registry matches require an explicit shared ID or exact normalized protocol ID plus asset; titles alone are never used. Conflicting registry values remain attributed. A newly linked source may generate an item when it adds material information.</p>'
    page+='<h2>Recent trial updates</h2>'
    for event in reversed(state['events'][-30:]):
        page+='<details><summary>'+esc(event['kind']+' — '+', '.join(r['id'] for r in event['records']))+'</summary>'+description(event)+'</details>'
    (out/'index.html').write_text(page+'</html>',encoding='utf8')
    (out/'.nojekyll').touch()


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default=BASE)
    args=parser.parse_args()
    if not args.base_url.startswith('https://'):
        raise ValueError('Feed base must be an absolute HTTPS URL')
    state_path=ROOT/'data/state.json'
    state=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {}
    stamp=now()
    incoming, coverage=[],[]
    from china import load_snapshot
    china_records,china_coverage=load_snapshot()
    incoming+=china_records
    coverage.append(china_coverage)
    try:
        records=ctis()
        incoming+=records
        coverage.append(dict(source='EU CTIS',status='verified: discovery + details',detail=f'{len(records)} matching trials. POST search with separate aliases and pagination, GET details. Undocumented public-portal API; schema validated each run. Results availability monitored; full document contents not monitored.',checked_at=stamp))
    except Exception as e:
        coverage.append(dict(source='EU CTIS',status='FAILED',detail=str(e),checked_at=stamp))
    try:
        records=ctgov()
        incoming+=records
        coverage.append(dict(source='ClinicalTrials.gov',status='verified: discovery + details',detail=f'{len(records)} matching studies with explicit non-US sites; API v2, all pages checked',checked_at=stamp))
    except Exception as e:
        coverage.append(dict(source='ClinicalTrials.gov',status='FAILED',detail=str(e),checked_at=stamp))
    seeds=json.loads((ROOT/'sources.json').read_text(encoding='utf8'))
    for source, spec in seeds['known_records'].items():
        good,errors=0,[]
        for entry in spec['records']:
            try:
                incoming.append(national_record(source,entry['id'],entry['url'],spec['parser']))
                good+=1
            except Exception as e:
                errors.append(str(e))
        coverage.append(dict(source=source,status='verified: known records only' if not errors else 'DEGRADED / FAILED',
            detail=f'{good}/{len(spec["records"])} known records read. New-trial discovery unsupported. '+ '; '.join(errors),checked_at=stamp))
    # These are explicit coverage gaps, not empty query results or fallback claims.
    for c in seeds['unsupported']:
        coverage.append(dict(c,checked_at='2026-10-26 verification attempt; not checked daily',status='UNSUPPORTED — not monitored'))
    # A complete ingestion failure should fail the workflow and preserve the published feed.
    if not incoming:
        raise RuntimeError('All implemented integrations failed; refusing to overwrite published data')
    state=update(state,incoming,stamp)
    state['coverage']=coverage
    state_path.parent.mkdir(exist_ok=True)
    temp=state_path.with_suffix('.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf8')
    temp.replace(state_path)
    render(state,coverage,ROOT/'docs',args.base_url.rstrip('/')+'/')
    print(json.dumps({'records':len(state['records']),'trials':len(state['trials']),'events':len(state['events']),'coverage':coverage},indent=2))


if __name__=='__main__':
    run()
