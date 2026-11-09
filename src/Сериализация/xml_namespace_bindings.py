"""Read namespace declarations from XML."""
import xml_namespaces


def namespaces(xml):
    return xml_namespaces.namespace_bindings(xml,'appearance')
