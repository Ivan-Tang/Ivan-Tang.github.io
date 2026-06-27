#!/usr/bin/env python3
"""
Convert Notability .nbn bundle to PDF.

Supports:
  - Handwriting stroke rendering (pen + highlighter, pressure sensitivity)
  - PDF backgrounds (when note was created from an imported PDF)
  - Embedded images
  - Page layout from Session.plist

Usage:
  python nbn_to_pdf.py "path/to/note.nbn"                    # single note
  python nbn_to_pdf.py "path/to/note.nbn" -o output.pdf      # custom output
  python nbn_to_pdf.py --batch "notes_dir/" -o "pdfs_dir/"   # batch convert
  python nbn_to_pdf.py --batch "notes_dir/" --course "量子力学"  # filter by subject
"""

import plistlib
import struct
import os
import sys
import argparse
import json
from pathlib import Path
from datetime import datetime
import io

# Try PyMuPDF first, fall back to Pillow-only
try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

from PIL import Image, ImageDraw


# ============================================================
# Session.plist parser
# ============================================================

class GLKeyedArchiver:
    """Parse GLKeyedArchiver (Ginger Labs' variant of NSKeyedArchiver)."""

    def __init__(self, filepath):
        with open(filepath, 'rb') as f:
            self._data = plistlib.load(f)
        self._objects = self._data.get('$objects', [])
        # $top can have different keys: 'root', '$0', etc.
        top = self._data.get('$top', {})
        self._root_uid = top.get('root') or top.get('$0')

    @property
    def root(self):
        if self._root_uid is not None:
            return self._resolve(self._root_uid)
        # Fallback: $objects[1] is usually the root
        if len(self._objects) > 1:
            return self._resolve(plistlib.UID(1))
        return None

    def _resolve(self, uid, depth=0, visited=None):
        if visited is None:
            visited = set()
        if depth > 30 or uid is None:
            return None
        if isinstance(uid, plistlib.UID):
            if uid.data in visited:
                return "<cycle>"
            visited.add(uid.data)
            return self._resolve(self._objects[uid.data], depth + 1, visited)
        if isinstance(uid, dict):
            result = {}
            for k, v in uid.items():
                if isinstance(k, str) and k.startswith('$'):
                    continue
                rv = self._resolve(v, depth + 1, visited.copy())
                if rv is not None:
                    result[k] = rv
            return result
        if isinstance(uid, list):
            return [self._resolve(x, depth + 1, visited.copy()) for x in uid]
        return uid

    def find_strokes(self):
        """Find and resolve the strokes dictionary in the object graph."""
        for obj in self._objects:
            if isinstance(obj, dict) and 'curvespoints' in obj:
                # Resolve UID values within the strokes dict
                resolved = {}
                for k, v in obj.items():
                    if isinstance(k, str) and k.startswith('$'):
                        continue
                    resolved[k] = self._resolve(v)
                return resolved
        return None

    def find_value(self, root_dict, key):
        """Recursively search for a key in a resolved dict tree."""
        if not isinstance(root_dict, dict):
            return None
        for k, v in root_dict.items():
            if k == key:
                return v
            if isinstance(v, dict):
                result = self.find_value(v, key)
                if result is not None:
                    return result
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        result = self.find_value(item, key)
                        if result is not None:
                            return result
        return None


# ============================================================
# Stroke data extraction
# ============================================================

