import re


def category_key(category):
    """Keep source category order, with numeric prefixes sorted naturally."""
    text = category or ''
    parts = tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                  for part in re.split(r'(\d+)', text) if part)
    return (not bool(text), parts)


def product_key(product):
    return (category_key(product.get('category')),
            not bool(product.get('image')),
            product.get('code') or product.get('name') or '',
            str(product['id']))
