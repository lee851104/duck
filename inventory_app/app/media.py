import hashlib
import io
import posixpath
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image, ImageOps

from .common import Problem

REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def relations(z, parent):
    directory, name = posixpath.split(parent)
    rel_path = posixpath.join(directory, '_rels', name+'.rels')
    if rel_path not in z.namelist():
        return {}
    result = {}
    for r in ET.fromstring(z.read(rel_path)):
        if r.get('TargetMode') == 'External':
            continue
        target = r.get('Target', '')
        path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(directory, target))
        if path.startswith('../') or '\\' in path:
            raise Problem('圖片路徑不安全')
        result[r.get('Id')] = path
    return result


def extract_media(xlsx_path, staging_dir):
    out = Path(staging_dir)
    out.mkdir(parents=True, exist_ok=True)
    images = []
    with ZipFile(xlsx_path) as z:
        rels = relations(z, 'xl/workbook.xml')
        workbook = ET.fromstring(z.read('xl/workbook.xml'))
        for sheet in workbook.findall('.//{*}sheet'):
            sheet_path = rels[sheet.attrib[REL]]
            sheet_rels = relations(z, sheet_path)
            sheet_xml = ET.fromstring(z.read(sheet_path))
            for drawing in sheet_xml.findall('.//{*}drawing'):
                draw_path = sheet_rels.get(drawing.attrib[REL])
                if not draw_path:
                    continue
                draw_rels = relations(z, draw_path)
                for anchor in ET.fromstring(z.read(draw_path)):
                    blip = anchor.find('.//{*}blip')
                    origin = anchor.find('{*}from')
                    if blip is None or origin is None:
                        continue
                    rid = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                    target = draw_rels.get(rid)
                    if not target or z.getinfo(target).file_size > 50*1024*1024:
                        continue
                    raw = z.read(target)
                    digest = hashlib.sha256(raw).hexdigest()
                    ext = Path(target).suffix.lower()
                    if ext not in {'.png', '.jpeg', '.jpg', '.webp', '.gif'}:
                        continue
                    original = out/(digest+ext)
                    thumbnail = out/(digest+'.thumb.jpg')
                    if not original.exists():
                        original.write_bytes(raw)
                    if not thumbnail.exists():
                        with Image.open(io.BytesIO(raw)) as im:
                            image = ImageOps.exif_transpose(im).convert('RGB')
                            image.thumbnail((480, 480))
                            image.save(thumbnail, 'JPEG', quality=85)
                    images.append({'sheet': sheet.get('name'),
                                   'row': int(origin.find('{*}row').text)+1,
                                   'col': int(origin.find('{*}col').text)+1,
                                   'original_path': original.name, 'thumbnail_path': thumbnail.name})
    return images
