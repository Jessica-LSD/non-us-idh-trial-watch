"""CDE browser collector and validated snapshot reader; no stealth or challenge bypass."""
import datetime as dt
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parent
HOST='https://www.chinadrugtrials.org.cn'
TERMS=['HMPL-306','HMPL306','HMPL 306','ranosidenib','safusidenib','AB-218','AB218','AB 218','DS-1001','DS-1001b','DS1001']
PATH=ROOT/'data/china-browser.json'


def value(rows,label):
    for row in rows:
        for i,cell in enumerate(row[:-1]):
            if re.sub(r'\s+','',cell)==label:
                return ' '.join(row[i+1].split())
    return ''


def parse_cde(document, observed_at, listing_status=''):
    from watch import assets
    rows=document['rows']
    identifier=value(rows,'登记号')
    title=value(rows,'试验专业题目') or value(rows,'试验通俗题目')
    drug=value(rows,'药物名称')
    matched=assets(drug+' '+title)
    phase=value(rows,'试验分期')
    condition=value(rows,'适应症')
    if not re.fullmatch(r'CTR\d{8}',identifier) or not title or not phase or not condition or not matched:
        raise ValueError('CDE required trial fields or exact asset evidence missing')
    if not document['url'].startswith(HOST+'/clinicaltrials.searchlistdetail.dhtml?id='):
        raise ValueError('Unexpected CDE source URL')
    # 相关登记号 means related registration; it is NOT proof of the same trial.
    # In particular CTR20263911 (Phase III) references CTR20252100 (Phase I).
    return dict(source='China CDE / NMPA',id=identifier,ids=[identifier],assets=matched,
        protocol=re.split(r'[;；]',value(rows,'试验方案编号'))[0].strip(),title=title,indications=[condition],phase=[phase],
        status=listing_status or value(rows,'试验状态'),enrollment={'target':value(rows,'目标入组人数'),'enrolled':value(rows,'已入组人数'),'actual':value(rows,'实际入组总人数')},
        countries=['China'],start=value(rows,'第一例受试者入组日期'),primary_completion='',completion=value(rows,'试验完成日期'),
        registered='',posted=value(rows,'首次公示信息日期'),updated='',outcomes={'primary':value(rows,'主要终点指标及评价时间'),'secondary':value(rows,'次要终点指标及评价时间')},
        eligibility={'inclusion':value(rows,'入选标准'),'exclusion':value(rows,'排除标准')},interventions=drug,
        results=value(rows,'临床试验结果摘要'),url=document['url'],observed_at=observed_at)


def load_snapshot():
    if not PATH.exists():
        return [],dict(source='China CDE / NMPA',status='FAILED — no verified snapshot',detail='Browser collector has not produced data.',checked_at='Never')
    data=json.loads(PATH.read_text(encoding='utf8'))
    records=data.get('records',[])
    detail=f'{len(records)} directly captured CDE records. Last successful capture: {data.get("last_success","Never")}. '+data.get('detail','')
    return records,dict(source='China CDE / NMPA',status=data['status'],detail=detail,checked_at=data.get('last_attempt',data.get('last_success','Never')))


ROWS_JS="""() => Array.from(document.querySelectorAll('tr')).map(tr => Array.from(tr.children).filter(x => ['TD','TH'].includes(x.tagName)).map(x => x.innerText.trim()))"""
LIST_JS="""() => Array.from(document.querySelectorAll('tr')).map(tr => ({cells:Array.from(tr.children).map(x=>x.innerText.trim()),key:tr.querySelector('a[id]')?.id})).filter(r=>r.cells.some(c=>/^CTR\\d{8}$/.test(c)))"""


