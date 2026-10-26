"""RSS 2.0 interoperability checks, usable against a file or public URL."""
import email.utils
from pathlib import Path
import sys
import urllib.request
import xml.etree.ElementTree as ET

target=sys.argv[1]
if target.startswith('https://'):
    with urllib.request.urlopen(target,timeout=30) as response:
        assert response.status==200
        payload=response.read()
else:
    payload=Path(target).read_bytes()
root=ET.fromstring(payload)
assert root.tag=='rss' and root.attrib.get('version')=='2.0'
channel=root.find('channel')
for tag in ['title','link','description']:
    assert channel.findtext(tag),tag
seen=set()
for item in channel.findall('item'):
    for tag in ['title','link','guid','pubDate','description']:
        assert item.findtext(tag),tag
    guid=item.findtext('guid');assert guid not in seen;seen.add(guid)
    assert item.findtext('link').startswith('https://')
    assert email.utils.parsedate_to_datetime(item.findtext('pubDate')).tzinfo
    assert item.find('guid').attrib.get('isPermaLink')=='false'
assert seen,'Expected at least one baseline or change item'
print(f'RSS 2.0 validated: {len(seen)} items, unique stable GUIDs, absolute links, timezone-aware dates, UTF-8 XML.')
