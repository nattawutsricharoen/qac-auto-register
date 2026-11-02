"""Read QAC View matrix with Python's standard library only.

Read-only evidence: output is not permission to write values back to QAC.
"""
from html.parser import HTMLParser


class _QACMatrixParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.modal_div_depth = 0
        self.tables = []
        self.table = None
        self.table_nesting = 0
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            if self.modal_div_depth:
                self.modal_div_depth += 1
            elif attrs.get('id') == 'modal-view-task':
                self.modal_div_depth = 1
        if not self.modal_div_depth:
            return
        if tag == 'table':
            if self.table is None:
                self.table = []
            self.table_nesting += 1
        elif tag == 'tr' and self.table is not None and self.row is None:
            self.row = []
        elif tag in ('td', 'th') and self.row is not None and self.cell is None:
            self.cell = []
        elif tag == 'br' and self.cell is not None:
            self.cell.append(' ')

    def handle_startendtag(self, tag, attrs):
        if tag == 'br' and self.cell is not None:
            self.cell.append(' ')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if not self.modal_div_depth:
            return
        if tag in ('th', 'td') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.table_nesting -= 1
            if self.table_nesting == 0:
                self.tables.append(self.table)
                self.table = None
        elif tag == 'div':
            self.modal_div_depth -= 1


def extract_view_matrix(html: str):
    parser = _QACMatrixParser()
    parser.feed(html)
    parser.close()
    matrices = []
    for table_index, rows in enumerate(parser.tables):
        if not rows or not rows[0] or rows[0][0].strip().lower() != 'inspection no.':
            continue
        headings = rows[0]
        labels = {row[0].strip().lower(): row for row in rows[1:] if row}
        items = labels.get('inspection items', [])
        values = []
        for row in rows[1:]:
            if not row or not row[0].strip().isdigit():
                continue
            slot = int(row[0].strip())
            for col in range(1, min(len(row), len(headings))):
                raw = row[col].strip()
                values.append({
                    'inspection_no': headings[col],
                    'inspection_item': items[col] if col < len(items) else '',
                    'slot': slot, 'raw_value': raw,
                    'has_result': raw not in ('', '-'),
                    'result_type': 'OK_NG' if raw.upper() in ('OK', 'NG') else ('OTHER' if raw not in ('', '-') else 'EMPTY'),
                })
        matrices.append({'table_index': table_index, 'inspection_count': len(headings)-1,
                         'values': values, 'row_count': len(rows)})
    return matrices
