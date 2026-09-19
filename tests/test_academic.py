"""Academic Studio contracts, recovery, API isolation and streamed JSON handling."""
import copy
import json
from pathlib import Path
import threading
import time

from flask import Flask
import pytest
from pydantic import ValidationError

from hachi_academic import AcademicService, create_academic_blueprint
from LAB_3.obe_schemas import CourseOutcomeSchema, OBESyllabusPayload, GradingBreakdown
from LAB_3.lab1_1_generator import default_ollama_caller, generate_course_outcomes
from LAB_3.lab1_2_pipeline import generate_syllabus_pipeline

SAMPLE = Path(__file__).resolve().parents[3] / "LAB_3/sample_output_syllabus.json"


@pytest.fixture
def syllabus():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def inputs(title="Data Structures and Algorithms"):
    return dict(course_code="CS201", course_title=title, course_description="Hands-on data structures and algorithm analysis.", target_pos=[1,2,3,4,5])


def wait_done(service, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.get(run_id)
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(.01)
    pytest.fail("Test worker did not finish")


def fake_caller(syllabus):
    def call(messages, model, mode):
        assert mode is True
        if "weekly_schedule" in messages[0]["content"]:
            return json.dumps({"weekly_schedule": syllabus["weekly_schedule"]})
        return json.dumps({"course_outcomes": syllabus["course_outcomes"]})
    return call


def test_two_runs_are_independent_and_survive_restart(tmp_path, syllabus):
    service = AcademicService(tmp_path, fake_caller(syllabus))
    try:
        a = service.start(inputs("First syllabus")); b = service.start(inputs("Second syllabus"))
        first, second = wait_done(service,a["id"]), wait_done(service,b["id"])
        assert first["status"] == second["status"] == "completed"
        assert first["id"] != second["id"]
        assert first["syllabus"]["course_title"] == "First syllabus"
        assert second["syllabus"]["course_title"] == "Second syllabus"
        assert len(list(tmp_path.glob("*.json"))) == 2
        OBESyllabusPayload.model_validate_json(service.export(a["id"]))
        assert "co_description" in first["outcomes"]["course_outcomes"][0]
        restarted = AcademicService(tmp_path)
        assert len(restarted.list()) == 2
        assert restarted.get(a["id"])["syllabus"] == first["syllabus"]
        restarted.close()
    finally:
        service.close()


def test_failed_schedule_preserves_outcomes_and_can_continue(tmp_path, syllabus):
    def broken(messages, model, mode):
        return '[]' if "weekly_schedule" in messages[0]["content"] else json.dumps({"course_outcomes": syllabus["course_outcomes"]})
    service = AcademicService(tmp_path, broken)
    try:
        first = wait_done(service, service.start({**inputs(), "max_retries":1})["id"])
        assert first["status"] == "failed" and first["outcomes"] and first["syllabus"] is None
        CourseOutcomeSchema.model_validate_json(service.export(first["id"], "outcomes"))
        service.caller = fake_caller(syllabus)
        second = wait_done(service, service.start({}, first["id"])["id"])
        assert second["status"] == "completed" and second["id"] != first["id"]
        assert [e["stage"] for e in second["events"]] == ["schedule"]
        assert service.get(first["id"])["status"] == "failed"
    finally:
        service.close()


def test_restart_marks_unfinished_run_and_keeps_validated_data(tmp_path, syllabus):
    run_id = 'a' * 32
    (tmp_path / (run_id+'.json')).write_text(json.dumps({"id":run_id,"status":"running","outcomes":syllabus["course_outcomes"]}))
    service=AcademicService(tmp_path)
    assert service.get(run_id)["status"] == "interrupted"
    assert service.get(run_id)["outcomes"] == syllabus["course_outcomes"]
    service.close()


def test_api_validates_inputs_and_exports_exact_selected_run(tmp_path, syllabus):
    service=AcademicService(tmp_path, fake_caller(syllabus))
    app=Flask(__name__); app.register_blueprint(create_academic_blueprint(service)); client=app.test_client()
    try:
        assert client.post('/api/academic/runs', json=[]).status_code==400
        assert client.post('/api/academic/runs', json={**inputs(),"target_pos":[1,1]}).status_code==400
        assert client.post('/api/academic/runs', json={**inputs(),"grading":{"quizzes_weight":.9}}).status_code==400
        response=client.post('/api/academic/runs',json=inputs())
        assert response.status_code==202
        run_id=response.json['id']; wait_done(service,run_id)
        downloaded=client.get('/api/academic/runs/'+run_id+'/download')
        assert downloaded.status_code==200 and 'attachment' in downloaded.headers['Content-Disposition']
        OBESyllabusPayload.model_validate_json(downloaded.data)
        assert client.get('/api/academic/runs/no-such-file/download').status_code==404
        assert client.get('/api/academic/runs/'+run_id+'/download?kind=inputs').status_code==404
    finally:
        service.close()


def test_queued_cancellation_never_calls_model(tmp_path, syllabus):
    entered, release=threading.Event(),threading.Event()
    def blocking(messages, model, mode):
        entered.set(); assert release.wait(4)
        return fake_caller(syllabus)(messages,model,mode)
    service=AcademicService(tmp_path,blocking)
    try:
        a=service.start(inputs()); assert entered.wait(2)
        b=service.start(inputs()); service.cancel(b['id']); release.set()
        assert wait_done(service,a['id'])['status']=='completed'
        assert wait_done(service,b['id'])['status']=='cancelled'
        assert service.get(b['id'])['events']==[]
    finally:
        release.set(); service.close()


@pytest.mark.parametrize('change', ['duplicate_week','unknown_co','duplicate_co','outside_po','wrong_bloom','missing_ksa','no_lab'])
def test_schema_rejects_structural_misalignment(syllabus, change):
    s=copy.deepcopy(syllabus)
    if change=='duplicate_week': s['weekly_schedule'][1]['week_number']=1
    elif change=='unknown_co': s['weekly_schedule'][0]['aligned_co']=5
    elif change=='duplicate_co': s['course_outcomes'][1]['clo_number']=1
    elif change=='outside_po': s['course_outcomes'][0]['mapped_plos']=[999]
    elif change=='wrong_bloom': s['course_outcomes'][0]['bloom_level']='Level 5-6 (Evaluate/Create)'
    elif change=='missing_ksa': s['weekly_schedule'][0]['llos']=s['weekly_schedule'][0]['llos'][:1]
    elif change=='no_lab': s['weekly_schedule'][0]['tla_activity']='Listen to a lecture'
    with pytest.raises(ValidationError): OBESyllabusPayload.model_validate(s)


@pytest.mark.parametrize('value',[-.1,2,float('nan'),float('inf')])
def test_grading_invalid_weights(value):
    with pytest.raises(ValidationError): GradingBreakdown(quizzes_weight=value)


@pytest.mark.parametrize('bad', ['[]','null','42','{"course_outcomes": []}'])
def test_bad_json_shapes_trigger_corrective_retry(syllabus,bad):
    calls=[]
    def caller(messages,model,mode):
        calls.append(copy.deepcopy(messages))
        return bad if len(calls)==1 else json.dumps({'course_outcomes':syllabus['course_outcomes']})
    result=generate_course_outcomes(**inputs(),llm_caller=caller)
    assert len(result.course_outcomes)==4 and len(calls)==2
    assert calls[1][-1]['role']=='user'


def test_pipeline_accepts_array_and_retries_scalar(syllabus):
    co=CourseOutcomeSchema.model_validate({k:v for k,v in syllabus.items() if k not in {'weekly_schedule','grading_breakdown'}})
    results=iter(['null',json.dumps(syllabus['weekly_schedule'])])
    assert len(generate_syllabus_pipeline(co,llm_caller=lambda *_:next(results)).weekly_schedule)==14


def test_streamed_json_uses_json_mode_and_disables_thinking(monkeypatch):
    seen={}
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def raise_for_status(self): pass
        def iter_lines(self):
            for chunk in [{'message':{'content':'{"a":'}},{'message':{'content':'1}'},'done':True,'done_reason':'stop'}]: yield json.dumps(chunk).encode()
    def post(*args,**kwargs): seen.update(kwargs); return Response()
    monkeypatch.setattr('LAB_3.lab1_1_generator.requests.post',post)
    assert default_ollama_caller([])=='{"a":1}'
    assert seen['json']['format']=='json' and seen['json']['think'] is False and seen['stream'] is True


@pytest.mark.parametrize('ending', ['disconnected', 'length', 'cancelled'])
def test_stream_never_accepts_incomplete_or_cancelled_output(monkeypatch, ending):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_lines(self):
            yield b'{"message":{"content":"{}"}}'
            if ending == 'length':
                yield b'{"done":true,"done_reason":"length"}'
    monkeypatch.setattr('LAB_3.lab1_1_generator.requests.post', lambda *a, **k: Response())
    expected = InterruptedError if ending == 'cancelled' else ValueError if ending == 'length' else RuntimeError
    with pytest.raises(expected):
        default_ollama_caller([], cancelled=lambda: ending == 'cancelled')


def test_cli_stdout_is_only_validated_json(monkeypatch, capsys, syllabus):
    from LAB_3 import lab1_1_generator as cli
    co = CourseOutcomeSchema.model_validate({k:v for k,v in syllabus.items() if k not in {'weekly_schedule','grading_breakdown'}})
    monkeypatch.setattr(cli, 'generate_course_outcomes', lambda **kwargs: co)
    monkeypatch.setattr('sys.argv', ['obe_json_generator.py'])
    cli.main()
    CourseOutcomeSchema.model_validate_json(capsys.readouterr().out)


def test_desktop_academic_window_reuse_and_export(tmp_path):
    # Load only the native bridge, avoiding the assistant's microphone/model startup.
    import ast
    from types import SimpleNamespace
    source = Path(__file__).resolve().parents[1] / 'hachi_app.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    bridge = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DesktopApi')
    class Closed:
        def is_set(self): return False
        def __iadd__(self, callback): self.callback = callback; return self
    target = tmp_path / 'export.json'
    window = SimpleNamespace(events=SimpleNamespace(closed=Closed()), restore=lambda: None,
                             show=lambda: None, create_file_dialog=lambda *a, **k: (str(target),))
    created = []
    def create_window(**kwargs): created.append(kwargs); return window
    ns = {'threading':threading, 'FLASK_PORT':5000,
          'webview':SimpleNamespace(create_window=create_window, FileDialog=SimpleNamespace(SAVE=1)),
          'app':SimpleNamespace(extensions={'academic_service':SimpleNamespace(export=lambda *a:'{"validated":true}')})}
    exec(compile(ast.Module(body=[bridge], type_ignores=[]), str(source), 'exec'), ns)
    api = ns['DesktopApi']()
    assert api.open_academic() == {'opened':True, 'reused':False}
    assert api.open_academic() == {'opened':True, 'reused':True}
    assert len(created) == 1 and created[0]['url'].endswith('/academic')
    assert api.save_academic_json('a'*32) == {'saved':True}
    assert json.loads(target.read_text()) == {'validated':True}
    window.create_file_dialog = lambda *a, **k: None
    assert api.save_academic_json('a'*32) == {'saved':False, 'cancelled':True}
    window.events.closed.callback()
    assert api._academic_window is None


