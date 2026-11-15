"""Check API validation, real streamed progress and interruption without fake results."""
import json
import time
import requests
from model import RESULTS, save

BASE='http://127.0.0.1:8765'
checks={}
for capacity in [0,-1,1.5,True,'600']:
    r=requests.post(BASE+'/api/scenario',json={'schools':[{'block_id':1936,'capacity':capacity}]},timeout=15)
    assert r.status_code==400 and 'error' in r.json()
checks['server_rejects_invalid_capacities']=True
r=requests.post(BASE+'/api/scenario',json={'schools':[]},headers={'Origin':'https://example.com'},timeout=10)
assert r.status_code==403
checks['cross_origin_mutation_rejected']=True
assert requests.get(BASE+'/../pyproject.toml',timeout=10).status_code==404
checks['arbitrary_files_not_exposed']=True
# Start a real fresh 601-place search. Observe actual calculations, then close
# the connection explicitly; do not save or present it as a complete search.
events=[]
with requests.post(BASE+'/api/search',json={'capacity':601,'force':True},stream=True,timeout=30) as r:
    assert r.status_code==200
    for line in r.iter_lines(chunk_size=1):
        if not line:continue
        event=json.loads(line)
        events.append(event)
        if event['type']=='progress' and event['checked']==2:break
progress=[e for e in events if e['type']=='progress']
assert [e['checked'] for e in progress]==[1,2]
assert all(e['total']==2230 and e['last']['status']=='ok' for e in progress)
checks['fresh_search_streams_real_per_candidate_progress']=True
for _ in range(30):
    r=requests.post(BASE+'/api/scenario',json={'schools':[]},timeout=10)
    if r.status_code!=409:break
    time.sleep(.3)
assert r.status_code==200 and r.json()['deficit_after']==37268
assert not (RESULTS/'search_601.json').exists()
checks['interrupted_search_releases_lock_and_does_not_cache_incomplete_results']=True
save(RESULTS/'api_checks.json',checks)
print(json.dumps(checks,indent=2),flush=True)
