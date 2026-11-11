"""Read-only compiler contract probe for a platform-validated CF/XML pair."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from xml.etree.ElementTree import ParseError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'Сериализация'))
import compiled_graph
import configuration_export as export
import ibcmd_backend as backend


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def phase(action):
    try:
        action()
        return dict(ok=True)
    except (ValueError,OSError,UnicodeError,ParseError) as error:
        kind=('compiler_rejected' if isinstance(error,backend.CompilationRejected) else
              'export_mismatch' if isinstance(error,backend.ExportMismatch) else 'validation_error')
        return dict(ok=False,kind=kind,error=str(error),codes=sorted(getattr(error,'codes',())))


def check(executable,native_cf,directory,platform):
    executable=Path(executable).resolve();native_cf=Path(native_cf).resolve();directory=Path(directory).resolve()
    _,files,records,root=export.inventory(directory)
    before=backend.read_cf(native_cf)
    if root['id'].encode() not in before['root']:raise ValueError('Native CF and XML have different root identities')
    inputs=dict(compiler_sha256=digest(executable),native_cf_sha256=digest(native_cf),
                xml_fingerprint=export.fingerprint(files))
    report=dict(schema=1,platform=platform,inputs=inputs,objects=len(records),files=len(files),phases={})
    def source_contract():
        index=compiled_graph.TypeIndex(records,before,platform)
        for oid in records:index.facts(oid)
        backend.require_complete_export(before,records,files)
    report['phases']['source_contract']=phase(source_contract)
    request=dict(compiler=dict(backend='ibcmd',executable=str(executable),base_cf=str(native_cf)))
    with backend.Compiler(request) as compiler:
        normalized=compiler.work/'native.cf';backend.write_cf(normalized,before)
        def native_export():
            target=compiler.work/'native-export'
            compiler.execute('cf','export',normalized,target,'--platform',platform)
            backend.verify_export(files,target,before)
        report['phases']['native_export']=phase(native_export)
        def bootstrap():
            # Stage only inventoried files: Git data and the CRS cache are
            # excluded by the same inventory rules as normal preparation.
            source=compiler.work/'source';source.mkdir()
            for name,raw in files.items():
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            output=compiler.work/'compiled.cf'
            compiler.execute('cf','bootstrap',source,output,'--platform',platform,'--base-free')
            image=backend.read_cf(output)
            if image['root']!=before['root']:raise ValueError('Compiler changed CF root identity')
            target=compiler.work/'compiled-export'
            compiler.execute('cf','export',output,target,'--platform',platform)
            backend.verify_export(files,target,image)
        # Export failure must not hide an independent compilation failure.
        report['phases']['bootstrap']=phase(bootstrap)
    current=export.inventory(directory)[1]
    report['inputs_unchanged']=inputs==dict(compiler_sha256=digest(executable),native_cf_sha256=digest(native_cf),
                                          xml_fingerprint=export.fingerprint(current))
    report['ok']=report['inputs_unchanged'] and all(row['ok'] for row in report['phases'].values())
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--native-cf',required=True,type=Path)
    parser.add_argument('--xml',required=True,type=Path)
    parser.add_argument('--platform',required=True)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        output=args.report.resolve();source=args.xml.resolve()
        if output.is_relative_to(source) or output in (args.native_cf.resolve(),args.executable.resolve()):
            raise ValueError('Report must be outside input XML and must not overwrite CF or compiler')
        report=check(args.executable,args.native_cf,args.xml,args.platform)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (ValueError,OSError,UnicodeError,ParseError) as error:
        print(json.dumps(dict(ok=False,kind='input_error',error=str(error)),ensure_ascii=True))
        return 2
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['ok'] else 1


if __name__=='__main__':sys.exit(main())
