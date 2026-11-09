"""Versioned repository XML and three-way Git merges, without editing inputs."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from functools import lru_cache
from xml.etree import ElementTree as E

import configuration_export as export
import ibcmd_backend
import repository_cache
import compiled_graph
from export_snapshot import version_map,expected_versions,write_files

DEFAULT_SOURCE_BRANCH='codex/crs-repository'


def source_reference(branch=DEFAULT_SOURCE_BRANCH):
    """Normalize and validate a branch before touching the XML repository."""
    if not isinstance(branch,str):raise ValueError('Invalid source_branch')
    if branch.startswith('refs/') and not branch.startswith('refs/heads/'):
        raise ValueError('source_branch must name a local Git branch')
    branch=branch.removeprefix('refs/heads/')
    if branch.startswith('refs/'):
        raise ValueError('Invalid source_branch: ambiguous nested ref')
    if not branch or branch.startswith('-'):raise ValueError('Invalid source_branch')
    reserved='codex/crs-work'
    if branch==reserved or branch.startswith(reserved+'/') or reserved.startswith(branch+'/'):
        raise ValueError('source_branch conflicts with internal work branches')
    reference='refs/heads/'+branch
    return _checked_reference(reference)


@lru_cache(maxsize=64)
def _checked_reference(reference):
    result=subprocess.run(['git','check-ref-format',reference],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if result.returncode:raise ValueError('Invalid source_branch: '+reference)
    return reference








def retain_unchanged(before,after):
    """Preserve unchanged exported bytes, including generated form helper IDs."""
    _,old_files,old,_=export.inventory(before);_,files,new,_=export.inventory(after)
    a,b=version_map(old_files),version_map(files)
    for oid,row in new.items():
        prior=old.get(oid)
        if prior is None or prior['path']!=row['path']:continue
        old_owners={oid,*compiled_graph.features(prior)}
        new_owners={oid,*compiled_graph.features(row)}
        old_streams={key:value for key,value in a.items() if '.' in key and key.partition('.')[0] in old_owners}
        new_streams={key:value for key,value in b.items() if '.' in key and key.partition('.')[0] in new_owners}
        same_body=a.get(oid)==b.get(oid)
        if same_body and old_streams==new_streams:
            for name in row['files']:files.pop(name,None)
            files.update({name:old_files[name] for name in prior['files']})
        else:
            if same_body:files[row['path']]=old_files[prior['path']]
            if row['kind'] in ('Form','CommonForm','Template','CommonTemplate','CommonModule') and old_streams==new_streams:
                for name in row['files']:
                    if name!=row['path']:files.pop(name,None)
                files.update({name:old_files[name] for name in prior['files'] if name!=prior['path']})
    return files


class Git:
    def __init__(self,directory,source_branch=DEFAULT_SOURCE_BRANCH):
        self.source_ref=source_reference(source_branch)
        self.source_branch=self.source_ref.removeprefix('refs/heads/')
        self.directory=Path(directory).resolve()

    def execute(self,*args,input=None,allowed=(0,),index=None):
        env=dict(os.environ)
        for name in ('GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE'):env.pop(name,None)
        env.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull,GIT_AUTHOR_NAME='CRS API',
                   GIT_AUTHOR_EMAIL='crs-api@localhost',GIT_COMMITTER_NAME='CRS API',GIT_COMMITTER_EMAIL='crs-api@localhost')
        if index is not None:env['GIT_INDEX_FILE']=str(index)
        command=['git','--git-dir='+str(self.directory),'-c','core.autocrlf=false','-c','core.quotePath=false',
                 '-c','core.longpaths=true','-c','commit.gpgSign=false',*map(str,args)]
        result=subprocess.run(command,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=240)
        if result.returncode not in allowed:raise ValueError('Git XML operation failed: '+result.stderr.decode('utf-8',errors='replace')[:1600])
        return result

    def initialize(self):
        if not self.directory.exists():
            self.directory.mkdir(parents=True)
            self.execute('init','--bare','--object-format=sha1')
            self.execute('symbolic-ref','HEAD',self.source_ref)
        elif self.execute('rev-parse','--is-bare-repository').stdout.strip()!=b'true':
            raise ValueError('xml_repository must be a dedicated bare Git repository')

    def head(self):
        result=self.execute('rev-parse','--verify',self.source_ref,allowed=(0,128))
        return result.stdout.decode().strip() if result.returncode==0 else None

    def history(self,state):
        head=self.head();versions={}
        if head:
            records=self.execute('log','--first-parent','--format=%H%x00%B%x00',self.source_ref).stdout.split(b'\0')
            for i in range(0,len(records)-1,2):
                commit=records[i].decode().strip();message=records[i+1].decode('utf-8')
                match=re.fullmatch(r'CRS repository version ([0-9a-f-]{36})\n\nCRS-Repository: ([0-9a-f-]{36})\nCRS-Platform: ([^\n]+)\nCRS-Root: ([0-9a-f-]{36})\n*',message)
                if not match or (match[2],match[3],match[4])!=(state['repository_id'],state['platform'],state['root_id']):raise ValueError('Git source branch has foreign or unrecognized commits')
                version=str(uuid.UUID(match[1]))
                if version in versions:raise ValueError('Duplicate repository version in Git source branch')
                versions[version]=commit
        return head,versions

    def tree(self,files):
        # One blob-writing process and a private index, independent of file count.
        with tempfile.TemporaryDirectory(prefix='crs-tree-',dir=self.directory) as folder:
            work=Path(folder);names=sorted(files);write_files(work/'files',files)
            paths=b''.join((work/'files'/name).as_posix().encode('utf-8')+b'\n' for name in names)
            hashes=self.execute('hash-object','-w','--no-filters','--stdin-paths',input=paths).stdout.splitlines()
            if len(hashes)!=len(names):raise ValueError('Git did not store the complete XML tree')
            index=work/'index'
            records=b''.join(b'100644 '+oid+b'\t'+name.encode('utf-8')+b'\0' for name,oid in zip(names,hashes))
            self.execute('update-index','-z','--index-info',input=records,index=index)
            return self.execute('write-tree',index=index).stdout.decode().strip()

    def files(self,commit):
        listing=self.execute('ls-tree','-rz','-r',commit).stdout
        entries=[]
        for record in listing.split(b'\0'):
            if not record:continue
            info,path=record.split(b'\t',1);mode,kind,oid=info.split()
            if mode!=b'100644' or kind!=b'blob':raise ValueError('Unsupported Git XML tree entry')
            entries.append((path.decode('utf-8'),oid))
        raw=self.execute('cat-file','--batch',input=b''.join(oid+b'\n' for _,oid in entries)).stdout
        result={};pos=0
        for name,oid in entries:
            end=raw.index(b'\n',pos);fields=raw[pos:end].split();size=int(fields[2]);pos=end+1
            if fields[:2]!=[oid,b'blob']:raise ValueError('Invalid Git blob response')
            result[name]=raw[pos:pos+size];pos+=size+1
        if pos!=len(raw):raise ValueError('Trailing Git blob data')
        return result

    def commit(self,files,message,parents=()):
        args=['commit-tree',self.tree(files)]
        for parent in parents:
            if parent:args+=['-p',parent]
        return self.execute(*args,input=(message+'\n').encode('utf-8')).stdout.decode().strip()

    def merge(self,base,local,remote):
        result=self.execute('merge-tree','--write-tree','--name-only','-z','--merge-base='+base,local,remote,allowed=(0,1))
        parts=result.stdout.split(b'\0');tree=parts[0].decode();conflicts=[]
        if result.returncode:
            for value in parts[1:]:
                if not value:break
                conflicts.append(value.decode('utf-8'))
        return tree,conflicts,result.stdout


def record_source(git,state,files):
    """Record a verified received version, including one received after a put."""
    if version_map(files)!=expected_versions(state):raise ValueError('Source XML versions differ from cached repository')
    git.initialize();head,versions=git.history(state);version=state['repository_version']
    if version in versions:
        if versions[version]!=head:raise ValueError('Repository version moved backwards relative to XML history')
        return head
    message='CRS repository version '+version+'\n\nCRS-Repository: '+state['repository_id']+'\nCRS-Platform: '+state['platform']+'\nCRS-Root: '+state['root_id']
    commit=git.commit(files,message,[head] if head else [])
    git.execute('update-ref',git.source_ref,commit,head or '0'*40)
    return commit


def reconcile(request):
    cache=repository_cache.Cache(request['cache_directory'])
    with cache.locked():
        state,image,cf=cache.load()
        if request['generation']!=state['generation']:raise ValueError('Cache changed before XML synchronization')
        base,base_files,_,base_root=export.inventory(request['baseline_directory'])
        local,local_files,_,local_root=export.inventory(request['directory'])
        if base==local or base in local.parents or local in base.parents:raise ValueError('Source and target XML directories must be separate')
        if base_root['id']!=state['root_id'] or local_root['id']!=state['root_id']:raise ValueError('XML belongs to another configuration root')
        version_map(base_files)
        fingerprints=(export.fingerprint(base_files),export.fingerprint(local_files))
        git=Git(request.get('xml_repository',cache.directory/'xml.git'),request.get('source_branch',DEFAULT_SOURCE_BRANCH));git.initialize()
        head,versions=git.history(state)
        run=cache.directory/'xml-runs'/uuid.uuid4().hex;run.mkdir(parents=True)
        compiler_request=dict(compiler=dict(backend='ibcmd',executable=request['executable'],base_cf=str(cf)))
        version=state['repository_version']
        if version not in versions:
            incoming=run/'export'
            with ibcmd_backend.Compiler(compiler_request) as compiler:
                compiler.execute('cf','export',cf,incoming,'--platform',state['platform'])
            _,incoming_files,incoming_records,incoming_root=export.inventory(incoming)
            ibcmd_backend.require_complete_export(image,incoming_records,incoming_files)
            if incoming_root['id']!=state['root_id'] or version_map(incoming_files)!=expected_versions(state):raise ValueError('Exported XML versions differ from cached repository')
            if head:
                previous=run/'previous';write_files(previous,git.files(head))
                incoming_files=retain_unchanged(previous,incoming)
            commit=record_source(git,state,incoming_files)
        else:
            commit=versions[version]
            if commit!=head:raise ValueError('Repository version moved backwards relative to XML history')
        remote=run/'remote';remote_files=git.files(commit)
        if version_map(remote_files)!=expected_versions(state):raise ValueError('Git source snapshot differs from cached repository versions')
        write_files(remote,remote_files)
        # Matching native stream versions permit preserving the caller's export
        # representation (zero helper IDs can differ between XML exporters).
        incoming_files=retain_unchanged(base,remote)
        baseline=run/'baseline';write_files(baseline,incoming_files)
        local_files=dict(local_files);local_files['ConfigDumpInfo.xml']=base_files['ConfigDumpInfo.xml']
        base_commit=git.commit(base_files,'CRS merge base')
        local_commit=git.commit(local_files,'CRS local XML snapshot',[base_commit])
        incoming_commit=git.commit(incoming_files,'CRS incoming XML snapshot',[base_commit])
        tree,conflicts,output=git.merge(base_commit,local_commit,incoming_commit)
        report=dict(merged=not conflicts,repository_version=version,repository_commit=commit,
                    source_branch=git.source_branch,git_directory=str(git.directory),
                    conflicts=[dict(path=name,reason='Git merge conflict') for name in conflicts],
                    baseline_directory=str(baseline),original_baseline_directory=str(base),original_directory=str(local))
        if not conflicts:
            merged_commit=git.execute('commit-tree',tree,'-p',local_commit,'-p',commit,input=b'CRS merged XML workspace\n').stdout.decode().strip()
            branch='codex/crs-work/'+run.name;target=run/'target'
            git.execute('update-ref','refs/heads/'+branch,merged_commit,'0'*40)
            git.execute('worktree','add',target,branch)
            try:export.inventory(target)
            except (ValueError,E.ParseError) as error:
                report.update(merged=False,conflicts=[dict(path='',reason='Merged XML export is inconsistent: '+str(error))])
            report.update(directory=str(target),work_branch=branch,work_commit=merged_commit)
        (run/'merge-output.bin').write_bytes(output)
        after=(export.fingerprint(export.inventory(base)[1]),export.fingerprint(export.inventory(local)[1]))
        if after!=fingerprints:report.update(merged=False,conflicts=[dict(path='',reason='Input XML changed during synchronization')])
        report_path=run/'report.json';report['report_file']=str(report_path)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return report


if __name__=='__main__':
    from serializer_cli import run
    run(reconcile)
