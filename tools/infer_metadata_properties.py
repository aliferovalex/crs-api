"""Infer candidate scalar slots from independent native property variants.

The output is a proposal, never an automatically activated runtime profile.
Identity fields are masked; prerequisite variants are explicit baselines.
"""
import argparse
import copy
import json
import re
from pathlib import Path
import sys
from xml.etree import ElementTree as E

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(next(p for p in (ROOT/'src').iterdir() if (p/'metadata_object_xml.py').exists())))
import metadata_object_xml as objects
import native_metadata as s


def normalized(case,kind,layout):
    top=E.fromstring(case['xml'])
    if len(top)!=1 or top[0].tag!=objects.Q+objects.profiles.xml_kind(kind):raise ValueError('Wrong property witness class')
    body=s.Parser(case['body']).documents()
    if len(body)!=1:raise ValueError('Expected one native property document')
    body=copy.deepcopy(body[0]);common=objects.at(body,objects.common_path(layout))
    if s.val(common[1][2])!=top[0].get('uuid') or s.val(common[2])!=top[0].findtext(objects.Q+'Properties/'+objects.Q+'Name'):raise ValueError('Property witness identity mismatch')
    common[1][2]=s.atom(s.ZERO);common[2]=s.atom('',True)
    for slot in layout['generated_slots']:body[1][slot]=s.atom(s.ZERO)
    return body


def differences(before,after,path=()):
    if isinstance(before,list) and isinstance(after,list) and len(before)==len(after):
        return [item for index,(old,new) in enumerate(zip(before,after)) for item in differences(old,new,path+(index,))]
    if s.render(before)==s.render(after):return []
    return [dict(path=list(path),before=s.render(before),after=s.render(after),leaf=isinstance(before,s.Atom) and isinstance(after,s.Atom))]


def infer(samples,kind,platform='8.5.1.1529'):
    labels={row['label']:row for row in samples}
    if len(labels)!=len(samples):raise ValueError('Duplicate property witness label')
    layout=objects.profiles.layout(kind,platform);normalized_bodies={key:normalized(row,kind,layout) for key,row in labels.items()};rules={};unresolved=[];evidence=[]
    for row in samples:
        if row.get('baseline') is None:continue
        if row['baseline'] not in labels or len(row.get('overrides',{}))!=1:raise ValueError('Property variants require one property and an existing baseline')
        baseline=labels[row['baseline']];key,value=next(iter(row['overrides'].items()))
        before=E.fromstring(baseline['xml'])[0].find(objects.Q+'Properties/'+objects.Q+key);after=E.fromstring(row['xml'])[0].find(objects.Q+'Properties/'+objects.Q+key)
        if before is None or after is None or len(before) or len(after) or before.attrib or after.attrib:raise ValueError('Expected scalar XML property witness')
        if (after.text or '')!=value:raise ValueError('Native export normalized the requested property value')
        delta=differences(normalized_bodies[row['baseline']],normalized_bodies[row['label']])
        if len(delta)!=1 or not delta[0]['leaf']:
            unresolved.append(dict(property=key,label=row['label'],delta=delta));continue
        path=delta[0]['path'];old=objects.at(normalized_bodies[row['baseline']],path);new=objects.at(normalized_bodies[row['label']],path)
        if old.quoted!=new.quoted:raise ValueError('Native scalar representation changed')
        if not old.quoted and any(not re.fullmatch(r'-?(0|[1-9][0-9]*)',s.val(atom)) for atom in (old,new)):
            unresolved.append(dict(property=key,label=row['label'],reason='non_integer_or_reference',delta=delta));continue
        candidate=dict(path=path,values={},quoted=old.quoted)
        rule=rules.setdefault(key,candidate)
        if rule['path']!=path or rule['quoted']!=old.quoted:raise ValueError('Conflicting native property paths: '+key)
        for label,atom in ((before.text or '',old),(after.text or '',new)):
            native=s.val(atom) if atom.quoted else int(s.val(atom))
            if label in rule['values'] and rule['values'][label]!=native:raise ValueError('Conflicting native property value: '+key)
            rule['values'][label]=native
        evidence.append(dict(property=key,baseline=row['baseline'],variant=row['label']))
    paths={}
    for key,rule in rules.items():paths.setdefault(tuple(rule['path']),[]).append(key)
    for path,keys in paths.items():
        if len(keys)>1:
            unresolved.append(dict(properties=keys,path=list(path),reason='shared_native_scalar'))
            for key in keys:rules.pop(key)
    for key,rule in list(rules.items()):
        if len(set(rule['values'].values()))!=len(rule['values']):
            unresolved.append(dict(property=key,reason='ambiguous_native_values'));rules.pop(key)
    return dict(kind=kind,platform=platform,scalar_properties=rules,unresolved=unresolved,evidence=evidence)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('input',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--kind',required=True);parser.add_argument('--platform',default='8.5.1.1529');args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8-sig'));result=infer(data['samples'] if isinstance(data,dict) else data,args.kind,args.platform)
    args.output.write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').replace('\n','\r\n').encode('utf-8'));print('Candidate scalar properties:',len(result['scalar_properties']),'unresolved:',len(result['unresolved']))


if __name__=='__main__':main()
