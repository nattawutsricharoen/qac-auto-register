import tempfile
from pathlib import Path
from app.daily_scan_checkpoint import DailyScanCheckpoint, verified_reference_values
from app.learning_corrections import CorrectionLearning

def test_exact_reference_checkpoint_and_numeric_precision():
    with tempfile.TemporaryDirectory() as temp:
        db=DailyScanCheckpoint(Path(temp)/'scan.sqlite')
        doc={'line':'TS1-Sub','model':'S91','document_name':'TS1-Sub_All Model_Machine condition check','document_no':'FOPI-M09-TS1-001-005-06'}
        items=[{'item':'438202','format':'1','slots':[{'number':1,'saved':True,'status':'SAVED','value':'0.5530'}]},
               {'item':'438208','format':'1','slots':[{'number':1,'saved':True,'status':'SAVED','value':'-36.8'}]},
               {'item':'438209','format':'1','slots':[{'number':1,'saved':False,'status':'UNKNOWN','value':'123'}]}]
        db.save('REFERENCE',doc,'2026-10-20','1329322',items)
        resumed=DailyScanCheckpoint(Path(temp)/'scan.sqlite').load('REFERENCE',doc,'2026-10-20','1329322')
        values=verified_reference_values(resumed['items'])
        assert values[('438202',1)]['value']=='0.5530'
        assert values[('438208',1)]['value']=='-36.8'
        assert ('438209',1) not in values
        assert db.load('REFERENCE',doc,'2026-10-20','1330240') is None
        assert db.load('REFERENCE',{**doc,'line':'TS2-Sub'},'2026-10-20','1329322') is None
        assert db.load('REFERENCE',doc,'2026-10-19','1329322') is None

def test_corrections_require_confirmation_and_never_cross_line_model():
    with tempfile.TemporaryDirectory() as temp:
        db=CorrectionLearning(Path(temp)/'learning.sqlite')
        db.record_confirmation('OCR_NG','TS1-Sub','S91','model','S9I','S91')
        assert db.suggestions('OCR_NG','TS1-Sub','S91','model','S9I')==[{'value':'S91','confirmations':1,'approved':False}]
        assert db.suggestions('OCR_NG','TS2-Sub','S91','model','S9I')==[]
        assert db.suggestions('OCR_NG','TS1-Sub','S92','model','S9I')==[]
        db.set_approved('OCR_NG','TS1-Sub','S91','model','S9I','S91',True)
        assert db.suggestions('OCR_NG','TS1-Sub','S91','model','S9I')[0]['approved']
