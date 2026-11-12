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
import resource_limits as limits
import configuration_export
import native_references
import native_object_profiles

MAX_CF_BYTES = 256 * 1024 * 1024
MAX_IMAGE_BYTES = 512 * 1024 * 1024
FORMAT15_OFFSET_LIMIT = 2**31-1
CF_IO_CHUNK_BYTES = 1024*1024
FORMAT16_BASE_OFFSET = 0x1359


def format16_preamble(storage_version):
    """Generate the semantic Format15 envelope of a complete Format16 CF."""
    sentinel=0x7fffffff
    def block(payload,minimum=0):
        size=max(len(payload),minimum)
        return ('\r\n%08x %08x %08x \r\n'%(len(payload),size,sentinel)).encode()+payload+bytes(size-len(payload))
    descriptions=[];addresses=[];offset=16+31+512
    for name in ('root','version','versions'):
        description=block(bytes(20)+name.encode('utf-16-le')+bytes(4))
        addresses.append(struct.pack('<III',offset,sentinel,sentinel));descriptions.append(description);offset+=len(description)
    data=struct.pack('<IIII',sentinel,512,storage_version,0)+block(b''.join(addresses),512)+b''.join(descriptions)
    if len(data)>FORMAT16_BASE_OFFSET:raise ValueError('Oversized Format16 preamble')
    return data+bytes(FORMAT16_BASE_OFFSET-len(data))


class _OffsetWriter:
    """Keep primary-container offsets relative while writing after a preamble."""
    def __init__(self,stream,offset):self.stream,self.offset=stream,offset
    def write(self,data):return self.stream.write(data)
    def tell(self):return self.stream.tell()-self.offset
    def seek(self,position,whence=0):
        self.stream.seek(position+self.offset if whence==0 else position,whence)
        return self.tell()


def primary_container_offset(source):
    source.seek(0);header=source.read(20)
    if header[:4]==bytes.fromhex('ffffff7f'):
        source.seek(FORMAT16_BASE_OFFSET);wide=source.read(20)
        if len(wide)==20 and wide[:8]==bytes.fromhex('ffffffffffffffff'):
            preamble=cf_container.Container();preamble.allow_absent=True;preamble.read(source)
            if preamble.size>FORMAT16_BASE_OFFSET:raise ValueError('Overlapping Format16 preamble')
            for item in preamble.files.values():
                for _ in item.data:pass
            return FORMAT16_BASE_OFFSET
    return 0


class CompilationRejected(ValueError):
    """A valid compiler report rejected the requested conversion."""
    def __init__(self,message,codes=(),report=None):
        super().__init__(message);self.codes=frozenset(codes);self.report=report


class ExportMismatch(ValueError):
    """The compiler reported success but did not preserve the full target."""


def retain_unchanged_objects(before,candidate,source_records,target_records,objects,baseline_files,target_files):
    """Keep source native records for owners whose complete export is unchanged.

    A base-free build may normalize unrelated native objects. Select by the
    complete owned file set, never by application properties or native slots.
    The assembled image must still pass the mandatory whole-tree export check.
    """
    unchanged={oid for oid in source_records.keys() & target_records.keys()
               if source_records[oid]['path']==target_records[oid]['path']
               and set(source_records[oid]['files'])==set(target_records[oid]['files'])
               and all(xml_compare.file_equal(name,baseline_files[name],target_files[name]) for name in source_records[oid]['files'])}
    delta=compiled_image.Delta(before,candidate,source_records,target_records,objects)
    result=dict(candidate)
    for name,owner in delta.records.items():
        if owner not in unchanged:continue
        if name in before:result[name]=before[name]
        else:result.pop(name,None)
    return result


def read_cf(path):
    return read_container_image(path, {'root', 'version', 'versions'})


def read_fragment(path):
    """An explicit compiler fragment is not a complete configuration image."""
    return read_container_image(path, {'versions'})


