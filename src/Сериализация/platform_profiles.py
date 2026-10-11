"""Version policy, independent of exact legacy build numbers.

Older releases use the 8.5.1 profile as a compatibility assumption; the native
snapshot checks still reject layouts that do not match this profile.
"""
import re


def version_parts(version):
    if not isinstance(version, str) or not re.fullmatch(r'8\.[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Invalid platform version: ' + str(version))
    return tuple(int(part) for part in version.split('.'))


def profile(version):
    parts = version_parts(version)
    if parts[:3] <= (8, 5, 1):
        return 'legacy'
    if version == '8.5.4.1878':
        return 'modern'
    raise ValueError('Unsupported platform: ' + version)


def legacy(version):
    return profile(version) == 'legacy'


def configuration_layout(version):
    return (76, 77) if legacy(version) else (79, 81)


def xml_attributes(attributes, version):
    if not attributes:
        return True
    if set(attributes) != {'version'}:
        return False
    if legacy(version):
        # Earlier Designer XML revisions use the same namespace. Field/layout
        # validation remains mandatory; accepting a revision is not a proof of
        # compatibility with every release that can export it.
        value = attributes['version']
        return bool(re.fullmatch(r'2\.(0|[1-9][0-9]*)', value)) and int(value.split('.')[1]) <= 21
    return attributes == {'version': '2.22'}
