"""Copy immutable inputs and existing visual assets into the new application."""
from pathlib import Path
import shutil
from hashlib import sha256
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
files={**{f'data/{n}':ROOT/'data/kemerovo/results'/n for n in ['blocks_metrics.geojson','travel_time.parquet','study_metadata.json']},
    'reference/dashboard.html':ROOT/'dashboard.html',
    **{f'vendor/{n}':ROOT/'scripts/vendor/leaflet'/n for n in ['leaflet.js','leaflet.css','LICENSE']}}
hashes={}
for dest,source in files.items():
    path=HERE/dest
    path.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,path)
    hashes[str(source.relative_to(ROOT))]=sha256(source.read_bytes()).hexdigest()
(HERE/'source_hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print('Скопированы данные и исходный дашборд. Оригиналы не изменены.')