def read_container_image(path, required):
    """Read the effective image, without mixing compatibility-container roots."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= limits.get('cf_bytes',MAX_CF_BYTES):
        raise ValueError('Missing or oversized ibcmd base/result CF')
    result = {}
    with path.open('rb') as source:
        offset = primary_container_offset(source)
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
                if total > limits.get('image_bytes',MAX_IMAGE_BYTES):
                    raise ValueError('Oversized decoded CF image')
                image[name] = raw
            if not container.size or not required <= set(image):
                raise ValueError('Incomplete CF configuration image')
            result = image
            offset += container.size
    return result


def write_cf(path, members):
    return write_container_image(path, members, {'root','version','versions'})


def write_fragment(path, members):
    return write_container_image(path, members, {'versions'})


def _deflate_to_file(output,raw):
    encoder=zlib.compressobj(wbits=-15)
    view=memoryview(raw)
    for start in range(0,len(view),CF_IO_CHUNK_BYTES):
        output.write(encoder.compress(view[start:start+CF_IO_CHUNK_BYTES]))
    output.write(encoder.flush())


def write_container_image(path, members, required):
    """Normalize effective records, using 64-bit offsets for large images."""
    if not required<=set(members):raise ValueError('Incomplete CF configuration image')
    if sum(map(len,members.values()))>limits.get('image_bytes',MAX_IMAGE_BYTES):raise ValueError('Oversized decoded CF image')
    with Path(path).open('w+b') as output:
        # Bound deflate expansion plus per-record descriptions, padding and TOC.
        # Choose before writing: Format15 stores signed 32-bit file offsets.
        upper_bound=1024+sum(len(raw)+len(raw)//100+2048+len(name.encode('utf-16-le')) for name,raw in members.items())
        wide=upper_bound>=FORMAT15_OFFSET_LIMIT
        writer = (cf_container.Container64 if wide else cf_container.Container)()
        if wide:output.write(format16_preamble(len(members)))
        writer.file = _OffsetWriter(output,FORMAT16_BASE_OFFSET) if wide else output
        writer.write_header(len(members))
        for name, raw in members.items():
            with tempfile.TemporaryFile() as item:
                _deflate_to_file(item,raw)
                item.seek(0)
                writer.add_file(item, name, False)
            output.seek(0,2)
            if output.tell()>limits.get('cf_bytes',MAX_CF_BYTES):raise ValueError('Oversized ibcmd result CF')
        writer.write_table_off_content()
    if Path(path).stat().st_size>limits.get('cf_bytes',MAX_CF_BYTES):raise ValueError('Oversized ibcmd result CF')
    # Compare one record at a time; a second complete decoded image can exhaust
    # memory during the first initialization of a large repository.
    with Path(path).open('rb') as source:
        offset=primary_container_offset(source)
        container=cf_container.detect_format(source,offset);container.read(source,offset)
        if set(container.files)!=set(members):raise ValueError('CF normalization changed member set')
        for name,item in container.files.items():
            if s.inflate(b''.join(item.data))!=members[name]:raise ValueError('CF normalization changed decoded contents')


def canonical(text):
    return xml_compare.document(text)


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
        if not xml_compare.file_equal(name,target_files[name],actual_files[name]):
            raise ExportMismatch('ibcmd output differs from target XML/file: '+name)


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
        timeout=os.environ.get('CRS_COMPILER_TIMEOUT_SECONDS','240')
        if not re.fullmatch(r'[0-9]{1,5}',timeout) or not 1<=int(timeout)<=86400:
            raise ValueError('CRS_COMPILER_TIMEOUT_SECONDS must be an integer from 1 to 86400')
        args=list(args)
        if '--platform' in args:
            position=args.index('--platform')+1
            # ibcmd explicitly supports release selectors. Its build catalog is
            # smaller than the set of repository server builds; retain the exact
            # version in CRS state/authentication and select only the XML release.
            version=str(args[position])
            if re.fullmatch(r'8\.(?:3\.27|5\.1)\.[0-9]+',version):args[position]='.'.join(version.split('.')[:3])
        try:
            result = subprocess.run([str(self.executable), *map(str, args)], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=int(timeout))
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
                                      [row.get('code') for row in report.get('errors',[]) if isinstance(row,dict)],report)
        return report

    def compile_tree(self,source,normalized,output,before,platform,verify=None,assemble=None):
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
            if assemble is not None:image=assemble(image)
            write_cf(output,image)
            self.route='bootstrap'
            if verify is not None:
                try:verify(output)
                except (CompilationRejected,ExportMismatch) as bootstrap_error:
                    raise CompilationRejected(str(overlay_error)+'; base-free verification: '+str(bootstrap_error)) from None

    def prepare(self, request, plan, changes, objects):
        for name in ('directory','baseline_directory'):
            if request.get(name):configuration_export.require_complete_directory(request[name])
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
                storage = external_data.extract(serialization_context.storage(request,'Oversized version storage'), oid)
                for stream in storage['externals']:
                    if before.get(stream['name']) != s.inflate(base64.b64decode(stream['data'], validate=True)):
                        raise ValueError('Stale or foreign ibcmd base CF stream: ' + stream['name'])
        # A form's owner need not itself have a changed XML file. Its current
        # definition is still required to prove the compiler's field bindings.
        storage = serialization_context.storage(request,'Oversized binding storage') if any(row['kind'].endswith('Form') for row in changes) else None
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
        def assemble(candidate):
            return retain_unchanged_objects(before,candidate,source_records,target,objects,baseline_files,target_files)
        self.compile_tree(source,normalized,output,before,request['platform'],verify,assemble)
        self.after = read_cf(output)
        self.delta=compiled_image.Delta(before,self.after,objects,target,objects)
        self.object_ids.update(self.delta.objects)

    def content(self, request, change, objects):
        oid = change['object_id']
        if oid not in self.object_ids:
            raise ValueError('ibcmd backend does not yet support implicit dependent-object changes: ' + oid)
        return compiled_metadata.content(request, change, objects, self.before, self.after)
