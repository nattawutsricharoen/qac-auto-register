from app.daily_reference_table import extract_view_matrix

def test_view_matrix():
    html='''<div id="modal-view-task"><table><tr><td>Inspection No.</td><td>2-1</td><td>2-2</td></tr>
    <tr><td>Inspection Items</td><td>Test A</td><td>Test B</td></tr>
    <tr><td>1</td><td>OK</td><td>-</td></tr><tr><td>2</td><td>NG</td><td>12.5</td></tr></table></div>'''
    v=extract_view_matrix(html)
    assert v[0]['inspection_count']==2
    assert [(x['inspection_no'],x['slot'],x['raw_value'],x['has_result']) for x in v[0]['values']] == [('2-1',1,'OK',True),('2-2',1,'-',False),('2-1',2,'NG',True),('2-2',2,'12.5',True)]

def test_no_modal():
    assert extract_view_matrix('<table><tr><td>Inspection No.</td></tr></table>')==[]


def test_stdlib_only_nested_markup():
    html = '''<html><input><div id="modal-view-task"><div><table>
      <tr><td>Inspection No.</td><td><span>2-1</span></td></tr>
      <tr><td>Inspection Items</td><td>Cleaning <b>check</b></td></tr>
      <tr><td>1</td><td><span>OK</span></td></tr></table></div></div></html>'''
    matrix = extract_view_matrix(html)
    assert matrix[0]['values'][0]['inspection_item'] == 'Cleaning check'
    assert matrix[0]['values'][0]['raw_value'] == 'OK'