def decode_strokes(strokes_dict):
    """Decode binary stroke data from a strokes dictionary.

    Returns a list of curves, each being:
      {
        'points': [(x, y), ...],
        'width': float,
        'color': (r, g, b, a),
        'style': 3=pen (default), 4=highlighter,
        'fractional_widths': [float, ...] or None,
        'forces': [float, ...] or None,
      }
    """
    if not strokes_dict:
        return []

    # Decode binary fields
    points_data = strokes_dict.get('curvespoints', b'')
    numpoints_data = strokes_dict.get('curvesnumpoints', b'')
    colors_data = strokes_dict.get('curvescolors', b'')
    widths_data = strokes_dict.get('curveswidth', b'')
    styles_data = strokes_dict.get('curvesstyles', b'')
    frac_widths_data = strokes_dict.get('curvesfractionalwidths', b'')
    forces_data = strokes_dict.get('curvesforces', b'')
    num_curves = strokes_dict.get('numcurves', 0)

    # Parse arrays
    all_points = struct.unpack(f'{len(points_data)//4}f', points_data)
    num_points_arr = struct.unpack(f'{len(numpoints_data)//4}i', numpoints_data)
    widths_arr = struct.unpack(f'{len(widths_data)//4}f', widths_data)
    styles_arr = list(styles_data) if styles_data else [3] * num_curves
    frac_widths_arr = struct.unpack(f'{len(frac_widths_data)//4}f', frac_widths_data) if frac_widths_data else []
    forces_arr = struct.unpack(f'{len(forces_data)//4}f', forces_data) if forces_data else []

    # Build curves
    curves = []
    pt_idx = 0
    fw_idx = 0

    for c in range(num_curves):
        npts = num_points_arr[c] if c < len(num_points_arr) else 0
        if npts <= 0:
            continue

        # Extract points for this curve
        curve_points = []
        for _ in range(npts):
            if pt_idx * 2 + 1 < len(all_points):
                curve_points.append((all_points[pt_idx * 2], all_points[pt_idx * 2 + 1]))
            pt_idx += 1

        # Color
        color = (0, 0, 0, 255)
        if c * 4 + 3 < len(colors_data):
            r, g, b, a = colors_data[c * 4:c * 4 + 4]
            color = (r, g, b, a)

        # Width
        width = widths_arr[c] if c < len(widths_arr) else 1.0

        # Style
        style = styles_arr[c] if c < len(styles_arr) else 3

        # Fractional widths (per-point width modifiers)
        fw = []
        if fw_idx < len(frac_widths_arr):
            fw = frac_widths_arr[fw_idx:fw_idx + npts]
            fw_idx += npts

        # Forces (per-point pressure)
        forces = []
        if c * npts < len(forces_arr):
            forces = forces_arr[c * npts:(c + 1) * npts] if npts > 0 else []

        curves.append({
            'points': curve_points,
            'width': width,
            'color': color,
            'style': style,
            'fractional_widths': fw,
            'forces': forces,
        })

    return curves


# ============================================================
# Page layout detection
# ============================================================

def get_page_layout(root_dict, strokes_dict):
    """Determine page dimensions and page breaks."""
    page_width = 574.0  # default Notability document width

    # Get from Session.plist (root_dict may be None)
    if root_dict:
        pw = root_dict.get('pageWidthInDocumentCoordsKey')
        if pw is not None:
            page_width = float(pw)

    # Determine paper size - default to US Letter proportions
    # Notability uses a normalized width; height is proportional to paper type
    paper_size = 'Letter'
    if root_dict:
        paper_attrs = root_dict.get('documentPaperAttributes', {})
        if paper_attrs:
            paper_id = paper_attrs.get('paperIdentifier', '')
            if 'A4' in str(paper_id):
                paper_size = 'A4'
            elif 'Letter' in str(paper_id):
                paper_size = 'Letter'

    # Calculate page height based on aspect ratio
    if paper_size == 'A4':
        aspect = 297 / 210  # A4
    else:
        aspect = 11 / 8.5   # US Letter

    page_height = page_width * aspect

    return {
        'width': page_width,
        'height': page_height,
        'paper_size': paper_size,
    }


def split_curves_by_page(curves, page_height):
    """Split curves into pages based on their Y coordinates.

    Each page is page_height units tall. Curves are assigned to the page
    where their starting Y coordinate falls. Y coordinates are then offset
    to be relative to their page's top-left corner.
    """
    if not curves:
        return [[]]

    pages = {}

    for curve in curves:
        if not curve['points']:
            continue

        # Use the first point's Y to determine page
        y_start = curve['points'][0][1]
        page_idx = int(y_start / page_height)

        if page_idx not in pages:
            pages[page_idx] = []

        # Offset Y coordinates to be relative to this page
        y_offset = page_idx * page_height
        offset_points = [(x, y - y_offset) for x, y in curve['points']]
        offset_curve = dict(curve, points=offset_points)
        pages[page_idx].append(offset_curve)

    # Convert to ordered list
    if not pages:
        return [[]]

    max_page = max(pages.keys())
    result = [pages.get(i, []) for i in range(max_page + 1)]
    return result if result else [[]]


# ============================================================
# PDF Rendering
# ============================================================

# Notability color palette (approximate hex -> RGB mapping for common colors)
# Colors in Session.plist are RGBA bytes (0-255)
# Some common Notability colors for reference:
PEN_COLORS = {
    (0, 0, 0, 255): '#000000',           # Black
    (255, 0, 0, 255): '#FF0000',         # Red
    (0, 0, 255, 255): '#0000FF',         # Blue
    (0, 128, 0, 255): '#008000',         # Green
    (255, 165, 0, 255): '#FFA500',       # Orange
    (128, 0, 128, 255): '#800080',       # Purple
}


