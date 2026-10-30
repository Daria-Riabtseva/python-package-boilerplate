"""Build a single HTML report from saved BlocksNet results; never fetch study data."""
from pathlib import Path
import argparse
import json
import math
import gzip
import base64
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite(v) for v in value]
    return value


def build(source: Path, output: Path):
    names = ['blocks_metrics.geojson', 'study_metadata.json', 'indicator_manifest.csv',
             'travel_time.parquet', 'school_demand_links.geojson', 'spacematrix_clusters.csv']
    missing = [name for name in names if not (source / name).exists()]
    if missing:
        raise FileNotFoundError('Сначала завершите ноутбук. Нет файлов: ' + ', '.join(missing))
    geo = json.loads((source / names[0]).read_text(encoding='utf-8'))
    meta = json.loads((source / names[1]).read_text(encoding='utf-8'))
    if 'population_calibration' in meta:
        total = sum(f['properties']['building_population'] for f in geo['features'])
        assert total == meta['population_calibration']['target_total'], 'Население не совпадает с контрольной суммой'
    manifest = pd.read_csv(source / names[2]).fillna('')
    matrix = pd.read_parquet(source / names[3])
    links = json.loads((source / names[4]).read_text(encoding='utf-8'))
    clusters = pd.read_csv(source / names[5]).fillna('')
    ids = [int(f['properties']['block_id']) for f in geo['features']]
    assert len(ids) == len(set(ids)) and ids, 'Неверные идентификаторы кварталов'
    matrix.index = matrix.index.astype(int)
    matrix.columns = matrix.columns.astype(int)
    assert ids == list(matrix.index) == list(matrix.columns), 'Матрица и кварталы не совпадают'
    columns = set().union(*(f['properties'].keys() for f in geo['features']))
    assert set(manifest.indicator).issubset(columns), 'Есть показатели без данных в итоговом GeoJSON'
    data = finite({'geo': geo, 'meta': meta, 'manifest': manifest.to_dict('records'),
                   'matrix': matrix.astype('float64').round(2).to_numpy().tolist(), 'ids': ids,
                   'links': links, 'clusters': clusters.to_dict('records')})
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    # Lossless compression preserves every metric, geometry and matrix entry.
    compressed = gzip.compress(payload.encode('utf-8'), compresslevel=9, mtime=0)
    assert gzip.decompress(compressed).decode('utf-8') == payload
    payload = base64.b64encode(compressed).decode('ascii')
    vendor = ROOT / 'scripts/vendor/leaflet'
    page = TEMPLATE.replace('__PAYLOAD__', payload)
    page = page.replace('__LEAFLET_CSS__', (vendor / 'leaflet.css').read_text(encoding='utf-8'))
    page = page.replace('__LEAFLET_JS__', (vendor / 'leaflet.js').read_text(encoding='utf-8').replace('</script', '<\\/script'))
    page = page.replace('__LEAFLET_LICENSE__', (vendor / 'LICENSE').read_text(encoding='utf-8'))
    if len(page.encode('utf-8')) > 20_000_000:
        raise ValueError('HTML превышает лимит 20 МБ; предыдущий файл не изменён')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    print(f'Создан {output}: {len(ids)} кварталов, {len(manifest)} показателей, {output.stat().st_size:,} байт')


