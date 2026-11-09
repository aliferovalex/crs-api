"""Required ibcmd-rs compilation with independent repository metadata checks.

Repository identities, dependencies and versions remain owned by CRS. The
compiler supplies only verified bodies/streams before the single final pack.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import struct
import tempfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as E

import compiled_image
import external_data
import xml_compare
import native_metadata as s
import export_xml
import serialization_context
import cf_container
import compiled_metadata
import configuration_export
import native_references
import native_object_profiles

MAX_CF_BYTES = 256 * 1024 * 1024
MAX_IMAGE_BYTES = 512 * 1024 * 1024


class CompilationRejected(ValueError):
    """A valid compiler report rejected the requested conversion."""
    def __init__(self,message,codes=()):
        super().__init__(message);self.codes=frozenset(codes)


class ExportMismatch(ValueError):
    """The compiler reported success but did not preserve the full target."""


def read_cf(path):
    """Read the effective image, without mixing compatibility-container roots."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_CF_BYTES:
        raise ValueError('Missing or oversized ibcmd base/result CF')
    result = {}
    with path.open('rb') as source:
        offset = 0
        for _ in range(2):
            if offset >= path.stat().st_size:
                break
            source.seek(offset)
            header = source.read(20)
            if header[:4] != bytes.fromhex('ffffff7f'):
                # Format16 starts with a free-block *offset*, not a fixed magic.
                valid = len(header) == 20
                if valid:
                    _, block, count, reserved = struct.unpack('<Qiii', header)
                    valid = 0 < block <= 65536 and block & (block - 1) == 0 and count >= 0 and reserved == 0
                if not valid:
                    if result:
                        break
                    raise ValueError('Unsupported CF container header')
            container = cf_container.detect_format(source, offset)
            try:
                container.read(source, offset)
            except (BufferError, EOFError, OverflowError) as error:
                raise ValueError('Invalid CF container: ' + str(error)) from None
            image = {}
            total = 0
            for name, item in container.files.items():
                packed = b''.join(item.data)
                try:
                    raw = s.inflate(packed)
                except (ValueError, zlib.error):
                    if name not in ('root', 'version', 'versions'):
                        raise ValueError('Invalid compressed CF member: ' + name) from None
                    raw = packed
                total += len(raw)
                if total > MAX_IMAGE_BYTES:
                    raise ValueError('Oversized decoded CF image')
                image[name] = raw
            if not container.size or not {'root', 'version', 'versions'} <= set(image):
                raise ValueError('Incomplete CF configuration image')
            result = image
            offset += container.size
    return result


def write_cf(path, members):
    """Normalize effective records to a single, fully deflated Format15 image."""
    with Path(path).open('w+b') as output:
        writer = cf_container.Container()
        writer.file = output
        writer.write_header(len(members))
        for name, raw in members.items():
            with tempfile.TemporaryFile() as item:
                item.write(s.compress(raw))
                item.seek(0)
                writer.add_file(item, name, False)
        writer.write_table_off_content()
    if read_cf(path) != members:
        raise ValueError('CF normalization changed decoded contents')


def canonical(text):
    if '<!DOCTYPE' in text.upper():
        raise ValueError('DOCTYPE is unsupported in compiler XML')
    return xml_compare.canonical(E.fromstring(text))


def align_xml(text, template):
    """Keep complete target XML; align only the writer's root namespace header."""
    pattern = r'<(?![!?/])[^>]+>'
    source = re.search(pattern, text)
    target = re.search(pattern, template)
    if source is None or target is None:
        raise ValueError('Missing compiler XML root')
    header = target.group()
    # QName values need the same prefix bindings even when ET does not expand
    # them (e.g. cfg:CatalogRef in Type). Never discard a used declaration.
    declaration = r'''xmlns:([\w-]+)\s*=\s*(["'])(.*?)\2'''
    bindings = {prefix: uri for prefix, _, uri in re.findall(declaration, source.group())}
    expected = {prefix: uri for prefix, _, uri in re.findall(declaration, header)}
    content = text[source.end():]
    for prefix, uri in bindings.items():
        if re.search(r'\b' + re.escape(prefix) + ':', content) and expected.get(prefix) != uri:
            raise ValueError('Compiler XML requires a different namespace: ' + prefix)
    aligned = text[:source.start()] + header + text[source.end():]
    if canonical(aligned) != canonical(text):
        raise ValueError('Compiler XML header alignment changed the document')
    return aligned


