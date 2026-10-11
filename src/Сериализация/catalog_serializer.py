"""Experimental default Catalog XML body, using the legacy platform profile."""
from flat_object_serializer import object_xml


def catalog_xml(text, platform='8.5.1.1529'):
    return object_xml(text, platform, 'Catalog')
