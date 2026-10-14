"""Verified owner identities and native templates shared by form converters."""
import json
from pathlib import Path
import metadata_serializer as s

KINDS=('Catalog','Document','CommonForm','DataProcessor','Report')


def layout(kind):
    names={'Catalog':'catalog','Document':'document','CommonForm':'common','DataProcessor':'dataprocessor','Report':'report'}
    if kind not in names:raise ValueError('Unsupported managed form kind')
    return json.loads(Path(__file__).with_name(names[kind]+'_form_layout_851.json').read_text(encoding='utf-8'))


def owner_name(owner,kind):
    if kind=='CommonForm':return ''
    if kind in ('Catalog','Document'):return s.val(owner[1][9][1][2])
    if kind in ('DataProcessor','Report'):return s.val(owner[1][3][1][2])
    raise ValueError('Unsupported form owner kind')


def common(body,kind):
    node=body
    for slot in layout(kind).get('common_path',[1,1,1]):node=node[slot]
    return node


def replace_common(body,kind,value):
    path=layout(kind).get('common_path',[1,1,1]);node=body
    for slot in path[:-1]:node=node[slot]
    node[path[-1]]=value


def defaults(kind):
    if kind=='Document':return {'AutoTime':'CurrentOrLast','UsePostingMode':'Auto','RepostOnWrite':'true'}
    if kind=='Report':return {'ReportFormType':'Main','AutoShowState':'Auto','ReportResultViewMode':'Auto','ViewModeApplicationOnSetReportResult':'Auto'}
    return {}