def require_complete_export(image, records, files):
    import export_coverage
    try:
        export_coverage.require_complete_export(image,records,files)
    except (ValueError,IndexError,UnicodeError) as exc:
        raise ExportMismatch(str(exc)) from exc


def verify_export(target_files,exported,image=None):
    """A whole target tree cannot gain or lose an unrequested companion."""
    _,actual_files,records,_=configuration_export.inventory(exported)
    if image is not None:require_complete_export(image,records,actual_files)
    expected_names=set(target_files)-{'ConfigDumpInfo.xml'}
    actual_names=set(actual_files)-{'ConfigDumpInfo.xml'}
    if actual_names!=expected_names:
        raise ExportMismatch('ibcmd output file set differs from complete target export: '+str(sorted(actual_names^expected_names)[:20]))
    for name in sorted(expected_names):
        expected=target_files[name];actual=actual_files[name];suffix=Path(name).suffix.lower()
        if suffix in ('.xml','.bsl','.txt'):
            expected=expected.decode('utf-8-sig').replace('\r\n','\n')
            actual=actual.decode('utf-8-sig').replace('\r\n','\n')
            equal=canonical(expected)==canonical(actual) if suffix=='.xml' else expected==actual
        else:equal=expected==actual
        if not equal:raise ExportMismatch('ibcmd output differs from target XML/file: '+name)


