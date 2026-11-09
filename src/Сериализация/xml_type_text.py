"""Read scalar XML type names."""

Q='{http://v8.1c.ru/8.1/data/core}'


def text(node):
    if node.attrib or len(node):raise ValueError('Unsupported Type structure')
    return node.text or ''
