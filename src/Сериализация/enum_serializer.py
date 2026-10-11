"""Experimental Enum body with inline values, using the legacy profile."""
from flat_object_serializer import object_xml


def enum_xml(text, platform='8.5.1.1529'):
    return object_xml(text, platform, 'Enum')
