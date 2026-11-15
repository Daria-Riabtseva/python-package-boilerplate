"""Run the entire experiment, sequentially, with durable progress and real results."""
import sys
import time
from datetime import datetime, timezone
import pandas as pd
from model import Model, HERE, RESULTS, save


def run():
    sys.stdout.reconfigure(encoding='utf-8')
    model=Model()
    # Freeze manual decisions before any automatic search is executed.
    choice={'chosen_utc':datetime.now(timezone.utc).isoformat(), 'source_hashes':model.hashes,
        'A':[{'block_id':1936,'capacity':600}],
        'B':[{'block_id':1936,'capacity':300},{'block_id':1295,'capacity':300}],
        'rationale_A':'Квартал 1936 имеет наибольший исходный остаточный дефицит: 2122 места при населении 17681. Приоритет — крупный необеспеченный жилой очаг.',
        'rationale_B':'По 300 мест в кварталах 1936 и 1295: два крупных очага остаточного дефицита (2122 и 2047 мест), в каждом дефицит выше новой вместимости. Это распределение ресурсов между двумя кварталами; земельные участки не выбираются.',
        'selection_basis':'Только исходные показатели практики 2, без использования результатов перебора.'}
    if (HERE/'manual_choices.json').exists():
        import json
        choice=json.loads((HERE/'manual_choices.json').read_text(encoding='utf-8'))
        assert choice['source_hashes']==model.hashes
    else: save(HERE/'manual_choices.json',choice)
    print('Исходный расчёт полностью совпал с практикой 2. Дефицит:',model.deficit,flush=True)
    scenarios={'baseline':model.package(model.baseline,[],'Исходное состояние')}
    for key in ['A','B']:
        scenarios[key]=model.scenario(choice[key],key)
        print(key,scenarios[key]['reduction'],flush=True)
        save(RESULTS/f'scenario_{key}.json',scenarios[key])
        pd.DataFrame(scenarios[key]['rows']).to_csv(RESULTS/f'scenario_{key}.csv',index=False,encoding='utf-8-sig')
    last=time.monotonic()
    def progress(k,n,row):
        nonlocal last
        save(RESULTS/'progress.json',{'checked':k,'total':n,'last':row})
        if k%25==0 or k==1:
            print(f'Проверено {k}/{n}; последний квартал {row["block_id"]}; сокращение {row.get("reduction")}',flush=True)
    search=model.search(600,progress)
    save(RESULTS/'search_600.json',search)
    pd.DataFrame(search['scores']).to_csv(RESULTS/'search_600.csv',index=False,encoding='utf-8-sig')
    assert search['complete'] and search['checked']==len(model.ids)
    scenarios['C']=model.scenario([{'block_id':search['best_ids'][0],'capacity':600}],'В')
    assert scenarios['C']['reduction']==search['scores'][0]['reduction']
    save(RESULTS/'scenario_C.json',scenarios['C'])
    pd.DataFrame(scenarios['C']['rows']).to_csv(RESULTS/'scenario_C.csv',index=False,encoding='utf-8-sig')
    save(RESULTS/'experiment.json',{'completed_utc':datetime.now(timezone.utc).isoformat(),'source_hashes':model.hashes,'manual_choices':choice,'search':search,'scenarios':scenarios})
    print('Полный перебор и три сценария завершены.',flush=True)


if __name__=='__main__':run()
