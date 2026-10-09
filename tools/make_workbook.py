"""Apply the four requested changes to the Popeyes Kitsilano callback log.

Usage: python tools/make_workbook.py <input.xlsx> <output.xlsx> <output.xlsm>
"""
import copy
import re
import sys
import zipfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.formatting.rule import Rule
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).parent))
from vbaproj import build_vba_project  # noqa: E402

SRC, OUT_XLSX, OUT_XLSM = (Path(p) for p in sys.argv[1:4])
HERE = Path(__file__).parent

FIRST_ROW = 6
LAST_COL = 12
STATUS_COL = 9
OLD_STATUS, NEW_STATUS = 'Picked Up', 'Completed'

# Status -> (row fill, text colour)
STATUS_COLOURS = {
    'Preordered':  ('E4DFEC', '5B2C6F'),
    'Ordered':     ('DDEBF7', '1F4E78'),
    'Notified':    ('FCE4D6', '843C0C'),
    'Completed':   ('C6EFCE', '006100'),
    'Transferred': ('FADBE7', '7B1E4B'),
    'Cancelled':   ('D9D9D9', '595959'),
}

AUTO_NOTE = ('Automatic: Date Logged fills in when a new row is started. '
             'Rows set to Completed move to the bottom. Row colour follows Status.')

# --- original dropdowns (openpyxl drops the x14 ones, so re-create them) ---
with zipfile.ZipFile(SRC) as z:
    rels = z.read('xl/_rels/workbook.xml.rels').decode()
    book = z.read('xl/workbook.xml').decode()
    sheet_files = {}
    for name, rid in re.findall(r'<sheet name="([^"]+)" sheetId="\d+"(?: state="\w+")? r:id="(rId\d+)"', book):
        target = re.search(rf'Id="{rid}"[^>]*Target="([^"]+)"', rels) or \
                 re.search(rf'Target="([^"]+)"[^>]*Id="{rid}"', rels)
        sheet_files[name] = 'xl/' + target.group(1)
    dropdowns = {}
    for name, path in sheet_files.items():
        xml = z.read(path).decode()
        dropdowns[name] = [
            dict(attrs=dict(re.findall(r'(\w+)="([^"]*)"', m.group(1))), formula=m.group(2), sqref=m.group(3))
            for m in re.finditer(r'<x14:dataValidation ([^>]*)><x14:formula1><xm:f>([^<]+)</xm:f></x14:formula1>'
                                 r'<xm:sqref>([^<]+)</xm:sqref>', xml)
        ]

wb = load_workbook(SRC)
lists = wb['Lists']
log_sheets = [ws for ws in wb.worksheets
              if ws['A5'].value == 'DATE LOGGED' and ws['I5'].value == 'STATUS']

# 1. "Picked Up" -> "Completed" in the dropdown list and in existing rows.
for row in lists.iter_rows(min_col=3, max_col=3):
    for c in row:
        if c.value == OLD_STATUS:
            c.value = NEW_STATUS
for ws in log_sheets:
    for row in ws.iter_rows(min_row=FIRST_ROW, min_col=STATUS_COL, max_col=STATUS_COL):
        for c in row:
            if isinstance(c.value, str) and c.value.strip() == OLD_STATUS:
                c.value = NEW_STATUS


def table_last_row(ws):
    status = next(d for d in dropdowns[ws.title] if d['formula'].startswith('Lists!$C'))
    return int(re.search(r'(\d+)$', status['sqref']).group(1))


def is_blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


