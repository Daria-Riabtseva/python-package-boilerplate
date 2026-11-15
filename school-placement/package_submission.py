"""Package the runnable app and submission evidence, without caches or duplicates."""
from pathlib import Path
import zipfile
import json

HERE=Path(__file__).resolve().parent
OUT=HERE/'submission/school-placement.zip'
OUT.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(OUT,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for path in sorted(HERE.rglob('*')):
        rel=path.relative_to(HERE)
        if not path.is_file() or any(p in rel.parts for p in ['.test-cache','__pycache__','submission','.venv']):continue
        # Screenshots are optional QA artifacts, not application inputs.
        if path.suffix=='.png':continue
        # Full scenario JSONs already live in experiment.json. Keep all CSVs.
        if path.name in ['scenario_A.json','scenario_B.json','scenario_C.json']:continue
        if path.suffix=='.json' and rel.parts[0]=='results':
            compact=json.dumps(json.loads(path.read_text(encoding='utf-8')),ensure_ascii=False,allow_nan=False,separators=(',',':'))
            archive.writestr(str(Path('school-placement')/rel).replace('\\','/'),compact.encode('utf-8'))
        else:archive.write(path,Path('school-placement')/rel)
print(f'{OUT}: {OUT.stat().st_size:,} bytes')
with zipfile.ZipFile(OUT) as archive:
    assert archive.testzip() is None
    names=set(archive.namelist())
    assert 'school-placement/data/travel_time.parquet' in names
    assert 'school-placement/reference/dashboard.html' in names
