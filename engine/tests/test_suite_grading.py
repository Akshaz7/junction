from engine.tests.run_fix_suite import grade


def result(text,value=None):
    return {'answer':{'text_md':text,'value':value},'trace':[],'cost':{'calls':[]}}


def test_metric_text_fact_is_a_valid_numeric_answer():
    assert grade({'expected':'3.0 m'},result('The height is 3 m. [1]'))=='pass'
    assert grade({'expected':'3.0 m'},result('The height is 2 m. [3]'))=='fail'


def test_citation_numbers_cannot_satisfy_numeric_gold():
    assert grade({'expected':'3'},result('9 windows. [3]',9))=='fail'
    assert grade({'expected':'3'},result('9 windows. [3]'))=='fail'