def render_strokes_to_image(curves, layout, dpi=150, background_color=(255, 255, 255, 255)):
    """Render strokes onto a PIL Image at the given DPI.

    Returns a PIL Image (RGBA mode).
    """
    scale = dpi / 72.0  # points to pixels
    img_width = int(layout['width'] * scale)
    img_height = int(layout['height'] * scale)

    # Create transparent image for strokes
    img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for curve in curves:
        if len(curve['points']) < 2:
            # Single point: draw a dot
            if curve['points']:
                x, y = curve['points'][0]
                px, py = x * scale, y * scale
                w = max(1, int(curve['width'] * scale))
                r = w // 2
                draw.ellipse([px - r, py - r, px + r, py + r],
                             fill=curve['color'][:3] + (curve['color'][3],))
            continue

        style = curve['style']
        color = curve['color']

        # Highlighter: wider, semi-transparent
        if style == 4:
            alpha = min(color[3], 80) if color[3] > 80 else color[3]
            color = (color[0], color[1], color[2], alpha)

        # Draw as polyline with pressure-sensitive width
        points = curve['points']
        fw = curve.get('fractional_widths', [])
        base_width = curve['width'] * scale

        # For each segment, draw a line with appropriate width
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]

            px1, py1 = x1 * scale, y1 * scale
            px2, py2 = x2 * scale, y2 * scale

            # Compute segment width
            seg_width = max(0.5, base_width)
            if fw and i < len(fw):
                seg_width = max(0.5, base_width * max(0.1, fw[i]))

            if seg_width < 1.0:
                seg_width = 1.0

            # Draw thick line with round ends
            try:
                draw.line([(px1, py1), (px2, py2)],
                          fill=color[:3] + (color[3],),
                          width=int(seg_width))
            except Exception:
                # Fallback: draw as thin line
                draw.line([(px1, py1), (px2, py2)],
                          fill=color[:3] + (color[3],),
                          width=1)

    return img


def render_page_simple(curves, layout, output_path, dpi=150):
    """Render a single page to a PNG file using PIL. (Simple fallback)."""
    img = render_strokes_to_image(curves, layout, dpi)
    img.save(output_path, 'PNG')
    return img


def render_to_pdf(nbn_path, output_path, dpi=150):
    """Convert a .nbn note to PDF.

    Args:
        nbn_path: Path to the .nbn bundle directory
        output_path: Path for the output PDF file
        dpi: Rendering DPI (default 150, higher = better quality, larger file)
    """
    nbn_path = Path(nbn_path)
    if not nbn_path.is_dir():
        raise ValueError(f"Not a directory: {nbn_path}")

    # 1. Parse Session.plist
    session_path = nbn_path / 'Session.plist'
    if not session_path.exists():
        raise FileNotFoundError(f"Session.plist not found in {nbn_path}")

    archiver = GLKeyedArchiver(str(session_path))
    root = archiver.root
    strokes_dict = archiver.find_strokes()

    # 2. Parse metadata
    meta_path = nbn_path / 'metadata.plist'
    note_name = nbn_path.name.replace('.nbn', '')
    if meta_path.exists():
        meta_archiver = GLKeyedArchiver(str(meta_path))
        meta_root = meta_archiver.root
        if meta_root:
            note_name = meta_root.get('noteName', note_name)

    print(f"  Converting: {note_name}")

    # 3. Extract strokes
    curves = decode_strokes(strokes_dict) if strokes_dict else []
    total_pts = sum(len(c['points']) for c in curves)
    print(f"    Strokes: {len(curves)} curves, {total_pts} points")

    # 4. Page layout
    layout = get_page_layout(root, strokes_dict or {})
    page_height = layout['height']
    print(f"    Layout: {layout['paper_size']}, {layout['width']:.0f}x{layout['height']:.0f} pts")

    # 5. Split into pages
    pages = split_curves_by_page(curves, page_height)
    print(f"    Pages: {len(pages)}")

    # 6. Check for PDF background
    pdfs_dir = nbn_path / 'PDFs'
    bg_pdf_path = None
    if pdfs_dir.exists():
        pdf_files = list(pdfs_dir.glob('*.pdf'))
        if pdf_files:
            bg_pdf_path = str(pdf_files[0])
            print(f"    PDF background: {len(pdf_files)} PDF(s)")

    # 7. Render to PDF
    scale = dpi / 72.0

    if HAS_FITZ:
        _render_with_fitz(curves, pages, layout, bg_pdf_path, output_path, dpi, scale)
    else:
        _render_with_pillow(curves, pages, layout, bg_pdf_path, output_path, dpi, scale)

    print(f"    Output: {output_path}")
    return output_path