def test_import_bridge_does_not_recover_another_process_run(tmp_path):
    from hachi_academic import LazyAcademicService
    path = tmp_path / 'untouched'
    service = LazyAcademicService(path)
    app = Flask(__name__)
    app.register_blueprint(create_academic_blueprint(service))
    assert not path.exists()
    assert app.test_client().get('/api/academic/runs').status_code == 200
    assert path.exists()
    service.close()


def test_pipeline_cli_handles_invalid_input_without_traceback(tmp_path, monkeypatch, capsys):
    from LAB_3 import lab1_2_pipeline as cli
    source = tmp_path / 'invalid.json'
    source.write_text('null')
    monkeypatch.setattr('sys.argv', ['lab1_2_pipeline.py', '--input', str(source)])
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == '' and '[ERROR]' in captured.err and 'Traceback' not in captured.err


def test_prompt_examples_are_valid_json():
    from LAB_3.lab1_1_generator import SYSTEM_PROMPT_OBE_COMPLIANT
    from LAB_3.lab1_2_pipeline import SYSTEM_PROMPT_14_WEEK_SCHEDULE
    for prompt in [SYSTEM_PROMPT_OBE_COMPLIANT, SYSTEM_PROMPT_14_WEEK_SCHEDULE]:
        example = prompt[prompt.index('{'):prompt.rindex('}')+1]
        assert isinstance(json.loads(example), dict)