def search(page,term):
    from watch import assets
    page.goto(HOST+'/clinicaltrials.searchlist.dhtml',wait_until='domcontentloaded')
    page.locator('#searchfrm input[name="keywords"]').fill(term)
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#searchfrm').get_by_role('button',name='查询',exact=True).click()
    found={}
    pages=0
    while True:
        text=page.locator('body').inner_text()
        count=re.search(r'当前第\s*(\d+)\s*页，共\s*(\d+)\s*页，共\s*(\d+)\s*条记录',text)
        if not count:
            raise ValueError('CDE result count absent; challenge or layout change. No bypass attempted.')
        current,total,expected=map(int,count.groups())
        if total>25:
            raise ValueError('Unexpectedly broad CDE search; refusing unfiltered results')
        for row in page.evaluate(LIST_JS):
            cells=row['cells']
            if len(cells)!=6 or not row.get('key'):
                raise ValueError('CDE listing schema changed')
            found[cells[1]]={'key':row['key'],'status':cells[2],'assets':assets(cells[3]+' '+cells[5])}
        pages+=1
        if current>=total or expected==0:
            if len(found)!=expected:
                raise ValueError('CDE result count and pagination disagree')
            return found
        if pages>=25:
            raise ValueError('CDE pagination guard')
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.get_by_role('link',name='Next',exact=True).click()


def collect():
    from playwright.sync_api import sync_playwright
    timestamp=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    previous=json.loads(PATH.read_text(encoding='utf8')) if PATH.exists() else {'records':[]}
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps({**previous,'last_attempt':timestamp,'status':'DEGRADED — fresh browser capture not completed',
        'detail':'The latest browser attempt has not completed successfully. Last verified records retained with their original timestamps.'},ensure_ascii=False,indent=2),encoding='utf8')
    diagnostics=ROOT/'work/china-diagnostics'
    diagnostics.mkdir(parents=True,exist_ok=True)
    page=None
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chromium')
            context=browser.new_context()
            page=context.new_page()
            page.set_default_timeout(45000)
            page.set_default_navigation_timeout(60000)
            page.goto(HOST,wait_until='domcontentloaded')
            # A positive and a negative control prevent a broken search silently looking successful.
            positive=search(page,'HMPL-306')
            if not any(r['assets']==['HMPL-306'] for r in positive.values()):
                raise ValueError('CDE positive search control failed')
            if search(page,'IDHWATCHNONSENSE987654321'):
                raise ValueError('CDE negative search control failed')
            found=dict(positive)
            for term in TERMS:
                if term!='HMPL-306':
                    found.update(search(page,term))
            records=[]
            for identifier,listing in sorted(found.items()):
                if not listing['assets']:
                    continue
                url=HOST+'/clinicaltrials.searchlistdetail.dhtml?id='+listing['key']
                page.goto(url,wait_until='domcontentloaded')
                page.get_by_role('button',name=re.compile('公示的试验信息')).click()
                page.locator('#collapseTwo').wait_for(state='visible')
                # Validate required detail content, not just the opened panel.
                page.get_by_text('试验方案编号',exact=True).wait_for(state='visible')
                doc={'url':url,'rows':page.evaluate(ROWS_JS)}
                record=parse_cde(doc,timestamp,listing['status'])
                if record['id']!=identifier:
                    raise ValueError('CDE detail/listing identifier mismatch')
                records.append(record)
            browser.close()
        if not records:
            raise ValueError('CDE collector found no verified records')
        data={'records':records,'last_success':timestamp,'last_attempt':timestamp,'status':'verified: browser discovery + details',
            'detail':'Daily standard Chromium browser search. All configured aliases, positive/negative controls and pagination checked. Related trial IDs are not deduplicated. No CAPTCHA solving, proxy rotation or stealth.'}
        exit_code=0
    except Exception as error:
        data={**previous,'last_attempt':timestamp,'status':'DEGRADED — browser automation failed; last verified capture retained',
            'detail':str(error)[:1200]+'. Stored records retain their original capture timestamps; not a fresh no-change result.'}
        exit_code=1
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in data.items() if k!='records'},ensure_ascii=True,indent=2))
    return exit_code


if __name__=='__main__':
    sys.exit(collect())
