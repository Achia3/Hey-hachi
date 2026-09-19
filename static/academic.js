(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let selected = null, record = null, lastVersion = '', busy = false;
  const active = new Set(['queued', 'running']);
  const names = {queued:'Queued', running:'Generating', completed:'Saved · review ready', failed:'Needs attention', cancelled:'Cancelled', interrupted:'Interrupted'};
  function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
  function show(id, yes) { $(id).hidden = !yes; }
  async function api(path, options = {}) { const response = await fetch('/api/academic' + path, options); const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data; }
  function post(path, body) { return api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}); }
  function announce(text) { $('workspace-message').textContent = text; }
  function date(value) { return new Date(value).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}); }
  function remember(key, value) { try { localStorage.setItem(key, value); } catch (_) {} }
  function recalled(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function theme(value) { document.documentElement.dataset.theme = value; $('theme').textContent = value === 'dark' ? 'Light mode' : 'Dark mode'; remember('hachi-academic-theme', value); }
  theme(recalled('hachi-academic-theme') || 'light');
  $('theme').addEventListener('click', () => theme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

  async function models() {
    $('refresh-models').disabled = true;
    try {
      const data = await api('/models'); const old = $('model').value;
      $('connection').textContent = data.available ? 'Ollama connected · local generation' : data.message;
      if (data.models.length) {
        $('model').replaceChildren(...data.models.map(name => {const option = el('option', name); option.value = name; return option;}));
        $('model').value = data.models.includes(old) ? old : data.models.includes('hachi-master:latest') ? 'hachi-master:latest' : data.models[0];
      }
    } catch (error) { $('connection').textContent = 'Could not check Ollama. Use Refresh to retry.'; }
    finally { $('refresh-models').disabled = false; }
  }
  $('refresh-models').addEventListener('click', models);
  function fill(inputs) {
    $('course-code').value = inputs.course_code; $('course-title').value = inputs.course_title;
    $('course-description').value = inputs.course_description; $('target-pos').value = inputs.target_pos.join(', ');
    $('po-descriptions').value = Object.entries(inputs.po_descriptions || {}).map(([n,t]) => n + ': ' + t).join('\n');
    if (inputs.model) { if (![...$('model').options].some(o => o.value === inputs.model)) $('model').append(el('option', inputs.model)); $('model').value = inputs.model; }
    if (inputs.grading) for (const [id,key] of [['quizzes','quizzes_weight'],['research','research_weight'],['labs','lab_weight'],['standing','class_standing_weight'],['exam','major_exam_weight']]) $(id).value = Math.round(inputs.grading[key] * 1000) / 10;
    $('attempts').value = inputs.max_retries || 3;
    $('course-code').focus();
  }
  function example() { fill({course_code:'CS201', course_title:'Data Structures and Algorithms', course_description:'Analysis and implementation of abstract data types, sorting, searching, trees, graphs, and algorithmic problem solving through hands-on programming labs.', target_pos:[1,2,3]}); }
  $('example').addEventListener('click', example); $('empty-example').addEventListener('click', example);
  function values() {
    const parts = $('target-pos').value.trim().split(/[\s,]+/);
    if (!parts.length || parts.some(x => !/^\d+$/.test(x))) throw new Error('Use PO numbers separated by commas, for example 1, 2, 3.');
    const descriptions = {};
    for (const line of $('po-descriptions').value.split('\n').filter(x => x.trim())) {
      const match = line.match(/^\s*(\d+)\s*:\s*(.+)$/);
      if (!match) throw new Error('Write PO descriptions as number: description, one per line.');
      if (descriptions[match[1]]) throw new Error('Each PO description should appear once.');
      descriptions[match[1]] = match[2].trim();
    }
    const grading = {};
    for (const [id,key] of [['quizzes','quizzes_weight'],['research','research_weight'],['labs','lab_weight'],['standing','class_standing_weight'],['exam','major_exam_weight']]) grading[key] = Number($(id).value) / 100;
    return {course_code:$('course-code').value.trim(), course_title:$('course-title').value.trim(), course_description:$('course-description').value.trim(), target_pos:parts.map(Number), po_descriptions:descriptions, model:$('model').value, grading, max_retries:Number($('attempts').value)};
  }
  $('course-form').addEventListener('submit', async event => {
    event.preventDefault(); show('form-error', false); $('generate').disabled = true;
    try { const created = await post('/runs', values()); selected = created.id; lastVersion = ''; remember('hachi-academic-selected', selected); announce('New generation saved to the queue.'); await refresh(); }
    catch (error) { $('form-error').textContent = error.message; show('form-error', true); }
    finally { $('generate').disabled = false; }
  });
  function history(runs) {
    $('run-count').textContent = runs.length; show('history-empty', !runs.length);
    const focused = document.activeElement?.dataset?.run;
    $('history').replaceChildren(...runs.map(r => {
      const b = el('button', undefined, 'history-item'); b.type = 'button'; b.dataset.run = r.id; b.setAttribute('aria-current', String(r.id === selected));
      b.append(el('span', r.inputs.course_title, 'history-title'));
      const meta = el('span', undefined, 'history-meta'); meta.append(el('span', date(r.created_at)), el('span', names[r.status] || r.status));
      b.append(meta, el('span', r.inputs.course_code + ' · ' + r.id.slice(0,8), 'history-code'));
      b.addEventListener('click', async () => { selected = r.id; lastVersion = ''; remember('hachi-academic-selected', selected); await refresh(); }); return b;
    }));
    if (focused) [...$('history').children].find(n => n.dataset.run === focused)?.focus({preventScroll:true});
  }
  function render(r) {
    record = r; show('empty-view', false); show('run-view', true);
    $('run-status').textContent = names[r.status] || r.status; $('run-status').dataset.status = r.status;
    $('run-reference').textContent = r.id.slice(0,8) + ' · ' + date(r.created_at);
    $('document-code').textContent = r.inputs.course_code + ' · Target POs ' + r.inputs.target_pos.join(', ');
    $('document-title').textContent = r.inputs.course_title; $('document-description').textContent = r.inputs.course_description;
    $('progress-message').textContent = r.message;
    $('progress-detail').textContent = active.has(r.status) ? (r.characters ? r.characters.toLocaleString() + ' characters received' : 'Local model · thinking disabled') : (r.elapsed_seconds ? r.elapsed_seconds + ' seconds · ' : '') + r.inputs.model;
    for (const [id,stage] of [['step-outcomes','outcomes'],['step-schedule','schedule'],['step-save','complete']]) { $(id).dataset.active = String(r.stage === stage); $(id).dataset.done = String(stage === 'outcomes' ? !!r.outcomes : !!r.syllabus); }
    const failed = ['failed','interrupted'].includes(r.status); show('run-error', failed); $('run-error').textContent = failed ? r.message : '';
    show('cancel', active.has(r.status)); show('export-co', !!r.outcomes); show('export', !!r.syllabus);
    show('continue', !!r.outcomes && !r.syllabus && !active.has(r.status));
    show('result-tabs', !!r.outcomes); show('outcomes-section', !!r.outcomes); show('schedule-section', !!r.syllabus); show('grading-section', !!r.syllabus); show('review-note', !!r.outcomes);
    $('review-note').textContent = (r.syllabus ? 'Syllabus structural checks passed. ' : 'Course outcome checks passed. ') + 'Review topic depth, assessment quality, and PO alignment before submission. PO numbers alone do not establish alignment with official PO descriptions.';
    if (!r.outcomes) { tab(false); $('json-output').textContent = ''; }
    if (r.outcomes) {
      $('outcome-count').textContent = r.outcomes.course_outcomes.length + ' outcomes';
      $('outcomes').replaceChildren(...r.outcomes.course_outcomes.map(co => {
        const item = el('div', undefined, 'outcome'), body = el('div');
        item.append(el('span', 'CO ' + co.clo_number, 'co-number'));
        body.append(el('p', co.co_description || co.description));
        const meta = el('div', undefined, 'outcome-meta'); meta.append(el('span', co.bloom_level), el('span', 'PO ' + (co.mapped_po || co.mapped_plos).join(', '))); body.append(meta); item.append(body); return item;
      }));
      $('json-output').textContent = JSON.stringify(r.syllabus || r.outcomes, null, 2);
    }
    if (r.syllabus) renderSyllabus(r.syllabus);
  }
  function renderSyllabus(s) {
    $('schedule').replaceChildren(...s.weekly_schedule.map(w => {
      const week = el('details', undefined, 'week' + ([7,14].includes(w.week_number) ? ' exam' : ''));
      const summary = el('summary'), title = el('span', (w.topic || w.topics).join(' · '), 'week-topic');
      title.append(el('small', w.period + ' · CO ' + w.aligned_co)); summary.append(el('span', 'W' + String(w.week_number).padStart(2,'0'), 'week-number'), title);
      const content = el('div', undefined, 'week-content'), dl = el('dl');
      for (const [label,text] of [['Activity', w.teaching_learning_activity || w.tla_activity],['Assessment',w.assessment_tool],['Evidence',w.evidence]]) dl.append(el('dt',label), el('dd',text));
      const llos = el('ul'); for (const llo of w.llos) llos.append(el('li', llo.category + ' · ' + llo.outcome_text)); content.append(dl,llos); week.append(summary,content); return week;
    }));
    const g = s.grading_breakdown, p = n => Math.round(n*1000)/10 + '%';
    const formula = el('div', undefined, 'grading-formula'); formula.append(el('strong', p(g.class_standing_weight)), document.createTextNode(' class standing + '), el('strong',p(g.major_exam_weight)), document.createTextNode(' major exam'));
    const split = el('p', 'Within class standing: quizzes ' + p(g.quizzes_weight) + ' · research ' + p(g.research_weight) + ' · labs ' + p(g.lab_weight), 'field-help');
    $('grading').replaceChildren(formula, split);
    const table = el('table'), head = el('thead'), hr = el('tr'); for (const label of ['CO','Weeks','Assessment tasks']) hr.append(el('th',label)); head.append(hr); const body = el('tbody');
    for (const co of s.course_outcomes) { const weeks = s.weekly_schedule.filter(w => w.aligned_co === co.clo_number); const row = el('tr'); row.append(el('td','CO '+co.clo_number),el('td',weeks.map(w => w.week_number).join(', ')),el('td',[...new Set(weeks.map(w => w.assessment_tool))].join(' · '))); body.append(row); }
    table.append(head,body); $('assessment-matrix').replaceChildren(table);
  }
  function tab(json) { $('preview-tab').setAttribute('aria-selected', String(!json)); $('json-tab').setAttribute('aria-selected', String(json)); show('preview-panel', !json); show('json-panel', json); }
  $('preview-tab').addEventListener('click', () => tab(false)); $('json-tab').addEventListener('click', () => tab(true));
  $('reuse').addEventListener('click', () => { if (record) { fill(record.inputs); announce('Inputs copied. Generate syllabus will create a separate saved run.'); } });
  $('cancel').addEventListener('click', async () => { if (!record) return; $('cancel').disabled = true; try { await post('/runs/'+record.id+'/cancel', {}); await refresh(); } catch(e) { announce(e.message); } finally { $('cancel').disabled=false; } });
  $('continue').addEventListener('click', async () => { if (!record) return; $('continue').disabled=true; try { const r = await post('/runs', {source_run_id:record.id}); selected=r.id; lastVersion=''; remember('hachi-academic-selected',selected); await refresh(); } catch(e) { announce(e.message); } finally { $('continue').disabled=false; } });
  async function download(kind) { if (!record) return; try { if (window.pywebview?.api?.save_academic_json) { const result = await window.pywebview.api.save_academic_json(record.id,kind); if (result.error) throw new Error(result.error); if (result.saved) announce('JSON exported.'); } else { const link = el('a'); link.href = '/api/academic/runs/'+record.id+'/download?kind='+kind; link.download = kind+'-'+record.id.slice(0,8)+'.json'; document.body.append(link); link.click(); link.remove(); } } catch(e) { announce(e.message); } }
  $('export').addEventListener('click', () => download('syllabus')); $('export-co').addEventListener('click', () => download('outcomes'));
  async function refresh() {
    if (busy) return; busy=true;
    try { const data = await api('/runs'); if (!selected || !data.runs.some(r => r.id === selected)) selected=data.runs[0]?.id || null; history(data.runs); if (selected) { const id=selected; const detail=await api('/runs/'+id); if (selected===id && lastVersion!==id+detail.updated_at) { lastVersion=id+detail.updated_at; render(detail); } } if ($('workspace-message').textContent.startsWith('Could not refresh saved runs:')) announce(''); }
    catch(e) { announce('Could not refresh saved runs: '+e.message); }
    finally { busy=false; }
  }
  selected=recalled('hachi-academic-selected');
  models(); refresh();
  setInterval(refresh, 2000);
})();