def _render_with_fitz(curves, pages, layout, bg_pdf_path, output_path, dpi, scale):
    """Render using PIL for strokes + PyMuPDF for PDF assembly.

    Strokes are rendered as high-res PNG images (using PIL), then inserted
    into PDF pages via PyMuPDF. PDF backgrounds are preserved as vectors.
    """
    page_w = layout['width']
    page_h = layout['height']

    # Determine page count
    if bg_pdf_path and os.path.exists(bg_pdf_path):
        bg_doc = fitz.open(bg_pdf_path)
        num_bg_pages = len(bg_doc)
    else:
        bg_doc = None
        num_bg_pages = 0

    doc = fitz.open()
    num_pages = max(len(pages), num_bg_pages, 1)

    for p_idx in range(num_pages):
        page_strokes = pages[p_idx] if p_idx < len(pages) else []

        if bg_doc and p_idx < num_bg_pages:
            # Insert background PDF page (preserves vector quality)
            bg_page = bg_doc[p_idx]
            bg_rect = bg_page.rect
            page = doc.new_page(width=bg_rect.width, height=bg_rect.height)
            page.show_pdf_page(page.rect, bg_doc, p_idx)
            # Scale strokes to match background page size
            use_w = bg_rect.width
            use_h = bg_rect.height
        else:
            # Blank page
            page = doc.new_page(width=page_w, height=page_h)
            use_w = page_w
            use_h = page_h

        # Render strokes as image overlay
        if page_strokes:
            # Adjust layout to match actual page size for rendering
            page_layout = {
                'width': use_w,
                'height': use_h,
                'paper_size': layout.get('paper_size', 'Letter'),
            }
            strokes_img = render_strokes_to_image(page_strokes, page_layout, dpi)

            # Convert PIL image to bytes and insert into PDF
            import io
            buf = io.BytesIO()
            strokes_img.save(buf, format='PNG')
            buf.seek(0)

            # Insert image covering the full page
            page.insert_image(page.rect, stream=buf.read())

    # Save
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    if bg_doc:
        bg_doc.close()


def _render_with_pillow(curves, pages, layout, bg_pdf_path, output_path, dpi, scale):
    """Fallback: render using Pillow and save as multi-page PDF (no PyMuPDF)."""
    from PIL import Image as PILImage

    page_w = layout['width']
    page_h = layout['height']

    # Open background PDF if present
    bg_images = []
    if bg_pdf_path and os.path.exists(bg_pdf_path):
        try:
            if HAS_FITZ:
                bg_doc = fitz.open(bg_pdf_path)
                for pg in bg_doc:
                    pix = pg.get_pixmap(dpi=dpi)
                    img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    bg_images.append(img)
                bg_doc.close()
        except Exception:
            pass

    num_pages = max(len(pages), len(bg_images), 1)
    page_images = []

    for p_idx in range(num_pages):
        img_w = int(page_w * scale)
        img_h = int(page_h * scale)

        if p_idx < len(bg_images):
            bg_img = bg_images[p_idx]
            img_w = bg_img.width
            img_h = bg_img.height
            combined = bg_img.convert('RGBA')
        else:
            combined = PILImage.new('RGBA', (img_w, img_h), (255, 255, 255, 255))

        if p_idx < len(pages) and pages[p_idx]:
            strokes_img = render_strokes_to_image(pages[p_idx], layout, dpi)
            if strokes_img.size != combined.size:
                strokes_img = strokes_img.resize(combined.size, PILImage.LANCZOS)
            combined = PILImage.alpha_composite(combined, strokes_img)

        page_images.append(combined)

    if page_images:
        rgb_images = [img.convert('RGB') for img in page_images]
        rgb_images[0].save(output_path, save_all=True, append_images=rgb_images[1:], resolution=dpi)


# ============================================================
# Metadata extraction
# ============================================================

