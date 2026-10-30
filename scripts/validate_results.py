"""Validate real saved results and cross-file balances without network requests."""
from pathlib import Path
import json
import ast
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import geopandas as gpd
import nbformat

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'data/kemerovo/results'


def main():
    final = gpd.read_file(RESULTS / 'blocks_metrics.geojson').set_index('block_id')
    assert final.index.is_unique and len(final) > 0
    manifest = pd.read_csv(RESULTS / 'indicator_manifest.csv')
    calibration = json.loads((RESULTS / 'population_calibration.json').read_text(encoding='utf-8'))
    assert int(final.building_population.sum()) == calibration['target_total']
    assert (final.building_population % 1 == 0).all()
    assert np.isclose(final.building_population_uncalibrated.sum(), calibration['uncalibrated_total'])
    assert (final.loc[final.building_population_uncalibrated == 0,'building_population'] == 0).all()
    assert manifest.indicator.is_unique and set(manifest.indicator).issubset(final.columns)
    sources = {
        'landuse_':'landuse.geojson', 'building_':'buildings.geojson',
        'school_':'schools.geojson', 'provision_':'provision.geojson',
        'density_':'density.geojson', 'transport_':'graph_attachment.geojson',
    }
    for prefix, filename in sources.items():
        original = gpd.read_file(RESULTS / filename).set_index('block_id')
        assert original.index.equals(final.index), filename
        for column in final:
            if column.startswith(prefix):
                name = column.removeprefix(prefix)
                left, right = final[column], original[name]
                if pd.api.types.is_numeric_dtype(left) or pd.api.types.is_bool_dtype(left):
                    np.testing.assert_allclose(left, right, equal_nan=True)
                else:
                    assert left.fillna('<missing>').equals(right.fillna('<missing>')), column
    matrix = pd.read_parquet(RESULTS / 'travel_time.parquet')
    matrix.index = matrix.index.astype(int); matrix.columns = matrix.columns.astype(int)
    assert matrix.index.equals(final.index) and matrix.columns.equals(final.index)
    values = matrix.to_numpy()
    assert np.isfinite(values).all() and (values >= 0).all()
    np.testing.assert_allclose(np.diag(values), 0)
    demand = final.provision_demand
    within, without, left = (final['provision_'+c] for c in ['demand_within','demand_without','demand_left'])
    np.testing.assert_allclose(demand, within + without + left)
    np.testing.assert_allclose(final.school_capacity,
                               final.school_capacity_observed_places + final.school_capacity_estimated_places)
    assert np.isclose(final.school_capacity.sum(), within.sum()+without.sum()+final.provision_capacity_left.sum())
    nonzero = demand > 0
    np.testing.assert_allclose(final.loc[nonzero,'provision_provision_strong'],within[nonzero]/demand[nonzero])
    np.testing.assert_allclose(final.loc[nonzero,'provision_provision_weak'],(within[nonzero]+without[nonzero])/demand[nonzero])
    assert final.loc[~nonzero,'provision_provision_strong'].isna().all()
    for col in ['density_gsi','density_mxi']:
        assert final[col].dropna().between(0,1).all()
    assert final.loc[~final.density_density_defined,'spacematrix_morphotype'].isna().all()
    links = pd.read_csv(RESULTS / 'school_demand_links.csv')
    assert links.source.isin(final.index).all() and links.target.isin(final.index).all()
    assert (links.value >= 0).all()
    local_supply = np.minimum(demand,final.school_capacity).sum()
    assert np.isclose(links.value.sum()+local_supply,within.sum()+without.sum())
    for filename, count_col, excess_file in [
        ('buildings_model.geojson','building_count','buildings_outside_blocks.geojson'),
        ('schools_model.geojson','school_count','schools_outside_blocks.geojson')]:
        prepared=gpd.read_file(ROOT/'data/kemerovo/processed'/filename)
        excess=gpd.read_file(ROOT/'data/kemerovo/processed'/excess_file)
        assert len(prepared)==final[count_col].sum()+len(excess), filename
    notebook=nbformat.read(ROOT/'examples/kemerovo_pipeline.ipynb',as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type=='code':
            ast.parse(cell.source)
            assert cell.execution_count is not None
            assert all(output.output_type!='error' for output in cell.outputs)
    report={
        'checked_utc':datetime.now(timezone.utc).isoformat(),'status':'passed',
        'blocks':len(final),'manifest_fields':len(manifest),'matrix_shape':list(matrix.shape),
        'school_demand_links':len(links),'population_total':int(final.building_population.sum()),
        'population_source':calibration['source'],'uncalibrated_model_population':calibration['uncalibrated_total'],
        'model_school_capacity':float(final.school_capacity.sum()),
        'school_capacity_estimated_fraction':float(final.school_capacity_estimated_places.sum()/final.school_capacity.sum()),
        'model_school_demand':int(demand.sum()),'model_demand_left':int(left.sum()),
        'far_snap_over_1000m':int(final.transport_far_snap_over_1000m.sum()),
        'checks':['unique IDs','all manifest fields','source/result equality','matrix shape and values',
                  'school supply/demand balance','provision ratios','links and local supply balance',
                  'object counts and excess objects','density domains','executed notebook without errors']}
    (RESULTS/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
