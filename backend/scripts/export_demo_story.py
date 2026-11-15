"""Export the public scripted previews from the same authored demo corpus. No API calls."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.demo_seed import MEETINGS, build_demo_turns


def story():
    spec=next(item for item in MEETINGS if item.get('featured'))
    who=lambda key: ({'me':'Archit Gupta','mate':'Vedant Moghe'}.get(key,key),None)
    turns,tasks,decisions,_,_=build_demo_turns(spec,who)
    duration=spec['minutes']*60000
    segments=[{'id':f'sample-{i}','start_ms':round(i*duration/len(turns)),
               'end_ms':round((i+.83)*duration/len(turns)),'text':text} for i,(_,text) in enumerate(turns)]
    moments=[]
    for kind,index,title,owner in [('task',tasks[0],spec['tasks'][0][1],'Archit'),
                                  ('decision',decisions[0],spec['decisions'][0][0],'Team'),
                                  ('task',tasks[1],spec['tasks'][1][1],'Vedant')]:
        text=turns[index][1].split(' Due:')[0]
        moments.append({'id':f'moment-{index}','at_ms':segments[index]['start_ms'],'kind':kind,'label':title,
                        'segmentId':segments[index]['id'],'line':text,'owner':owner})
    answers=[]
    for keyword,question,answer in [
        ('Architecture council: the billing ledger','Why PostgreSQL?','The team chose PostgreSQL for atomic ledger writes, unique constraints and reliable invoice reconciliation.'),
        ('Release go/no-go: tenant workspaces',"What’s blocking the release?",'Safari smoke tests, certificate rollback and QA sign-off are the remaining gates for the five-tenant pilot.'),
        ('Architecture follow-up: defer the search cache','Why defer Redis?','The metadata index met the target in a synthetic benchmark, so the team deferred Redis and its invalidation complexity.')]:
        source=next(item for item in MEETINGS if item['title']==keyword)
        answers.append({'question':question,'answer':answer,'source':source['title'],'ago':source['ago'],'at_ms':0})
    return {'meeting':spec['title'],'duration_ms':duration,'segments':segments,'moments':moments,
            'answers':answers,'language_decision':'Use PostgreSQL','language_reason':'Atomic writes and reliable invoice reconciliation.'}


if __name__=='__main__':
    target=Path(__file__).resolve().parents[2]/'frontend/src/lib/demo-story.json'
    target.write_text(json.dumps(story(),ensure_ascii=False,indent=2)+'\n')
    print('Exported authored software-team previews; no provider or account calls.')