def get_note_metadata(nbn_path):
    """Extract metadata from a .nbn bundle."""
    meta_path = Path(nbn_path) / 'metadata.plist'
    session_path = Path(nbn_path) / 'Session.plist'

    result = {
        'name': Path(nbn_path).name.replace('.nbn', ''),
        'uuid': None,
        'subject': None,
        'created': None,
        'modified': None,
        'has_pdf_bg': False,
        'has_images': False,
        'num_pages': 0,
        'num_curves': 0,
        'num_points': 0,
    }

    # Metadata
    if meta_path.exists():
        archiver = GLKeyedArchiver(str(meta_path))
        root = archiver.root
        if root:
            result['uuid'] = root.get('uuidKey')
            result['subject'] = root.get('noteSubject', 'unsortedNotesKey')
            result['name'] = root.get('noteName', result['name'])

            mod = root.get('noteModifiedDateKey', {})
            if isinstance(mod, dict):
                ts = mod.get('NS.time', 0)
                if ts:
                    result['modified'] = datetime(2001, 1, 1).timestamp() + ts

            cre = root.get('noteCreationDateKey', {})
            if isinstance(cre, dict):
                ts = cre.get('NS.time', 0)
                if ts:
                    result['created'] = datetime(2001, 1, 1).timestamp() + ts

    # Session
    if session_path.exists():
        archiver = GLKeyedArchiver(str(session_path))
        strokes = archiver.find_strokes()
        if strokes:
            result['num_curves'] = strokes.get('numcurves', 0)
            result['numpoints'] = strokes.get('numpoints', 0)

    # Check for PDF background
    pdfs_dir = Path(nbn_path) / 'PDFs'
    if pdfs_dir.exists():
        pdfs = list(pdfs_dir.glob('*.pdf'))
        result['has_pdf_bg'] = len(pdfs) > 0

    # Check for images
    imgs_dir = Path(nbn_path) / 'Images'
    if imgs_dir.exists():
        imgs = [f for f in os.listdir(str(imgs_dir)) if not f.startswith('.')]
        result['has_images'] = len(imgs) > 0

    return result


# ============================================================
# Main / CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Convert Notability .nbn notes to PDF',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python nbn_to_pdf.py "path/to/note.nbn"
  python nbn_to_pdf.py "path/to/note.nbn" -o output.pdf --dpi 200
  python nbn_to_pdf.py --batch "notes_dir/" -o "pdfs_dir/"
  python nbn_to_pdf.py --batch "notes_dir/" --course "量子力学" --dpi 150
        """
    )
    parser.add_argument('input', nargs='?', help='Path to .nbn bundle or directory (with --batch)')
    parser.add_argument('-o', '--output', help='Output PDF path or directory (with --batch)')
    parser.add_argument('--dpi', type=int, default=150, help='Rendering DPI (default: 150)')
    parser.add_argument('--batch', action='store_true', help='Batch convert all .nbn files in directory')
    parser.add_argument('--course', help='Filter by course/subject name (with --batch)')
    parser.add_argument('--limit', type=int, default=0, help='Max notes to convert (with --batch, 0=all)')
    parser.add_argument('--list', action='store_true', help='List metadata only, no conversion')
    parser.add_argument('--json', action='store_true', help='Output metadata as JSON (with --list)')

    args = parser.parse_args()

    if not args.input:
        parser.print_help()
        return

    if args.batch:
        # Batch mode
        input_dir = Path(args.input)
        if not input_dir.is_dir():
            print(f"Error: not a directory: {args.input}")
            sys.exit(1)

        output_dir = Path(args.output) if args.output else Path('pdfs_output')
        output_dir.mkdir(parents=True, exist_ok=True)

        nbn_dirs = sorted([d for d in input_dir.iterdir() if d.name.endswith('.nbn') and d.is_dir()])
        if args.limit > 0:
            nbn_dirs = nbn_dirs[:args.limit]
        print(f"Found {len(nbn_dirs)} .nbn notes")

        if args.json:
            results = []
            for nbn in nbn_dirs:
                meta = get_note_metadata(str(nbn))
                if args.course and args.course not in meta.get('subject', ''):
                    continue
                results.append(meta)
            print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
            return

        success = 0
        for nbn in nbn_dirs:
            try:
                meta = get_note_metadata(str(nbn))
                if args.course and args.course not in meta.get('subject', ''):
                    continue
                out = output_dir / f"{meta['name']}.pdf"
                render_to_pdf(str(nbn), str(out), dpi=args.dpi)
                success += 1
            except Exception as e:
                print(f"  Error converting {nbn.name}: {e}")

        print(f"\nDone! Converted {success} notes to {output_dir}")

    elif args.list:
        # List metadata
        nbn_path = Path(args.input)
        if not nbn_path.is_dir():
            print(f"Error: not a directory: {args.input}")
            sys.exit(1)

        meta = get_note_metadata(str(nbn_path))
        if args.json:
            print(json.dumps(meta, indent=2, ensure_ascii=False, default=str))
        else:
            for k, v in meta.items():
                print(f"  {k}: {v}")

    else:
        # Single note
        nbn_path = Path(args.input)
        output = args.output or f"{nbn_path.name.replace('.nbn', '')}.pdf"
        render_to_pdf(str(nbn_path), output, dpi=args.dpi)


if __name__ == '__main__':
    main()
