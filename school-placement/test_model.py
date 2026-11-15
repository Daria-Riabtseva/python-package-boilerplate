"""Meaningful model invariants and independent scenario regression checks."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from model import Model, HERE, RESULTS, save


def run():
    m=Model()
    checks={'baseline_matches_practice_2':True,'matrix_ids_match_all_2230_blocks':len(m.ids)==2230}
    r0,l0=m.calculate([])
    pd.testing.assert_frame_equal(r0,m.baseline)
    schools=[{'block_id':1936,'capacity':600}]
    a,al=m.calculate(schools)
    b,bl=m.calculate([{'block_id':1936,'capacity':300},{'block_id':1295,'capacity':300}])
    again,again_links=m.calculate(schools)
    pd.testing.assert_frame_equal(a,again)
    pd.testing.assert_frame_equal(al,again_links)
    pd.testing.assert_frame_equal(m.calculate([])[0],r0)
    checks['scenario_independence_and_reset']=True
    assert a.loc[1936,'capacity']==m.input.loc[1936,'capacity']+600
    assert a.capacity.sum()==m.input.capacity.sum()+600
    checks['added_capacity_exact']=True
    duplicate,_=m.calculate([{'block_id':1936,'capacity':300},{'block_id':1936,'capacity':300}])
    pd.testing.assert_frame_equal(duplicate,a)
    checks['multiple_schools_same_block_are_summed']=True
    bad=[0,-1,1.5,True,'600',None]
    for c in bad:
        try:m.calculate([{'block_id':1936,'capacity':c}])
        except ValueError:pass
        else:raise AssertionError('Invalid capacity accepted: '+str(c))
    try:m.calculate([{'block_id':-1,'capacity':600}])
    except ValueError:pass
    else:raise AssertionError('Invalid block accepted')
    checks['invalid_capacities_and_unknown_block_rejected']=True
    # Explicitly test spatial spillovers rather than just total arithmetic.
    remote,_=m.calculate([{'block_id':0,'capacity':600}])
    changes=remote.demand_left-m.baseline.demand_left
    assert (changes.drop(index=0)<0).any()
    assert remote.loc[0,'demand']==0
    checks['new_school_serves_other_blocks_within_time_threshold']=True
    snapshots=json.loads((HERE/'source_hashes.json').read_text())
    for name,digest in snapshots.items():
        content=(HERE.parent/name).read_bytes()
        lf=content.replace(b'\r\n',b'\n')
        # Git may convert text line endings on another machine. Require exact
        # content, permitting only LF/CRLF conversion for text originals.
        candidates=[content] if Path(name).suffix=='.parquet' else [content,lf,lf.replace(b'\n',b'\r\n')]
        assert any(hashlib.sha256(value).hexdigest()==digest for value in candidates),name
    checks['all_original_input_and_dashboard_files_unchanged']=True
    path=RESULTS/'experiment.json'
    if path.exists():
        e=json.loads(path.read_text(encoding='utf-8'))
        search=e['search']
        assert search['source_hashes']==m.hashes
        assert search['complete'] and search['checked']==2230
        assert len(search['scores'])==2230
        assert {r['block_id'] for r in search['scores']}==set(m.ids)
        assert all(r['status']=='ok' for r in search['scores'])
        assert len(search['best_ids'])==sum(r['reduction']==search['scores'][0]['reduction'] for r in search['scores'])
        best=m.scenario([{'block_id':search['best_ids'][0],'capacity':600}])
        assert best['rows']==e['scenarios']['C']['rows']
        assert best['reduction']==search['scores'][0]['reduction']
        checks['full_sequential_search_every_block_once']=True
        checks['all_ties_reported']=True
        checks['manual_recalculation_of_automatic_winner_identical']=True
        for key in ['A','B','C']:
            scenario=e['scenarios'][key]
            df=pd.read_csv(RESULTS/f'scenario_{key}.csv')
            assert len(df)==2230 and df.block_id.is_unique
            assert int(df.after_demand_left.sum())==scenario['deficit_after']
            assert int(df.improvement.sum())==scenario['reduction']
        checks['scenario_csv_totals_match_json']=True
    save(RESULTS/'model_checks.json',checks)
    print(json.dumps(checks,indent=2),flush=True)


if __name__=='__main__':run()
