"""Common JSON file entry point for standalone serializers."""
import json,sys,zlib
from pathlib import Path
from xml.etree import ElementTree as E


def run(handler):
    try:result={"ok":True,**handler(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig')))}
    except (ValueError,KeyError,IndexError,TypeError,OSError,E.ParseError,zlib.error) as error:result=dict(ok=False,error=str(error))
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
