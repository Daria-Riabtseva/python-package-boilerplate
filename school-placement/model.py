"""Independent scenarios using the unmodified BlocksNet 1.0.0a9 method."""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
import pandas as pd
from blocksnet.analysis.provision import competitive_provision
from blocksnet.config import log_config

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'data'
RESULTS = HERE / 'results'


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


class Model:
    def __init__(self):
        log_config.set_disable_tqdm(True)
        log_config.set_logger_level('ERROR')
        self.geo = json.loads((SOURCE / 'blocks_metrics.geojson').read_text(encoding='utf-8'))
        self.meta = json.loads((SOURCE / 'study_metadata.json').read_text(encoding='utf-8'))
        self.props = pd.DataFrame([f['properties'] for f in self.geo['features']]).set_index('block_id')
        self.ids = list(self.props.index.astype(int))
        self.matrix = pd.read_parquet(SOURCE / 'travel_time.parquet')
        self.matrix.index = self.matrix.index.astype(int)
        self.matrix.columns = self.matrix.columns.astype(int)
        assert self.ids == list(self.matrix.index) == list(self.matrix.columns)
        assert np.isfinite(self.matrix.to_numpy()).all()
        self.input = self.props[['building_population','school_capacity']].rename(columns={'building_population':'population','school_capacity':'capacity'})
        self.hashes = {name: hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in ['blocks_metrics.geojson','travel_time.parquet','study_metadata.json']}
        self.baseline, self.links = self.calculate([])
        for col in self.baseline:
            saved = 'provision_' + col
            if saved in self.props:
                np.testing.assert_allclose(self.baseline[col], pd.to_numeric(self.props[saved]), equal_nan=True, err_msg=col)
        self.deficit = int(self.baseline.demand_left.sum())

    def validate(self, schools):
        if not isinstance(schools, list) or len(schools)>100:
            raise ValueError('Задайте список не более 100 школ.')
        for s in schools:
            if type(s.get('block_id')) is not int or s['block_id'] not in self.ids:
                raise ValueError('Неизвестный квартал.')
            if type(s.get('capacity')) is not int or s['capacity'] <= 0:
                raise ValueError('Вместимость должна быть положительным целым числом.')

    def calculate(self, schools):
        self.validate(schools)
        data = self.input.copy(deep=True)
        for s in schools:
            data.loc[s['block_id'],'capacity'] += s['capacity']
        result, links = competitive_provision(data, self.matrix,
            self.meta['normative_school_accessibility_min'],
            self.meta['normative_school_demand_per_1000'], max_depth=self.meta['assumptions']['provision_max_depth'])
        result.loc[result.demand==0,['provision_strong','provision_weak']] = np.nan
        np.testing.assert_allclose(result.demand, result.demand_left+result.demand_within+result.demand_without)
        assert int(result.capacity.sum()) == int(self.input.capacity.sum())+sum(s['capacity'] for s in schools)
        assert int(result.capacity.sum()) == int(result.demand_within.sum()+result.demand_without.sum()+result.capacity_left.sum())
        return result, links

    def package(self, frame, schools, name):
        rows = pd.DataFrame(index=frame.index)
        rows['population'] = self.input.population
        for col in ['capacity','demand','demand_left','demand_within','provision_strong']:
            rows['before_'+col] = self.baseline[col]
            rows['after_'+col] = frame[col]
        rows['improvement'] = rows.before_demand_left-rows.after_demand_left
        rows['delta_provision'] = rows.after_provision_strong-rows.before_provision_strong
        rows.index.name='block_id'
        return {'name':name,'schools':schools,'deficit_before':self.deficit,
            'deficit_after':int(frame.demand_left.sum()),'reduction':self.deficit-int(frame.demand_left.sum()),
            'added_capacity':sum(s['capacity'] for s in schools),
            'improved_blocks':int((rows.improvement>0).sum()),'remaining_blocks':int((frame.demand_left>0).sum()),
            'rows':json.loads(rows.reset_index().to_json(orient='records'))}

    def scenario(self, schools, name='Пользовательский'):
        frame, _ = self.calculate(schools)
        return self.package(frame, schools, name)

    def search(self, capacity, progress=None):
        self.validate([{'block_id':self.ids[0], 'capacity':capacity}])
        scores=[]
        start=time.perf_counter()
        for k, block in enumerate(self.ids):
            try:
                frame,_=self.calculate([{'block_id':int(block),'capacity':capacity}])
                row={'block_id':int(block),'deficit_after':int(frame.demand_left.sum()),'reduction':self.deficit-int(frame.demand_left.sum()),'status':'ok'}
            except Exception as exc:
                row={'block_id':int(block),'status':'error','error':str(exc),'reduction':None}
            scores.append(row)
            if progress: progress(k+1,len(self.ids),row)
        ok=[s for s in scores if s['status']=='ok']
        ok.sort(key=lambda s:(-s['reduction'],s['block_id']))
        best=ok[0]['reduction'] if ok else None
        return {'capacity':capacity,'checked':len(scores),'total':len(self.ids),'complete':len(ok)==len(self.ids),
            'elapsed_seconds':time.perf_counter()-start,'source_hashes':self.hashes,
            'best_ids':[s['block_id'] for s in ok if s['reduction']==best],
            'scores':ok+[s for s in scores if s['status']!='ok']}


if __name__=='__main__':
    t=time.perf_counter()
    m=Model()
    print('baseline',m.deficit,'seconds',time.perf_counter()-t,flush=True)
    t=time.perf_counter()
    r=m.scenario([{'block_id':1936,'capacity':600}], 'А')
    print('scenario',r['reduction'],'seconds',time.perf_counter()-t,flush=True)