def test_pipeline_repairs_only_invalid_weeks_and_revalidates_full_result(syllabus):
    co = CourseOutcomeSchema.model_validate({k:v for k,v in syllabus.items() if k not in {'weekly_schedule','grading_breakdown'}})
    bad = copy.deepcopy(syllabus['weekly_schedule'])
    bad[6]['llos'] = []
    bad[8]['llos'][0]['outcome_text'] = 'Understand the shortest path algorithm'
    calls = []
    def caller(messages, *args):
        calls.append(copy.deepcopy(messages))
        return json.dumps({'weekly_schedule':bad if len(calls)==1 else [syllabus['weekly_schedule'][6],syllabus['weekly_schedule'][8]]})
    result = generate_syllabus_pipeline(co, llm_caller=caller)
    assert len(result.weekly_schedule) == 14
    assert 'ONLY weeks [7, 9]' in calls[1][0]['content']
    assert result.weekly_schedule[0].model_dump() == syllabus['weekly_schedule'][0]


def test_pipeline_does_not_accept_wrong_partial_repairs(syllabus):
    co = CourseOutcomeSchema.model_validate({k:v for k,v in syllabus.items() if k not in {'weekly_schedule','grading_breakdown'}})
    bad = copy.deepcopy(syllabus['weekly_schedule']); bad[6]['llos'] = []
    responses = iter([{'weekly_schedule':bad}, {'weekly_schedule':[syllabus['weekly_schedule'][0]]}])
    with pytest.raises(RuntimeError, match='replacement weeks'):
        generate_syllabus_pipeline(co, max_retries=2, llm_caller=lambda *_:json.dumps(next(responses)))


