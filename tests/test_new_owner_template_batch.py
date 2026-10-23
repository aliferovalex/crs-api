"""A complete export creates owners, forms and templates without intermediate packets."""
import base64
import unittest
import uuid
from unittest.mock import patch
from xml.etree import ElementTree as E

import test_configuration_commit as cases
from test_managed_form_creation import store
from test_owned_template_creation import request
import configuration_commit as commit
import configuration_batch as batch
import metadata_context
import native_metadata as s
import template_content


class NewOwnerTemplateBatchTests(unittest.TestCase):
    def test_new_owner_with_forms_and_templates_joins_changes_and_deletion(self):
        fixture=cases.ConfigurationCommitTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        r,_=fixture.request();new=request();q=commit.preparation.Q
        owner=E.fromstring(new['object_xml'])[0];oid=owner.get('uuid');name=owner.findtext(q+'Properties/'+q+'Name')
        root=fixture.export.new/'Configuration.xml';top=E.parse(root);E.SubElement(top.getroot()[0].find(q+'ChildObjects'),q+'Catalog').text=name;top.write(root,encoding='utf-8')
        path=fixture.export.new/'Catalogs'/(name+'.xml');path.parent.mkdir();path.write_text(new['object_xml'],encoding='utf-8')
        for tag,entries in (('Forms',new['forms']),('Templates',new['templates'])):
            for entry in entries:
                file=path.with_suffix('')/tag/(entry['name']+'.xml');file.parent.mkdir(parents=True,exist_ok=True);file.write_text(entry['definition_xml'],encoding='utf-8')
                ext=file.with_suffix('')/'Ext';ext.mkdir(parents=True)
                if tag=='Forms':
                    (ext/'Form.xml').write_text(entry['form_xml'],encoding='utf-8');(ext/'Form').mkdir();(ext/'Form/Module.bsl').write_text(entry['module_text'],encoding='utf-8')
                else:
                    typ=template_content.kind(entry['definition_xml']);(ext/template_content.PROFILES[typ]['file']).write_bytes(entry['template_xml'].encode('utf-8') if typ=='DataCompositionSchema' else base64.b64decode(entry['template_data']))
        plan,_=commit.prepare(r);self.assertEqual(len(plan['new_ids']),6)
        self.assertEqual(len(plan['creation_plans']),1);self.assertEqual(len(plan['creation_plans'][0]['templates']),3)
        r.update(target_fingerprint=plan['target_fingerprint'],baseline_fingerprint=plan['baseline_fingerprint'])
        for key in plan['snapshot_ids']:
            if key not in r['snapshots']:
                r['snapshots'][key]=store(fixture.objects[key],b'unchanged opaque metadata body')
                r['originals'][key]=uuid.UUID(s.val(fixture.objects[key][0][7])).bytes_le.hex()+'00000000'
        with patch.object(commit.packets,'assemble',wraps=commit.packets.assemble) as assemble:
            result=commit.serialize(r);self.assertEqual(assemble.call_count,1)
        self.assertEqual(len(result['new_ids']),6);self.assertEqual(len(result['removed_ids']),1)
        _,records=batch.read_packet(result['data']);by_id={row.object_id:row for row in records}
        metadata=s.Parser(by_id[oid].metadata.decode('utf-8-sig')).documents()[0]
        self.assertEqual(len(metadata_context.children(metadata)),5)
        self.assertTrue(all(s.val(s.Parser(by_id[key].metadata.decode('utf-8-sig')).documents()[0][3])==oid for key in result['new_ids'] if key!=oid))


if __name__=='__main__':unittest.main()
