"""End-to-end browser checks in installed Edge, including actual CSV downloads."""
from pathlib import Path
import base64
import csv
import io
import json
import subprocess
import time
import uuid
import requests
import websocket

HERE=Path(__file__).resolve().parent
CACHE=HERE/'.test-cache'
CACHE.mkdir(exist_ok=True)
profile=CACHE/('edge-'+uuid.uuid4().hex)
downloads=CACHE/('downloads-'+uuid.uuid4().hex)
downloads.mkdir()
startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
proc=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-extensions',
    '--disable-background-networking','--remote-debugging-port=0','--window-size=1500,1100',
    '--user-data-dir='+str(profile),'http://127.0.0.1:8765/'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,startupinfo=startup)
ws=None;seq=0;exceptions=[]


def command(method,params=None):
    global seq
    seq+=1
    ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
    while True:
        msg=json.loads(ws.recv())
        if msg.get('method')=='Runtime.exceptionThrown':exceptions.append(msg['params']['exceptionDetails'])
        if msg.get('id')==seq:
            if 'error' in msg:raise RuntimeError(msg['error'])
            return msg.get('result',{})


def js(code):
    r=command('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
    if 'exceptionDetails' in r:raise RuntimeError(r['exceptionDetails'])
    return r['result'].get('value')


def until(code,seconds=30):
    end=time.monotonic()+seconds
    while not js(code):
        if time.monotonic()>end:raise TimeoutError(code)
        time.sleep(.25)


def download_check(button,filename,count):
    js(f"document.getElementById('{button}').click();true")
    file=downloads/filename
    end=time.monotonic()+20
    while not file.exists():
        if time.monotonic()>end:raise TimeoutError(filename)
        time.sleep(.2)
    with file.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f,delimiter=';'))
    assert len(rows)==count,(filename,len(rows),count)
    return rows


