import copy
import datetime as dt
import email.utils
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
import watch

STAMP='2026-10-26T10:00:00+00:00'

def record(identifier='NCT00000001',source='ClinicalTrials.gov'):
    return dict(id=identifier, ids=[identifier], source=source, protocol='AB-218-G104',
        assets=['safusidenib'], title='A study of safusidenib', indications=['Glioma'],phase=['PHASE2'],
        status='RECRUITING',countries=['China'],enrollment=50,start='2026-01-01',
        completion='2028-01-01',updated='2026-10-01',url='https://clinicaltrials.gov/study/'+identifier)


class WatchTests(unittest.TestCase):
    def test_aliases(self):
        for text in ['DS 1001b','AB218','AB-218','SAFUSIDENIB','沙福司替尼']:
            self.assertEqual(watch.assets(text),['safusidenib'])
        for text in ['HMPL 306','HMPL306','ranosidenib']:
            self.assertEqual(watch.assets(text),['HMPL-306'])
        self.assertEqual(watch.assets('ivosidenib HMPL-523'),[])

    def test_no_repeat_and_date_noise(self):
        r=record()
        s=watch.update({},[r],STAMP)
        self.assertEqual(len(s['events']),1)
        r['updated']='2026-10-25'
        self.assertEqual(len(watch.update(s,[r],STAMP)['events']),1)

    def test_material_change_and_reversion(self):
        r=record(); s=watch.update({},[r],STAMP)
        r['status']='COMPLETED';s=watch.update(s,[r],STAMP)
        self.assertEqual(s['events'][-1]['changes'],['status'])
        r['status']='RECRUITING';s=watch.update(s,[r],STAMP)
        self.assertEqual(len(set(e['guid'] for e in s['events'])),3)

    def test_cross_registry_dedup_transitive(self):
        a=record(); b=record('ChiCTR2300070430','China ChiCTR')
        b['protocol']='different';b['ids']+=['CTR20230597']
        c=record('CTR20230597','China CDE');c['protocol']='AB-218-G104'
        s=watch.update({},[a,b,c],STAMP)
        self.assertEqual(len(s['trials']),1)
        self.assertEqual(len(s['events']),1)
        self.assertEqual(len(s['events'][0]['records']),3)

    def test_similar_titles_not_merged(self):
        a=record(); b=record('NCT00000002');b['protocol']='AB-218-G203'
        self.assertEqual(len(watch.update({},[a,b],STAMP)['trials']),2)

    def test_failed_source_retains_last_good_records(self):
        s=watch.update({},[record()],STAMP)
        nxt=watch.update(s,[],STAMP)
        self.assertEqual(s['records'],nxt['records'])
        self.assertEqual(s['events'],nxt['events'])

    def test_rss_contract_and_escape(self):
        r=record();r['title']='A & B <study>';s=watch.update({},[r],STAMP)
        class TestDirectory:
            def __enter__(self):
                self.path=watch.ROOT/'test-output'
                self.path.mkdir(exist_ok=True)
                return str(self.path)
            def __exit__(self,*args):
                for p in self.path.iterdir():
                    p.unlink()
                self.path.rmdir()
        with TestDirectory() as d:
            watch.render(s,[],Path(d),watch.BASE)
            root=ET.parse(Path(d)/'feed.xml').getroot()
            self.assertEqual(root.attrib['version'],'2.0')
            item=root.find('channel/item')
            self.assertEqual(item.find('guid').attrib['isPermaLink'],'false')
            self.assertIsNotNone(email.utils.parsedate_to_datetime(item.findtext('pubDate')))
            self.assertIn('A &amp; B &lt;study&gt;',item.findtext('description'))
            for tag in ['title','link','guid','pubDate','description']:
                self.assertTrue(item.findtext(tag))

    def test_national_challenge_rejected(self):
        with patch('watch.request',return_value='<html>Enable JavaScript</html>'):
            with self.assertRaises(ValueError):
                watch.national_record('Japan jRCT','jRCT2080225243','https://example.org','jrct')

    def test_ctgov_geography_pagination_and_aliases(self):
        def study(i,country):
            return {'protocolSection':{'identificationModule':{'nctId':i,'briefTitle':'Safusidenib'},
                'statusModule':{},'contactsLocationsModule':{'locations':[{'country':c} for c in country]},
                'armsInterventionsModule':{'interventions':[{'name':'AB-218'}]}}}
        pages=[{'studies':[study('NCT00000001',['United States']),study('NCT00000002',[])],'nextPageToken':'two'},
            {'studies':[study('NCT00000003',['United States','China'])]}]
        import json
        with patch('watch.request',side_effect=[json.dumps(p) for p in pages]) as mock:
            result=watch.ctgov()
            self.assertEqual([r['id'] for r in result],['NCT00000003'])
            self.assertIn('pageToken=two',mock.call_args.args[0])

    def test_tables_ignore_comments_and_scripts(self):
        rows=watch.Tables('<!--<tr><td>fake</td></tr>--><table><tr><th>Phase</th><td>2<script>bad</script></td></tr></table>').rows
        self.assertEqual(rows,[['Phase','2']])

    def test_ctis_search_schema_and_pagination(self):
        import json
        with patch('watch.request',side_effect=[
            json.dumps({'data':[{'ctNumber':'one'}],'pagination':{'nextPage':True,'totalRecords':2}}),
            json.dumps({'data':[{'ctNumber':'two'}],'pagination':{'nextPage':False,'totalRecords':2}})]) as mock:
            self.assertEqual(len(watch.ctis_search('HMPL-306')),2)
            self.assertEqual(mock.call_args.args[1]['pagination']['page'],2)
        with patch('watch.request',return_value='{}'):
            with self.assertRaises(ValueError): watch.ctis_search('HMPL-306')

if __name__=='__main__':
    unittest.main()