# 3. Existing Completed rows go to the bottom of the table (same rule the macro uses).
for ws in log_sheets:
    last = table_last_row(ws)
    width = max(ws.max_column, LAST_COL)  # whole row, like the macro's cut/insert
    rows = []
    for r in range(FIRST_ROW, last + 1):
        cells = [ws.cell(r, c) for c in range(1, width + 1)]
        for c in cells:  # whitespace-only cells (e.g. a stray space) count as empty
            if isinstance(c.value, str) and not c.value.strip():
                c.value = None
        rows.append(dict(
            values=[c.value for c in cells],
            styles=[copy.copy(c._style) for c in cells],
            height=ws.row_dimensions[r].height,
        ))
    filled = [x for x in rows if not all(is_blank(v) for v in x['values'][:LAST_COL])]
    done = [x for x in filled if x['values'][STATUS_COL - 1] == NEW_STATUS]
    open_ = [x for x in filled if x['values'][STATUS_COL - 1] != NEW_STATUS]
    empty = [x for x in rows if all(is_blank(v) for v in x['values'][:LAST_COL])]
    ordered = open_ + empty + done
    if [id(x) for x in ordered] != [id(x) for x in rows]:
        for r, x in zip(range(FIRST_ROW, last + 1), ordered):
            for c in range(1, width + 1):
                cell = ws.cell(r, c)
                cell.value = x['values'][c - 1]
                cell._style = x['styles'][c - 1]
            ws.row_dimensions[r].height = x['height']
        print(f'{ws.title}: {len(open_)} open rows on top, {len(done)} completed rows moved to rows '
              f'{last - len(done) + 1}-{last}')

for ws in log_sheets:
    last = table_last_row(ws)
    # 2. Date Logged shows as a date (the macro fills it in).
    for r in range(FIRST_ROW, last + 1):
        ws.cell(r, 1).number_format = 'mmm d, yyyy'

    # 4. Colour-code rows by Status.
    area = f'A{FIRST_ROW}:L{last}'
    for status, (fill, font) in STATUS_COLOURS.items():
        style = DifferentialStyle(fill=PatternFill(bgColor=fill, fill_type='solid'), font=Font(color=font))
        ws.conditional_formatting.add(area, Rule(type='expression', dxf=style,
                                                 formula=[f'$I{FIRST_ROW}="{status}"']))

    # Dropdowns back exactly as they were.
    for d in dropdowns[ws.title]:
        a = d['attrs']
        ws.add_data_validation(DataValidation(
            type='list', formula1=d['formula'], allow_blank=a.get('allowBlank') == '1',
            showErrorMessage=a.get('showErrorMessage') == '1', showInputMessage=a.get('showInputMessage') == '1',
            errorTitle=a.get('errorTitle'), error=a.get('error'),
            promptTitle=a.get('promptTitle'), prompt=a.get('prompt'), sqref=d['sqref']))

    # Short note on what is automatic.
    ws['F4'] = AUTO_NOTE
    ws['F4'].font = Font(name='Arial', size=9, italic=True, color='595959')

sept = wb['SEPTEMBER']
sept['F3'] = sept['F3'].value.replace(' Row 6 is a sample row; delete it before use.', '')

# Code names so the macro's sheet modules line up with the tabs.
wb.code_name = 'ThisWorkbook'
modules = [('ThisWorkbook', 'workbook', (HERE.parent / 'macro' / 'ThisWorkbook.bas').read_text())]
for i, ws in enumerate(wb.worksheets, start=1):
    ws.sheet_properties.codeName = f'Sheet{i}'
    modules.append((f'Sheet{i}', 'sheet', ''))

wb.save(OUT_XLSX)

# --- macro-enabled copy -------------------------------------------------------
vba = build_vba_project(modules)
with zipfile.ZipFile(OUT_XLSX) as zin, zipfile.ZipFile(OUT_XLSM, 'w', zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == '[Content_Types].xml':
            text = data.decode()
            text = text.replace('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
                                'application/vnd.ms-excel.sheet.macroEnabled.main+xml')
            text = text.replace('<Default Extension="xml"',
                                '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
                                '<Default Extension="xml"', 1)
            assert 'macroEnabled.main' in text and 'vbaProject' in text
            data = text.encode()
        elif item.filename == 'xl/_rels/workbook.xml.rels':
            text = data.decode()
            text = text.replace('</Relationships>',
                                '<Relationship Id="rIdVBA1" '
                                'Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" '
                                'Target="vbaProject.bin"/></Relationships>')
            data = text.encode()
        zout.writestr(item, data)
    zout.writestr('xl/vbaProject.bin', vba)
print('wrote', OUT_XLSX, OUT_XLSM, f'(vbaProject.bin {len(vba)} bytes)')