try:
    portfile=profile/'DevToolsActivePort';end=time.monotonic()+30
    while not portfile.exists():
        if time.monotonic()>end:raise TimeoutError('Edge startup')
        time.sleep(.2)
    port=int(portfile.read_text().splitlines()[0])
    page=next(p for p in requests.get(f'http://127.0.0.1:{port}/json/list',timeout=10).json() if p['type']=='page')
    ws=websocket.create_connection(page['webSocketDebuggerUrl'],timeout=60,suppress_origin=True)
    command('Runtime.enable');command('Page.enable')
    command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads)})
    until('!!window.schoolApp')
    checks={}
    checks['initial_rows']=js("document.querySelectorAll('#results tbody tr').length")
    assert checks['initial_rows']==2230
    assert js('schoolApp.layers.size')==2230
    assert js('schoolApp.state.active.deficit_after')==37268
    checks['initial_map_and_table_all_blocks']=True
    svg_height=js("document.querySelector('#map .leaflet-overlay-pane svg').getBoundingClientRect().height")
    assert svg_height>=js("document.getElementById('map').clientHeight")
    checks['leaflet_overlay_svg_has_correct_visible_dimensions']=True
    # Fire the same Leaflet click event handled when selecting a polygon.
    js("schoolApp.layers.get(1936).fire('click');document.getElementById('capacity').value='600';document.getElementById('add').click();true")
    assert js('schoolApp.state.selected')==1936
    assert js('schoolApp.layers.get(1936).options.weight')==3
    assert js('schoolApp.state.schools[0].capacity')==600
    js("document.getElementById('calculate').click();true")
    until('!schoolApp.state.busy')
    assert js('schoolApp.state.active.reduction')==600
    assert js('schoolApp.state.active.added_capacity')==600
    assert js("document.getElementById('view').value")=='after'
    assert js('schoolApp.state.active.rows.find(r=>r.block_id===1936).after_capacity')==600
    checks['map_click_capacity_and_calculation']=True
    js("document.getElementById('view').value='delta';document.getElementById('view').onchange();true")
    assert js('schoolApp.layers.get(1936).options.fillColor')=='#087f72'
    assert '2122' in js("document.getElementById('selected').textContent").replace('\u00a0','').replace('\u202f','')
    checks['map_delta_matches_selected_card_and_table']=True
    for bad in ['0','-2','1.5']:
        js(f"document.getElementById('capacity').value='{bad}';document.getElementById('add').click();true")
        assert js('schoolApp.state.schools.length')==1
        assert js("document.getElementById('message').classList.contains('error')")
    checks['invalid_capacities_rejected_in_ui']=True
    rows=download_check('export','school_scenario.csv',2230)
    assert sum(int(float(r['Дефицит после'])) for r in rows)==36668
    checks['actual_scenario_csv_download_correct']=True
    js("document.getElementById('reset').click();true")
    assert js('schoolApp.state.schools.length')==0
    assert js('schoolApp.state.active.deficit_after')==37268
    assert js("document.getElementById('view').value")=='before'
    checks['reset_returns_baseline']=True
    if js('!!schoolApp.state.data.experiment'):
        for key in ['a','b','c']:
            js(f"document.getElementById('preset-{key}').click();true")
            until('!schoolApp.state.busy')
            assert js('schoolApp.state.active.added_capacity')==600
        c=js('schoolApp.state.active')
        js("document.getElementById('calculate').click();true")
        until('!schoolApp.state.busy')
        assert js('schoolApp.state.active.rows')==c['rows']
        checks['manual_winner_recalculation_matches_automatic']=True
        js("document.getElementById('auto').click();true")
        until('!schoolApp.state.busy',60)
        assert js('schoolApp.state.search.checked')==2230
        assert js('schoolApp.state.search.complete')
        assert js("document.querySelectorAll('#search-table tbody tr').length")==2230
        download_check('export-search','school_search.csv',2230)
        checks['automatic_button_cached_full_search_and_csv']=True
        js("document.getElementById('row-filter').value='improved';document.getElementById('row-filter').onchange();true")
        assert js('schoolApp.state.displayedRows.every(r=>r.improvement>0)')
        assert js("document.querySelectorAll('#results tbody tr').length")==js('schoolApp.state.displayedRows.length')
        checks['filter_and_table_consistency']=True
    # Expand the original dashboard and check that it is available locally.
    assert requests.get('http://127.0.0.1:8765/reference.html',timeout=15).status_code==200
    checks['original_dashboard_available']=True
    js("document.getElementById('reset').click();window.scrollTo(0,0);true")
    screenshot=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
    (HERE/'results/preview.png').write_bytes(base64.b64decode(screenshot['data']))
    js("document.getElementById('map').scrollIntoView({block:'center'});true")
    screenshot=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
    (HERE/'results/map_preview.png').write_bytes(base64.b64decode(screenshot['data']))
    # Responsive layout should not overflow the viewport.
    command('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
    js('schoolApp.map.invalidateSize();true')
    assert js('document.documentElement.scrollWidth<=window.innerWidth+1')
    checks['mobile_no_horizontal_overflow']=True
    # Exercise the new-search UI path as well, then explicitly disconnect.
    # This partial run is a test only and is never reported as full enumeration.
    js("document.getElementById('auto-capacity').value='602';document.getElementById('force').checked=true;document.getElementById('auto').click();true")
    until("document.getElementById('progress').value>=2",30)
    assert '2230' in js("document.getElementById('progress-text').textContent")
    assert js('schoolApp.state.busy')
    checks['new_search_ui_displays_live_calculation_progress']=True
    checks['javascript_exceptions']=exceptions
    assert not exceptions
    (HERE/'results/browser_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=True,indent=2),flush=True)
finally:
    if ws:
        try:command('Browser.close')
        except Exception:pass
        ws.close()
    try:proc.wait(timeout=10)
    except subprocess.TimeoutExpired:proc.terminate()