TEMPLATE = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Кемерово · Кварталы и доступность</title>
<!-- Leaflet 1.9.4 license: __LEAFLET_LICENSE__ -->
<style>__LEAFLET_CSS__</style>
<style>
:root{--ink:#15343d;--muted:#597079;--paper:#f2f5f2;--line:#dbe3df;--accent:#087f72}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,sans-serif}
header{background:#123b40;color:#fff;padding:42px max(5vw,20px) 32px}header small{letter-spacing:.18em;color:#b2d9c8}
h1{font-size:clamp(32px,5vw,58px);line-height:1.1;letter-spacing:-.04em;margin:12px 0}h2{font-size:24px;letter-spacing:-.02em}
header p{max-width:830px;color:#d5e7df}main{max-width:1500px;margin:auto;padding:25px 4vw 70px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card,.panel{background:white;border:1px solid var(--line);border-radius:14px;padding:22px}
.card strong{display:block;font-size:30px;line-height:1.2;margin:8px 0}.muted,small{color:var(--muted)}
.notice{padding:16px 20px;background:#fff4d7;border-left:4px solid #d69b2d;margin:20px 0;border-radius:6px}
.controls{display:flex;gap:16px;flex-wrap:wrap;align-items:end;margin-bottom:15px}label{display:block;font-size:13px;font-weight:650}
select,input{display:block;padding:10px 12px;border:1px solid #b6c8c2;border-radius:7px;font:inherit;max-width:100%;background:#fff}
select{min-width:230px}.grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(260px,1fr);gap:18px}
#map{height:660px;border-radius:10px;background:#e5eeea}#legend{margin:12px 0;font-size:13px;display:flex;gap:14px;flex-wrap:wrap}
.dot{display:inline-block;width:12px;height:12px;margin-right:5px;border-radius:3px}.scroll{overflow:auto;max-height:580px}
table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th{text-align:left;position:sticky;top:0;background:#eaf2ee;z-index:1}
td,th{padding:9px 12px;border-bottom:1px solid var(--line)}tbody tr:hover{background:#edf7f1}a{color:#087f72}
section{margin-top:26px}#chart,#scatter{width:100%;height:250px}#selection{max-height:430px;overflow:auto}
.twocol{display:grid;grid-template-columns:1fr 1fr;gap:18px}.badge{display:inline-block;background:#dceee5;color:var(--ink);padding:4px 9px;border-radius:20px;font-size:12px}
button{cursor:pointer;padding:9px 15px;background:var(--accent);color:#fff;border:0;border-radius:7px;font:inherit}
.leaflet-tooltip{max-width:360px;white-space:normal}footer{margin-top:35px;font-size:13px;color:var(--muted)}
@media(max-width:950px){.grid,.twocol{grid-template-columns:1fr}.cards{grid-template-columns:1fr 1fr}#map{height:470px}}
</style></head><body>
<header><small>ТЕХНОЛОГИИ ИИ В УРБАНИСТИКЕ · ПРАКТИКА 02</small>
<h1>Кемерово в масштабе квартала</h1><p>Землепользование, застройка, школьные места и транспортная доступность.
Интерактивный отчёт по сохранённым результатам BlocksNet 1.0.0a9.</p><span class="badge" id="date"></span></header>
<main><div class="cards" id="cards"></div>
<div class="notice"><strong>Учебная модель.</strong> Численность города задана пользователем; её распределение по кварталам и вместимость школ являются модельными оценками.
Автомобильный граф построен из OSM с разрешения пользователя вместо недоступного готового архива.
Время рассчитано по модельным скоростям, без пробок и внеуличных подходов. Это не оценка пешей доступности школ.</div>
<div class="notice" id="quality"></div>
<section class="panel"><div class="controls"><div><label for="metric">Показатель карты и графика</label><select id="metric"></select></div>
<div><label for="origin">Время в пути из квартала</label><select id="origin"></select></div>
<label><input id="showLinks" type="checkbox"> Показать связи школьного спроса</label></div>
<p id="explanation" class="muted"></p><div class="grid"><div><div id="map"></div><div id="legend"></div></div>
<aside><h2>Распределение</h2><svg id="chart" role="img" aria-label="Распределение выбранного показателя"></svg>
<p id="stats" class="muted"></p><h2>Выбранный квартал</h2><div id="selection">Нажмите на квартал на карте.</div></aside></div></section>
<section class="twocol"><div class="panel"><h2>Интенсивность и покрытие застройкой</h2><p class="muted">FSI — площадь этажей / площадь квартала. GSI — доля территории под зданиями.</p><svg id="scatter" role="img" aria-label="FSI и GSI"></svg></div>
<div class="panel"><h2>Наблюдения по данным</h2><div id="findings"></div></div></section>
<section class="panel"><h2>Все показатели по кварталам</h2><div class="controls"><div><label for="search">Поиск по таблице</label><input id="search" placeholder="block_id или тип застройки"></div>
<button id="export">Скачать текущую таблицу CSV</button></div><p class="muted">Таблица включает все сохранённые показатели. Пустое значение означает отсутствие или неопределённость данных.</p><div class="scroll" id="table"></div></section>
<section class="panel"><h2>Матрица времени в пути</h2><p class="muted">Выберите отправной квартал над картой: карта переключится на время до остальных кварталов. Здесь показана строка полной матрицы; нет маршрута — пустое значение.</p><div class="scroll" id="times"></div></section>
<section class="panel"><h2>Характеристики кластеров Spacematrix</h2><p class="muted">Медианные признаки и интерпретации групп. Классификация «Стрелки» основана на пороговых правилах, поэтому названия могут различаться.</p><div class="scroll" id="clusters"></div></section>
<section class="panel"><h2>Распределение школьного спроса</h2><p class="muted">source — квартал спроса, target — квартал школы, value — распределённые места. Линии на карте схематические.</p><div class="scroll" id="links"></div></section>
<section class="panel"><h2>Методика, единицы и ограничения</h2><div id="method"></div><details><summary>Полный перечень показателей</summary><div class="scroll" id="manifest"></div></details></section>
<footer>Данные: © OpenStreetMap contributors, ODbL. Расчёты: BlocksNet. Геоданные встроены в этот HTML;
Leaflet встроен; интернет нужен только для подложки OSM. HTML не запускает геоаналитические расчёты.</footer></main>
<script id="study" type="application/gzip+base64">__PAYLOAD__</script>
<script>__LEAFLET_JS__</script><script>
'use strict';
(async () => {
if (!('DecompressionStream' in window)) throw new Error('Для открытия отчёта используйте современный Edge, Chrome или Firefox.');
const bytes=Uint8Array.from(atob(document.getElementById('study').textContent.trim()),c=>c.charCodeAt(0));
const unpacked=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
const D=JSON.parse(await new Response(unpacked).text()),rows=D.geo.features.map(f=>f.properties);
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=x=>x===null||x===undefined?'Нет данных':typeof x==='number'?x.toLocaleString('ru-RU',{maximumFractionDigits:3}):String(x);
const sum=k=>rows.reduce((s,r)=>s+(Number.isFinite(r[k])?r[k]:0),0);
function table(items,columns){if(!items.length)return '<p>Нет записей.</p>';columns=columns||Object.keys(items[0]);return '<table><thead><tr>'+columns.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+items.map(r=>'<tr>'+columns.map(c=>'<td>'+esc(fmt(r[c]))+'</td>').join('')+'</tr>').join('')+'</tbody></table>';}
const definitions={fsi:['FSI — интенсивность застройки','м²/м²'],gsi:['GSI — покрытие зданиями','доля 0–1'],mxi:['MXI — доля жилой площади','доля 0–1'],l:['L — расчётная этажность','этажи'],osr:['OSR — открытая площадь на площадь этажей','м²/м²'],share_living:['Жилая площадь / пятно','м²/м²'],share_non_living:['Нежилая площадь / пятно','м²/м²'],population_uncalibrated:['Первичная оценка населения OSM','человек, до корректировки'],population:['Население квартала (распределение)','человек, оценка'],footprint_area:['Пятно застройки','м²'],build_floor_area:['Площадь этажей','м²'],living_area:['Жилая площадь','м², оценка'],non_living_area:['Нежилая площадь','м², оценка'],capacity:['Вместимость школ','места'],count:['Количество объектов','объекты'],number_of_floors:['Сумма этажностей зданий','сумма этажей'],mean_number_of_floors:['Средняя этажность зданий','этажи'],provision_strong:['Сильная обеспеченность','доля спроса'],provision_weak:['Слабая обеспеченность','доля спроса'],demand:['Спрос на школьные места','места'],demand_left:['Неудовлетворённый спрос','места'],demand_within:['Спрос, обеспеченный в пределах норматива','места'],demand_without:['Спрос, обеспеченный вне норматива','места'],capacity_left:['Остаток школьных мест','места'],capacity_within:['Места, занятые в пределах норматива','места'],capacity_without:['Места, занятые вне норматива','места'],area_accessibility:['Среднее время с весами площадей','минуты'],site_area:['Площадь квартала','м²'],is_living:['Количество жилых зданий','объекты'],share:['Доля преобладающей функции','доля 0–1'],land_use:['Преобладающая функция','категория']};
Object.assign(definitions,{
residential:['Жилая функция','доля площади 0–1'],business:['Деловая функция','доля площади 0–1'],recreation:['Рекреация','доля площади 0–1'],industrial:['Промышленная функция','доля площади 0–1'],transport:['Транспортная функция','доля площади 0–1'],special:['Специальная функция','доля площади 0–1'],agriculture:['Сельскохозяйственная функция','доля площади 0–1'],landuse_overlap_flag:['Перекрытие зон: сумма долей больше 1','признак'],floors_estimated:['Здания с восстановленной этажностью','объекты'],population_estimated:['Жилые здания с модельным населением','объекты'],area_estimated:['Здания с расчётными площадями','объекты'],capacity_estimated:['Школы с восстановленной вместимостью','объекты'],capacity_estimated_places:['Восстановленные школьные места','места, оценка'],capacity_observed_places:['Школьные места из исходных данных','места'],density_defined:['Определённость показателей застроенного квартала','признак'],spacematrix_cluster:['Кластер Spacematrix','номер группы'],spacematrix_morphotype:['Морфотип Spacematrix','категория'],strelka_morphotype:['Морфотип «Стрелки»','категория'],all_destinations_reachable:['Есть путь до всех привязанных узлов','признак'],transport_snap_distance_m:['Расстояние до узла автомобильного графа','метры'],transport_snap_node_id:['Узел привязки квартала','идентификатор'],transport_far_snap_over_1000m:['Привязка к графу дальше 1 км','признак']});
function def(key){if(key==='travel_time')return ['Время от выбранного квартала','минуты'];let base=key.replace(/^(building|school|provision|density|landuse)_/,'');return definitions[key]||definitions[base]||[key,'сохранённое значение'];}
$('date').textContent='Сохранено: '+new Date(D.meta.created_utc).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'})+' МСК';
const cards=[['Кварталы',rows.length,'расчётные участки'],['Население Кемерово',sum('building_population'),'контрольная численность, указанная пользователем'],['Школы',sum('school_count'),'объекты после устранения вложенных дублей'],['Школьные места',sum('school_capacity'),'включая восстановленную вместимость']];
$('cards').innerHTML=cards.map(([t,v,n])=>'<div class="card"><span>'+esc(t)+'</span><strong>'+esc(fmt(v))+'</strong><small>'+esc(n)+'</small></div>').join('');
$('quality').textContent='Общая численность '+fmt(sum('building_population'))+' взята из сообщения пользователя. По кварталам она распределена пропорционально исходной модели OSM, с точным сохранением общей суммы. У '+fmt(sum('building_floors_estimated')/sum('building_count')*100)+'% зданий этажность восстановлена: распределение жителей по кварталам условно. '+fmt(sum('school_capacity_estimated_places')/sum('school_capacity')*100)+'% школьных мест также восстановлены моделью. У '+rows.filter(r=>!r.landuse_land_use).length+' кварталов функция не назначена; дальняя привязка к графу (>1 км) — у '+rows.filter(r=>r.transport_far_snap_over_1000m).length+' кварталов.';
const keys=['site_area',...D.manifest.map(r=>r.indicator)];
for(const key of keys){let o=document.createElement('option');o.value=key;o.textContent=def(key)[0]+' · '+key;$('metric').append(o);}
let travel=document.createElement('option');travel.value='travel_time';travel.textContent='Время от выбранного квартала';$('metric').append(travel);
for(const id of D.ids){let o=document.createElement('option');o.value=id;o.textContent='Квартал '+id;$('origin').append(o);}
$('metric').value=keys.includes('density_fsi')?'density_fsi':keys[0];
const palette=['#d8edbf','#a6d8b7','#66b9a5','#2c918b','#12666e','#103f57'],catColors=['#087f72','#d99039','#7c72b5','#579dbe','#b85d72','#88a74a','#586f7c','#d6b951','#9b6f4a','#a48ca5','#62aaa0'];
let map,layer,linkLayer;if(window.L){map=L.map('map').setView([55.36,86.09],11);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);}else{$('map').innerHTML='<p>Leaflet недоступен. Проверьте интернет. Таблицы и графики ниже доступны.</p>';}
let activeRows=rows;
function valuesFor(key){if(key==='travel_time'){let i=D.ids.indexOf(Number($('origin').value));return D.matrix[i];}return rows.map(r=>r[key]);}
function histogram(values,categorical){let svg=$('chart');let body='';const w=380,h=230;let counts=[],labels=[];
 if(categorical){let c={};values.filter(v=>v!==null&&v!==undefined).forEach(v=>c[v]=(c[v]||0)+1);let entries=Object.entries(c).sort((a,b)=>b[1]-a[1]);counts=entries.map(x=>x[1]);labels=entries.map(x=>x[0]);}
 else{let v=values.filter(Number.isFinite);if(v.length){let lo=Math.min(...v),hi=Math.max(...v);if(lo===hi){counts=[v.length];labels=[fmt(lo)];}else{let step=(hi-lo)/10;counts=Array(10).fill(0);v.forEach(x=>counts[Math.min(9,Math.floor((x-lo)/step))]++);labels=counts.map((_,i)=>fmt(lo+i*step)+'–'+fmt(lo+(i+1)*step));}}}
 let max=Math.max(1,...counts);counts.forEach((c,i)=>{let bw=(w-40)/counts.length,bh=c/max*150;body+=`<rect x="${20+i*bw}" y="${180-bh}" width="${Math.max(1,bw-3)}" height="${bh}" fill="#087f72"><title>${esc(labels[i])}: ${c}</title></rect>`;});
 body+='<text x="20" y="212" font-size="12" fill="#597079">'+(categorical?'Категории (подсказка при наведении)':'Интервалы: подсказка при наведении')+'</text>';svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.innerHTML=body;}
function update(){const key=$('metric').value,vals=valuesFor(key),numeric=vals.some(Number.isFinite),finiteVals=vals.filter(Number.isFinite);let lo=numeric?Math.min(...finiteVals):0,hi=numeric?Math.max(...finiteVals):0;
 let categories=[...new Set(vals.filter(v=>v!==null&&v!==undefined).map(String))].sort();
 function color(v){if(v===null||v===undefined)return '#d4d9d6';if(!numeric)return catColors[categories.indexOf(String(v))%catColors.length];return palette[Math.min(5,Math.floor((v-lo)/(hi-lo||1)*5.999))];}
 const idx=new Map(D.ids.map((id,i)=>[id,i]));if(layer)layer.remove();if(map){layer=L.geoJSON(D.geo,{style:f=>({color:'#365b58',weight:.35,fillOpacity:.78,fillColor:color(vals[idx.get(Number(f.properties.block_id))])}),onEachFeature:(f,l)=>{let r=f.properties;l.bindTooltip('Квартал '+esc(r.block_id)+'<br>'+esc(def(key)[0])+': '+esc(fmt(vals[idx.get(Number(r.block_id))]))+' '+esc(def(key)[1]));l.on('click',()=>{$('selection').innerHTML=table(Object.entries(r).map(([indicator,value])=>({indicator,value})));});}}).addTo(map);if(!map._studyFit){map.fitBounds(layer.getBounds());map._studyFit=true;}}
 $('explanation').textContent=def(key)[0]+'. Единицы: '+def(key)[1]+'. Серый цвет — нет определённого значения.';
 $('legend').innerHTML=numeric?'<span>Светлее: '+esc(fmt(lo))+'</span>'+palette.map(c=>'<span class="dot" style="background:'+c+'"></span>').join('')+'<span>Темнее: '+esc(fmt(hi))+'</span>':categories.map(c=>'<span><i class="dot" style="background:'+color(c)+'"></i>'+esc(c)+'</span>').join('');
 histogram(vals,!numeric);$('stats').textContent='Определено: '+vals.filter(v=>v!==null&&v!==undefined).length+' / '+rows.length+(numeric?'; среднее: '+fmt(finiteVals.reduce((a,b)=>a+b,0)/finiteVals.length):'');
 const i=D.ids.indexOf(Number($('origin').value));$('times').innerHTML=table(D.ids.map((id,j)=>({source_block_id:D.ids[i],target_block_id:id,time_min:D.matrix[i][j]})));}
$('metric').onchange=update;$('origin').onchange=()=>{$('metric').value='travel_time';update();};
$('showLinks').onchange=()=>{if(linkLayer)linkLayer.remove();if(map&&$('showLinks').checked)linkLayer=L.geoJSON(D.links,{style:{color:'#d58a2d',weight:1.2,opacity:.55},onEachFeature:(f,l)=>l.bindTooltip(Object.entries(f.properties).map(([k,v])=>esc(k)+': '+esc(fmt(v))).join('<br>'))}).addTo(map);};
function filter(){const q=$('search').value.toLowerCase();activeRows=rows.filter(r=>Object.values(r).some(v=>String(v??'').toLowerCase().includes(q)));$('table').innerHTML=table(activeRows,['block_id',...keys]);}
$('search').oninput=filter;$('export').onclick=()=>{let cols=['block_id',...keys],csv=[cols,...activeRows.map(r=>cols.map(k=>r[k]??''))].map(a=>a.map(x=>'"'+String(x).replaceAll('"','""')+'"').join(';')).join('\r\n');let a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));a.download='kemerovo_metrics.csv';a.click();URL.revokeObjectURL(a.href);};
$('clusters').innerHTML=table(D.clusters);$('manifest').innerHTML=table(D.manifest.map(r=>({...r,label:def(r.indicator)[0],unit:def(r.indicator)[1]})));$('links').innerHTML=table(D.links.features.map(f=>f.properties));
const points=rows.filter(r=>Number.isFinite(r.density_fsi)&&Number.isFinite(r.density_gsi));let maxF=Math.max(1,...points.map(r=>r.density_fsi));
$('scatter').setAttribute('viewBox','0 0 500 250');$('scatter').innerHTML='<path d="M40 15V215H480" fill="none" stroke="#597079"/><text x="430" y="242" font-size="13">GSI →</text><text x="5" y="20" font-size="13">FSI</text>'+points.map(r=>`<circle cx="${40+r.density_gsi*430}" cy="${215-r.density_fsi/maxF*195}" r="2.5" fill="#087f72" opacity=".5"><title>Квартал ${r.block_id}: FSI ${fmt(r.density_fsi)}, GSI ${fmt(r.density_gsi)}</title></circle>`).join('');
const observations=[];const estimated=sum('school_capacity_estimated_places'),cap=sum('school_capacity');
if(cap>0)observations.push('Доля оценённых школьных мест: '+fmt(estimated/cap*100)+'%.');
observations.push('Модельный неудовлетворённый спрос: '+fmt(sum('provision_demand_left'))+' мест.');
let ranked=rows.filter(r=>Number.isFinite(r.density_fsi)).sort((a,b)=>b.density_fsi-a.density_fsi);if(ranked.length)observations.push('Максимальный FSI: квартал '+ranked[0].block_id+', '+fmt(ranked[0].density_fsi)+'.');
let accessible=rows.filter(r=>Number.isFinite(r.area_accessibility)).sort((a,b)=>a.area_accessibility-b.area_accessibility);if(accessible.length)observations.push('Минимальное среднее время с весами площадей: квартал '+accessible[0].block_id+', '+fmt(accessible[0].area_accessibility)+' мин.');
$('findings').innerHTML='<ul>'+observations.map(s=>'<li>'+esc(s)+'</li>').join('')+'</ul><p class="muted">Выводы относятся к выбранным исходным данным и допущениям модели.</p>';
$('method').innerHTML='<p><strong>Источник графа:</strong> '+esc(D.meta.graph_source)+'</p><p>Спрос на школы: '+esc(D.meta.normative_school_demand_per_1000)+' мест на 1000 жителей; доступность: '+esc(D.meta.normative_school_accessibility_min)+' минут. Норматив взят из конфигурации BlocksNet, не проверен как действующая местная норма.</p><p>Сильная обеспеченность учитывает удовлетворённый спрос в нормативном времени, слабая — также за его пределами. Глубина 1, как в примере: показатели могут совпадать. При нулевом спросе доля не определена.</p><p>Контрольная численность города: '+esc(fmt(D.meta.population_calibration.target_total))+' человек по сообщению пользователя (год статистики не указан). По кварталам она распределена пропорционально исходной оценке методом наибольших остатков, с точным сохранением общей суммы. Исходные веса: жилая площадь / 30 м² на человека; доля жилой площади 0.9, отсутствующая этажность — 1. Вместимость школ при отсутствии данных восстановлена по конфигурации BlocksNet. Spacematrix: 11 кластеров, random_state=42. Отсутствие объекта в OSM не означает его отсутствия в городе.</p><p>area_accessibility — среднее время до остальных кварталов с весами их площадей. Незастроенные кварталы могут не иметь определённых показателей плотности и морфотипов.</p><details><summary>Метаданные исследования</summary><pre style="white-space:pre-wrap">'+esc(JSON.stringify(D.meta,null,2))+'</pre></details>';
filter();update();
})().catch(error=>{
 const message=document.createElement('div');message.className='notice';
 message.textContent='Не удалось открыть данные отчёта. '+error.message;
 document.querySelector('main').prepend(message);console.error(error);
});
</script></body></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/kemerovo/results')
    parser.add_argument('--output', type=Path, default=ROOT / 'dashboard.html')
    args = parser.parse_args()
    build(args.source, args.output)
