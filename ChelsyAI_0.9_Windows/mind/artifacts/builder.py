"""Artifact Builder — model provides structure; this code builds real files."""
from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

ARTIFACT_FORMATS = ('txt', 'docx', 'pdf', 'pptx', 'xlsx')

DANGEROUS_NAME = re.compile(r'[\\/:\0<>"|?*]')


@dataclass
class ArtifactSpec:
    format: str
    title: str
    language: str
    sections: list[dict]  # {heading, paragraphs: [str], bullets?: [str]}
    tables: list[dict] | None = None  # {headers, rows}
    slides: list[dict] | None = None  # {title, bullets, notes}
    sources: list[str] | None = None
    sheet_name: str = 'Данные'


@dataclass
class BuiltArtifact:
    format: str
    mime: str
    filename: str
    path: Path
    sha256: str
    size_bytes: int


MIME = {
    'txt': 'text/plain; charset=utf-8',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pdf': 'application/pdf',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}


def safe_filename(title: str, ext: str) -> str:
    base = DANGEROUS_NAME.sub('_', (title or 'document').strip())[:80] or 'document'
    base = re.sub(r'[\x00-\x1f\x7f]', '_', base).replace('..', '_').strip('. ') or 'document'
    if base.split('.')[0].upper() in {'CON','AUX','PRN','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}: base = '_' + base
    return f'{base}.{ext}'


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _write_txt(spec: ArtifactSpec, path: Path) -> None:
    lines = [spec.title, '=' * len(spec.title), '']
    for sec in spec.sections:
        if sec.get('heading'):
            lines.append(sec['heading'])
            lines.append('-' * len(sec['heading']))
        for p in sec.get('paragraphs') or []:
            lines.append(p)
            lines.append('')
        for b in sec.get('bullets') or []:
            lines.append(f'• {b}')
        lines.append('')
    if spec.sources:
        lines.append('Источники:' if spec.language == 'ru' else 'Sources:')
        for s in spec.sources:
            lines.append(f'- {s}')
    path.write_text('\n'.join(lines).strip() + '\n', encoding='utf-8')


def _write_docx(spec: ArtifactSpec, path: Path) -> None:
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document()
    doc.add_heading(spec.title, level=0)
    for i,sec in enumerate(spec.sections):
        if i: doc.add_page_break()
        if sec.get('heading'):
            doc.add_heading(sec['heading'], level=1)
        for p in sec.get('paragraphs') or []:
            doc.add_paragraph(p)
        for b in sec.get('bullets') or []:
            doc.add_paragraph(b, style='List Bullet')
    for table in spec.tables or []:
        headers = table.get('headers') or []
        rows = table.get('rows') or []
        if not headers:
            continue
        t = doc.add_table(rows=1 + len(rows), cols=len(headers))
        for i, h in enumerate(headers):
            t.rows[0].cells[i].text = str(h)
        for r_i, row in enumerate(rows):
            for c_i, cell in enumerate(row):
                t.rows[r_i + 1].cells[c_i].text = str(cell)
    if spec.sources:
        doc.add_heading('Источники' if spec.language == 'ru' else 'Sources', level=1)
        for s in spec.sources:
            doc.add_paragraph(s, style='List Number')
    # Ensure document is editable text (not a screenshot)
    doc.save(path)


def _write_pdf(spec: ArtifactSpec, path: Path) -> None:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    unicode_ok = False
    candidates = [
        Path(__file__).resolve().parents[2] / 'assets' / 'fonts' / 'DejaVuSans.ttf',
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'),
    ]
    for cand in candidates:
        if cand.is_file():
            pdf.add_font('Chelsy', '', str(cand))
            unicode_ok = True
            break
    font = 'Chelsy' if unicode_ok else 'Helvetica'

    if not unicode_ok:
        raise ValueError('Для PDF требуется встроенный шрифт Unicode.')

    def write(text: str, size: int = 11, h: float = 6):
        pdf.set_font(font, size=size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, h, text)

    write(spec.title, size=14, h=8)
    pdf.ln(4)
    for i,sec in enumerate(spec.sections):
        if i: pdf.add_page()
        if sec.get('heading'):
            write(sec['heading'], size=12, h=7)
        for p in sec.get('paragraphs') or []:
            write(p, size=11, h=6)
            pdf.ln(1)
        for b in sec.get('bullets') or []:
            write(f'- {b}', size=11, h=6)
    if spec.sources:
        pdf.ln(4)
        write('Источники:' if spec.language == 'ru' else 'Sources:', size=12, h=7)
        for s in spec.sources:
            write(f'- {s}', size=11, h=6)
    pdf.output(str(path))


def _write_pptx(spec: ArtifactSpec, path: Path) -> None:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation()
    slides = spec.slides or []
    if not slides:
        # Derive slides from sections
        slides = [{'title': spec.title, 'bullets': [], 'notes': ''}]
        for sec in spec.sections:
            slides.append({
                'title': sec.get('heading') or spec.title,
                'bullets': list(sec.get('bullets') or []) or list(sec.get('paragraphs') or [])[:5],
                'notes': '',
            })
    for slide_data in slides:
        layout = prs.slide_layouts[1] if len(prs.slide_layouts) > 1 else prs.slide_layouts[0]
        slide = prs.slides.add_slide(layout)
        if slide.shapes.title:
            slide.shapes.title.text = str(slide_data.get('title') or spec.title)
        body = None
        for shape in slide.placeholders:
            if shape.placeholder_format.idx == 1:
                body = shape
                break
        if body is not None:
            tf = body.text_frame
            tf.clear()
            bullets = slide_data.get('bullets') or []
            if not bullets:
                p = tf.paragraphs[0]
                p.text = ''
            else:
                for i, b in enumerate(bullets):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.text = str(b)
                    p.level = 0
        notes = slide_data.get('notes') or ''
        if notes:
            slide.notes_slide.notes_text_frame.text = str(notes)
    if spec.sources:
        layout = prs.slide_layouts[1] if len(prs.slide_layouts) > 1 else prs.slide_layouts[0]
        slide = prs.slides.add_slide(layout)
        if slide.shapes.title:
            slide.shapes.title.text = 'Источники' if spec.language == 'ru' else 'Sources'
        for shape in slide.placeholders:
            if shape.placeholder_format.idx == 1:
                tf = shape.text_frame
                tf.clear()
                for i, s in enumerate(spec.sources):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.text = str(s)
                break
    prs.save(path)


def _write_xlsx(spec: ArtifactSpec, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = (spec.sheet_name or 'Данные')[:31]
    tables = spec.tables or []
    if not tables:
        # default two-column content dump
        ws.append(['Раздел', 'Содержание'])
        ws['A1'].font = Font(bold=True)
        ws['B1'].font = Font(bold=True)
        for sec in spec.sections:
            text = ' '.join(sec.get('paragraphs') or sec.get('bullets') or [])
            ws.append([sec.get('heading') or '', text])
    else:
        for t_i, table in enumerate(tables):
            if t_i > 0:
                ws = wb.create_sheet(title=f'Лист{t_i + 1}'[:31])
            headers = table.get('headers') or []
            rows = table.get('rows') or []
            if headers:
                ws.append([str(h) for h in headers])
                for cell in ws[1]:
                    cell.font = Font(bold=True)
                    cell.data_type = 's'
            for row in rows:
                ws.append(row)
                for cell in ws[ws.max_row]:
                    if isinstance(cell.value,str): cell.data_type='s'
            if table.get('add_total') and headers and rows:
                from openpyxl.utils import get_column_letter
                col=len(headers)
                letter=get_column_letter(col)
                last=ws.max_row
                if col>1: ws.cell(last+1,1,'Итого' if spec.language=='ru' else 'Total')
                ws.cell(last+1,col,f'=SUM({letter}2:{letter}{last})')
            ws.freeze_panes='A2'
            ws.auto_filter.ref=f'A1:{ws.cell(len(rows)+1,len(headers)).coordinate}'
    if spec.sources:
        src = wb.create_sheet('Источники')
        src.append(['Источник'])
        for s in spec.sources:
            src.append([str(s)])
    wb.save(path)


WRITERS = {
    'txt': _write_txt,
    'docx': _write_docx,
    'pdf': _write_pdf,
    'pptx': _write_pptx,
    'xlsx': _write_xlsx,
}


def build_artifact(spec: ArtifactSpec, dest_dir: Path, *, basename: str | None = None) -> BuiltArtifact:
    if spec.format not in ARTIFACT_FORMATS:
        raise ValueError(f'Неподдерживаемый формат: {spec.format}')
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = dest_dir / '.tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(basename or spec.title, spec.format)
    tmp_path = tmp_dir / filename
    final_path = dest_dir / filename
    WRITERS[spec.format](spec, tmp_path)
    # Atomic publish after validation
    validate_artifact(spec.format, tmp_path)
    tmp_path.replace(final_path)
    digest = _sha256(final_path)
    return BuiltArtifact(
        format=spec.format, mime=MIME[spec.format], filename=filename,
        path=final_path, sha256=digest, size_bytes=final_path.stat().st_size,
    )


def validate_artifact(fmt: str, path: Path) -> None:
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError('Файл пуст или отсутствует')
    if fmt == 'txt':
        text = path.read_text(encoding='utf-8')
        if not text.strip():
            raise ValueError('Пустой TXT')
        return
    if fmt in ('docx', 'pptx', 'xlsx'):
        # OOXML must be a valid zip
        with zipfile.ZipFile(path, 'r') as zf:
            names = zf.namelist()
            if '[Content_Types].xml' not in names:
                raise ValueError(f'Повреждённый {fmt.upper()}')
            # Reject embedded macros / OLE
            for n in names:
                lower = n.lower()
                if lower.endswith('.bin') and 'vba' in lower:
                    raise ValueError('Макросы запрещены')
                if 'activex' in lower:
                    raise ValueError('ActiveX запрещён')
        return
    if fmt == 'pdf':
        data = path.read_bytes()[:8]
        if not data.startswith(b'%PDF'):
            raise ValueError('Некорректный PDF')
        # Extractable text check — basic
        raw = path.read_bytes()
        if b'/JavaScript' in raw or b'/JS' in raw:
            raise ValueError('PDF с JavaScript запрещён')
        return
    raise ValueError('Неизвестный формат')