class Compiler:
    def __init__(self, request):
        options = request.get('compiler')
        if not isinstance(options, dict) or set(options) != {'backend', 'executable', 'base_cf'} or options['backend'] != 'ibcmd':
            raise ValueError('Compiler requires backend=ibcmd, executable and base_cf')
        self.executable = Path(options['executable']).resolve()
        self.base = Path(options['base_cf']).resolve()
        if not self.executable.is_file() or not self.base.is_file():
            raise ValueError('Missing ibcmd executable or base CF')
        self.temp = None

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='crs-ibcmd-')
        self.work = Path(self.temp.name)
        return self

    def __exit__(self, *_):
        self.temp.cleanup()

    def execute(self, *args):
        if 'IBCMD_RS_LOAD_NO_VERIFY' in os.environ:
            raise ValueError('Unverified ibcmd diagnostic mode is forbidden for repository preparation')
        try:
            result = subprocess.run([str(self.executable), *map(str, args)], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=240)
        except subprocess.TimeoutExpired:
            raise ValueError('ibcmd compilation timed out') from None
        try:
            payload = result.stdout or (result.stderr if result.returncode else b'')
            report = json.loads(payload.decode('utf-8-sig'))
        except (UnicodeError, ValueError):
            raise ValueError('ibcmd returned an invalid JSON report') from None
        if not isinstance(report, dict):
            raise ValueError('ibcmd returned an invalid JSON report')
        if result.returncode or report.get('ok') is not True:
            messages = '; '.join(str(row.get('message', row)) for row in report.get('errors', []))
            raise CompilationRejected('ibcmd failed: ' + messages[:2000],
                                      [row.get('code') for row in report.get('errors',[]) if isinstance(row,dict)])
        return report

    def compile_tree(self,source,normalized,output,before,platform,verify=None):
        """Both routes use ibcmd; neither writes application properties here."""
        self.route='overlay'
        try:
            self.execute('cf','load',source,output,'--base',normalized,'--platform',platform)
            if verify is not None:verify(output)
        except (CompilationRejected,ExportMismatch) as overlay_error:
            if isinstance(overlay_error,CompilationRejected) and 'no_changes' in overlay_error.codes:raise
            clean=self.work/'bootstrap-source'
            shutil.copytree(source,clean,ignore=shutil.ignore_patterns('.ibcmd'))
            candidate=self.work/'bootstrap.cf'
            try:
                self.execute('cf','bootstrap',clean,candidate,'--platform',platform,'--base-free')
            except CompilationRejected as bootstrap_error:
                raise CompilationRejected(str(overlay_error)+'; base-free compilation: '+str(bootstrap_error)) from None
            image=read_cf(candidate)
            if image['root']!=before['root']:raise ValueError('Base-free compiler changed CF root identity')
            # Container service headers belong to the bound source CF. The
            # native contents below still pass the whole-tree reverse check,
            # delta ownership and repository identity/dependency validation.
            image['version']=before['version']
            write_cf(output,image)
            self.route='bootstrap'
            if verify is not None:
                try:verify(output)
                except (CompilationRejected,ExportMismatch) as bootstrap_error:
                    raise CompilationRejected(str(overlay_error)+'; base-free verification: '+str(bootstrap_error)) from None

    def prepare(self, request, plan, changes, objects):
        self.object_ids = {row['object_id'] for row in changes}
        before = read_cf(self.base)
        self.before = before
        # A CF has no repository versions: bind its actual data to current
        # snapshots and external storage rather than trusting its file name.
        for oid in plan['snapshot_ids']:
            frame = serialization_context.read(dict(request, snapshot=request['snapshots'][oid]), oid)
            if before.get(oid) != s.inflate(frame.data):
                raise ValueError('Stale or foreign ibcmd base CF object: ' + oid)
            if s.val(objects[oid][0][11][0]) != '0':
                storage = external_data.extract(serialization_context.decode(request['storage'], 'Oversized version storage'), oid)
                for stream in storage['externals']:
                    if before.get(stream['name']) != s.inflate(base64.b64decode(stream['data'], validate=True)):
                        raise ValueError('Stale or foreign ibcmd base CF stream: ' + stream['name'])
        # A form's owner need not itself have a changed XML file. Its current
        # definition is still required to prove the compiler's field bindings.
        storage = serialization_context.decode(request['storage'], 'Oversized binding storage') if any(row['kind'].endswith('Form') for row in changes) else None
        if storage is not None:
            reader = native_references.Catalog(request)
            for row in changes:
                if not row['kind'].endswith('Form'):continue
                parent = row['_record']['parent_id'] if row.get('_new') else s.val(objects[row['object_id']][0][3])
                if parent not in objects:continue
                identity = next(value for value in reader.targets.targets if value.object_id == parent)
                if before.get(parent) != reader.load(identity, storage, label='Form owner').body:
                    raise ValueError('Stale or foreign ibcmd form owner CF')
        root = next(oid for oid, docs in objects.items() if s.val(docs[0][3]) == s.ZERO)
        if root.encode() not in before['root']:
            raise ValueError('CF root differs from repository configuration')
        _,target_files,target,_=configuration_export.inventory(request['directory'])
        _,baseline_files,source_records,_=configuration_export.inventory(request['baseline_directory'])
        require_complete_export(before,source_records,baseline_files)
        if not plan['new_ids'] and not plan['removed_ids'] and not any(op.get('changed_files') for op in plan['operations']):
            # Position-only changes still require a verified source, but there
            # is no XML change for cf load to compile.
            self.after=dict(before)
            self.delta=compiled_image.Delta(before,self.after,objects,target,objects)
            return
        normalized = self.work / 'base.cf'
        write_cf(normalized, before)
        source = self.work / 'source'
        self.execute('cf', 'export', normalized, source, '--platform', request['platform'], '--index')
        require_complete_export(before,source_records,{path.relative_to(source).as_posix():path.read_bytes() for path in source.rglob('*')
            if path.is_file() and '.ibcmd' not in path.relative_to(source).parts})
        changed_files={Path(name) for name in baseline_files.keys()|target_files.keys() if name!='ConfigDumpInfo.xml'}
        for relative in sorted(changed_files):
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid compiler source path')
            actual=Path(request['directory'])/relative;staged=source/relative
            if not actual.is_file():
                staged.unlink(missing_ok=True);continue
            raw=actual.read_bytes()
            if relative.suffix.lower() in ('.xml','.bsl','.txt'):
                text=export_xml.read(actual)
                if relative.suffix.lower()=='.xml' and staged.is_file():text=align_xml(text,export_xml.read(staged))
                raw=text.replace('\r\n','\n').replace('\n','\r\n').encode('utf-8')
                if not staged.is_file() or staged.read_bytes().startswith(b'\xef\xbb\xbf'):raw=b'\xef\xbb\xbf'+raw
            staged.parent.mkdir(parents=True,exist_ok=True);staged.write_bytes(raw)
        output = self.work / 'target.cf'
        def verify(path):
            exported=self.work/('exported-'+self.route)
            self.execute('cf','export',path,exported,'--platform',request['platform'])
            verify_export(target_files,exported,read_cf(path))
        self.compile_tree(source,normalized,output,before,request['platform'],verify)
        self.after = read_cf(output)
        self.delta=compiled_image.Delta(before,self.after,objects,target,objects)
        self.object_ids.update(self.delta.objects)

    def content(self, request, change, objects):
        oid = change['object_id']
        if oid not in self.object_ids:
            raise ValueError('ibcmd backend does not yet support implicit dependent-object changes: ' + oid)
        return compiled_metadata.content(request, change, objects, self.before, self.after)