def test_saved_draft_is_validated_and_repair_uses_bounded_json_schema(syllabus):
    co = CourseOutcomeSchema.model_validate({k:v for k,v in syllabus.items() if k not in {'weekly_schedule','grading_breakdown'}})
    draft = copy.deepcopy(syllabus['weekly_schedule']); draft[12]['tla_activity'] = 'Listen to presentations'
    calls = []
    def caller(messages, model, response_format):
        calls.append(response_format)
        return json.dumps({'weekly_schedule':[syllabus['weekly_schedule'][12]]})
    result = generate_syllabus_pipeline(co, initial_response=json.dumps({'weekly_schedule':draft}), llm_caller=caller)
    assert len(result.weekly_schedule) == 14 and len(calls) == 1
    spec = calls[0]['properties']['weekly_schedule']
    assert spec['minItems'] == spec['maxItems'] == 1
    assert spec['items']['properties']['week_number']['enum'] == [13]


def test_extra_midterm_is_rejected_outside_exam_week(syllabus):
    bad = copy.deepcopy(syllabus)
    bad['weekly_schedule'][10]['topics'] = ['Midterm Examination']
    with pytest.raises(ValidationError, match='only in weeks 7 and 14'):
        OBESyllabusPayload.model_validate(bad)


def test_old_invalid_completed_record_is_preserved_as_repairable_draft(tmp_path, syllabus):
    service = AcademicService(tmp_path, fake_caller(syllabus))
    try:
        run = service.start(inputs())
        done = wait_done(service, run['id'])
        done['syllabus']['weekly_schedule'][10]['topic'] = ['Midterm Examination']
        service._save(done)
        with pytest.raises(ValidationError):
            service.export(run['id'])
    finally:
        service.close()
    reloaded = AcademicService(tmp_path)
    try:
        old = reloaded.get(run['id'])
        assert old['status'] == 'failed' and old['syllabus'] is None
        assert old['previous_syllabus'] and old['outcomes'] and old['schedule_draft']
    finally:
        reloaded.close()
