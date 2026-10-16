const API='/api/v1';
const state={token:localStorage.getItem('gd_token'),user:null,projects:[],project:null,candidates:[],kpis:null};
const qs=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
async function api(path,opt={}){const h={...(opt.headers||{})};if(state.token)h.Authorization=`Bearer ${state.token}`;if(opt.body&&!(opt.body instanceof FormData))h['Content-Type']='application/json';const r=await fetch(API+path,{...opt,headers:h});if(!r.ok){let d='Request failed';try{d=(await r.json()).detail||d}catch{}throw Error(typeof d==='string'?d:JSON.stringify(d))}return r.headers.get('content-type')?.includes('json')?r.json():r}
function badge(v){return `<span class="status-badge ${String(v).toLowerCase().replaceAll('_','-')}">${esc(String(v).replaceAll('_',' '))}</span>`}
function pct(v){return `${Number(v||0).toFixed(1)}%`}
async function login(e){e.preventDefault();try{const r=await api('/auth/login',{method:'POST',body:JSON.stringify({email:qs('#email').value,password:qs('#password').value})});state.token=r.access_token;state.user=r.user;localStorage.setItem('gd_token',state.token);await start()}catch(err){qs('#loginError').innerHTML=`<div class="alert error">${esc(err.message)}</div>`}}
async function start(){if(!state.token)return;try{state.user=state.user||await api('/auth/me');state.projects=await api('/projects');state.project=state.projects[0]||null;qs('#loginView').classList.add('hidden');qs('#appView').classList.remove('hidden');qs('#userName').textContent=state.user.full_name;qs('#userRole').textContent=state.user.role.replaceAll('_',' ');renderProjectSelect();route()}catch{logout()}}
function logout(){localStorage.removeItem('gd_token');state.token=null;location.reload()}
function renderProjectSelect(){qs('#projectSelect').innerHTML=state.projects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');if(state.project)qs('#projectSelect').value=state.project.id}
async function loadData(){if(!state.project)return;const [k,c]=await Promise.all([api(`/dashboard/${state.project.id}`),api(`/candidates?project_id=${state.project.id}&page_size=200`)]);state.kpis=k;state.candidates=c.items}
function metric(l,v,s,a=''){return `<div class="metric-card ${a}"><div class="metric-head"><span>${l}</span><span>◫</span></div><strong>${v}</strong><small>${s}</small></div>`}
function bars(title,items){const max=Math.max(1,...items.map(x=>x.count));return `<div class="panel"><div class="panel-title"><h3>${title}</h3></div><div class="bars">${items.map(i=>`<div class="bar-row"><span>${esc(String(i.name).replace('GoogleStatus.','').replace('QualityTier.','').replaceAll('_',' '))}</span><div><i style="width:${i.count/max*100}%"></i></div><b>${i.count}</b></div>`).join('')}</div></div>`}
async function legacyDashboard(){await loadData();const k=state.kpis;qs('#content').innerHTML=`<div class="demo-banner"><span>✓</span><div><strong>Seeded Demonstration Data</strong><span>Stable seeded data · clearly labelled · no live-source claims</span></div></div><div class="hero-panel"><div><p class="eyebrow">INCREMENTAL DISCOVERY</p><h2>${pct(k.incremental_usable_ratio)} usable coverage beyond Google</h2><p>D/A measures verified, customer-usable POIs absent from the Google baseline.</p></div><div class="hero-score"><strong>${k.D_usable_non_google}</strong><span>usable non-Google POIs</span></div></div><div class="metrics-grid">${metric('A · Total POIs',k.A_total,'Explicit B + C + I')}${metric('B · Google Present',k.B_google_present,`${pct(k.google_coverage_ratio)} baseline coverage`)}${metric('C · Google Absent',k.C_google_absent_verified,`${pct(k.verified_gap_ratio)} verified gaps`)}${metric('D · Usable Non-Google',k.D_usable_non_google,`${pct(k.usability_rate_of_gaps)} gap usability`,'accent')}${metric('I · Pending / Inconclusive',k.I_inconclusive_or_pending,'Excluded from C and D')}${metric('Gold on D',pct(k.gold_quality_ratio),'Highest evidence tier')}${metric('Precise Coordinates',pct(k.coordinate_precision_coverage),'Non-centroid coverage')}${metric('Contactability',pct(k.contactability_coverage),'At least one active channel')}</div><div class="social-strip"><div><span>Instagram on D</span><strong>${k.E_instagram_on_D}</strong></div><div><span>TikTok on D</span><strong>${k.F_tiktok_on_D}</strong></div><div><span>Facebook on D</span><strong>${k.G_facebook_on_D}</strong></div><div><span>WhatsApp on D</span><strong>${k.H_whatsapp_on_D}</strong></div></div><div class="two-col">${bars('POIs by city',k.by_city)}${bars('Source contribution',k.by_source)}</div><div class="two-col">${bars('Google status distribution',k.by_google_status)}${bars('Quality distribution',k.by_quality_tier)}</div><div class="invariant-row"><div class="ok"><span>✓</span><span><strong>A = B + C + I</strong><small>Counting invariant ${k.invariant_a_equals_b_plus_c_plus_i?'passed':'failed'}</small></span></div><div class="ok"><span>✓</span><span><strong>D ⊆ C</strong><small>Usability subset ${k.invariant_d_subset_c?'passed':'failed'}</small></span></div><div class="ok"><span>✓</span><span><strong>Evidence-led</strong><small>No absence inferred by subtraction</small></span></div></div>`}
function projects(){qs('#content').innerHTML=`<div class="page-actions"><div><h2>Project portfolio</h2><p>Customer scope, geography, targets and thresholds.</p></div><button class="primary" onclick="newProject()">+ New project</button></div><div class="project-grid">${state.projects.map(p=>`<div class="project-card"><div class="project-icon">${esc(p.country.slice(0,2).toUpperCase())}</div><div>${badge(p.status)}<h3>${esc(p.name)}</h3><p>${esc(p.customer)}</p><div class="project-meta"><span>${esc(p.country)}</span><span>${p.cities.length} cities</span><span>Target ${p.target_volume}</span></div></div></div>`).join('')}</div>`}
async function newProject(){const name=prompt('Project name');if(!name)return;const customer=prompt('Customer','Demonstration Customer')||'Demonstration Customer';await api('/projects',{method:'POST',body:JSON.stringify({name,customer,country:'Indonesia',cities:['Jakarta'],categories:['All POI categories'],target_volume:100,confidence_threshold:70,gold_threshold:85})});state.projects=await api('/projects');state.project=state.projects[0];renderProjectSelect();projects()}
async function legacyWorkbench(){await loadData();qs('#content').innerHTML=`<div class="page-actions"><div><h2>POI workbench</h2><p>Review normalized candidates, Google status and D eligibility.</p></div><div class="summary-pills"><span>${state.candidates.length} candidates</span></div></div><div class="toolbar"><div class="searchbox"><span style="position:absolute;left:12px;top:10px">⌕</span><input id="search" placeholder="Search business name"></div><select id="statusFilter"><option value="">All Google statuses</option>${['GOOGLE_CHECK_PENDING','GOOGLE_PRESENT_CONFIRMED','GOOGLE_POSSIBLE_MATCH','GOOGLE_ABSENT_VERIFIED','GOOGLE_CHECK_INCONCLUSIVE'].map(x=>`<option>${x}</option>`).join('')}</select><button class="secondary" onclick="filterRows()">Apply</button></div><div id="tableArea"></div>`;renderTable(state.candidates)}
function renderTable(rows){qs('#tableArea').innerHTML=`<div class="table-wrap"><table><thead><tr><th>POI</th><th>City / Source</th><th>Google status</th><th>Confidence</th><th>Quality</th><th>D eligible</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr><td><div class="poi-name"><strong>${esc(r.business_name)}</strong><span>${esc(r.poi_id)}${r.is_demo?'<b>DEMO</b>':''}</span></div></td><td><strong>${esc(r.city||'—')}</strong><span class="cell-sub">${esc(r.source_name)}</span></td><td>${badge(r.google_status)}</td><td><div class="score"><i style="width:${r.confidence_score}%"></i><span>${r.confidence_score}</span></div></td><td>${badge(r.quality_tier)}</td><td>${r.usability_eligible?'<span class="yes">✓ Yes</span>':'<span class="no">⚠ No</span>'}</td><td><button class="text-button" onclick="openCandidate(${r.id})">Review</button></td></tr>`).join('')}</tbody></table></div>`}
function filterRows(){const s=qs('#search').value.toLowerCase(),f=qs('#statusFilter').value;renderTable(state.candidates.filter(r=>(!s||r.business_name.toLowerCase().includes(s))&&(!f||r.google_status===f)))}
function openCandidate(id){const r=state.candidates.find(x=>x.id===id);if(!r)return;qs('#drawerWrap').innerHTML=`<div class="drawer-backdrop" onclick="closeDrawer(event)"><aside class="drawer" onclick="event.stopPropagation()"><div class="drawer-title"><div><span>${esc(r.poi_id)}</span><h2>${esc(r.business_name)}</h2></div><button onclick="qs('#drawerWrap').innerHTML=''">×</button></div><div class="record-banner">${badge(r.google_status)}${badge(r.quality_tier)}${r.is_demo?'<span class="demo-tag">DEMO DATA</span>':''}</div><div class="detail-grid"><div><span>Category</span><strong>${esc(r.category)}</strong></div><div><span>City</span><strong>${esc(r.city||'Missing')}</strong></div><div><span>Coordinates</span><strong>${r.latitude??'Missing'}, ${r.longitude??'Missing'}</strong></div><div><span>Contact</span><strong>${esc(r.phone||r.whatsapp||r.website||'Missing')}</strong></div><div><span>Source</span><strong>${esc(r.source_name)}</strong></div><div><span>Evidence</span><strong>${esc(r.evidence_reference||'Missing')}</strong></div></div><div class="eligibility-box"><h3>D eligibility</h3>${r.usability_eligible?'<p class="success">✓ All mandatory rules passed.</p>':`<ul>${r.usability_failures.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>`}</div><form class="review-form" onsubmit="saveReview(event,${r.id})"><h3>Controlled Google review</h3><label>Decision<select name="decision">${['GOOGLE_PRESENT_CONFIRMED','GOOGLE_POSSIBLE_MATCH','GOOGLE_ABSENT_VERIFIED','GOOGLE_CHECK_INCONCLUSIVE'].map(d=>`<option ${d===r.google_status?'selected':''}>${d}</option>`).join('')}</select></label><label>Reason<textarea name="reason" required>Reviewed business name, city, address and source evidence.</textarea></label><label>Evidence reference<input name="evidence" value="${esc(r.evidence_reference||'')}"></label><button class="primary wide">Save review and recalculate</button></form></aside></div>`}
function closeDrawer(e){if(e.target===e.currentTarget)qs('#drawerWrap').innerHTML=''}
async function saveReview(e,id){e.preventDefault();const f=new FormData(e.target),r=state.candidates.find(x=>x.id===id),decision=f.get('decision'),evidence=f.get('evidence');try{await api(`/candidates/${id}/google-review`,{method:'POST',body:JSON.stringify({decision,completed:true,reason:f.get('reason'),evidence_reference:evidence||undefined,queries:[{check_type:'NAME_CITY',query:`${r.business_name} ${r.city}`,timestamp:new Date().toISOString(),decision}],candidate_place_ids:[]})});qs('#drawerWrap').innerHTML='';await workbench()}catch(err){alert(err.message)}}
async function legacyMapView(){await loadData();const pos={Jakarta:[49,61],Bandung:[53,65],Surabaya:[65,60],Medan:[20,30],Denpasar:[72,65]};const colors={'GOOGLE_ABSENT_VERIFIED':'#16a34a','GOOGLE_PRESENT_CONFIRMED':'#2563eb','GOOGLE_POSSIBLE_MATCH':'#f59e0b','GOOGLE_CHECK_INCONCLUSIVE':'#7c3aed','GOOGLE_CHECK_PENDING':'#64748b'};qs('#content').innerHTML=`<div class="page-actions"><div><h2>Map intelligence</h2><p>Spatial distribution of Google status and usable gaps across Indonesia.</p></div></div><div class="map-legend">${Object.entries(colors).map(([k,v])=>`<span><i style="background:${v}"></i>${k.replaceAll('_',' ')}</span>`).join('')}</div><div class="static-map"><div class="island sumatra"></div><div class="island java"></div><div class="island bali"></div>${state.candidates.map((r,i)=>{const p=pos[r.city]||[50,50];const left=p[0]+((i%3)-1)*1.1,top=p[1]+((i%4)-1.5)*1.2;return `<div class="pin" style="left:${left}%;top:${top}%;background:${colors[r.google_status]}"></div><div class="pin-label" style="left:${left}%;top:${top}%">${esc(r.business_name)} · ${esc(r.city)}</div>`}).join('')}<div class="simple-map-note">Offline demo map · precise coordinates retained in records and exports</div></div>`}
function imports(){qs('#content').innerHTML=`<div class="page-actions"><div><h2>Source data import</h2><p>Upload CSV or XLSX while preserving raw source lineage.</p></div></div><div class="import-layout"><form id="importForm" class="panel import-card"><div class="upload-icon">⇧</div><h3>Import POI candidates</h3><p>Common name, address, coordinate, contact and social columns are normalized automatically.</p><div id="importMsg"></div><label>Source name<input name="source_name" required placeholder="Authorized source or file provider"></label><label class="file-drop"><span>Select CSV or XLSX</span><input type="file" name="file" accept=".csv,.xlsx" required></label><button class="primary wide">Import and normalize</button></form><div class="panel rules-card"><h3>Import controls</h3><ul><li>Original row retained in source lineage.</li><li>Missing business names are rejected.</li><li>Coordinates are never fabricated.</li><li>Imports begin in Google-check pending.</li><li>No import counts under D before review.</li><li>Demo and file-upload modes stay labelled.</li></ul><a href="/sample-template.csv" download>Download field template</a></div></div>`;qs('#importForm').onsubmit=doImport}
async function doImport(e){e.preventDefault();const f=new FormData(e.target);f.set('project_id',state.project.id);try{const r=await api('/imports/poi',{method:'POST',body:f});qs('#importMsg').innerHTML=`<div class="alert success">Imported ${r.imported}; rejected ${r.rejected_rows}.</div>`}catch(err){qs('#importMsg').innerHTML=`<div class="alert error">${esc(err.message)}</div>`}}
function deliverables(){qs('#content').innerHTML=`<div class="page-actions"><div><h2>Customer deliverables</h2><p>Validate and export only records that satisfy configured usability rules.</p></div></div><div class="deliverable-card"><div class="deliverable-icon">✓</div><div><p class="eyebrow">CONTROLLED RELEASE</p><h2>Usable non-Google POI dataset</h2><p>XLSX output preserves POI ID, source lineage, Google status, confidence, tier, evidence, coordinate precision and validation date.</p><div class="check-list"><span>✓ D subset of C enforced</span><span>✓ Gold and Silver only</span><span>✓ Validation summary included</span><span>✓ Demo records labelled</span></div></div><button class="primary" onclick="exportXlsx()">⇩ Export XLSX</button></div>`}
async function exportXlsx(){try{const r=await api(`/exports/${state.project.id}/xlsx?usable_only=true`);const b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download='GeoDiscover_export.xlsx';a.click();URL.revokeObjectURL(u)}catch(e){alert(e.message)}}
// ---- City Discovery -------------------------------------------------------
// Pick a city, see the cost, run the pipeline, download the unique records.
const cov={regions:null,estimate:null,jobs:[],timer:null};
const STAGES=['QUEUED','SWEEPING_GRAB','SWEEPING_GOOGLE','SWEEPING_HERE','MATCHING','PROBING','FINISHED'];
const STAGE_LABEL={QUEUED:'Queued',SWEEPING_GRAB:'Sweep Grab',SWEEPING_GOOGLE:'Sweep Google',SWEEPING_HERE:'Sweep HERE',MATCHING:'Match',PROBING:'Probe',FINISHED:'Done'};
function usd(v){return v===null||v===undefined?'unknown':'$'+Number(v).toFixed(2)}

async function coverage(){
  if(cov.timer){clearInterval(cov.timer);cov.timer=null}
  cov.regions=cov.regions||await api('/jobs/regions');
  const provs=cov.regions.provinces;
  const configured=cov.regions.providers_configured;
  const warn=configured.length<2?`<div class="alert error">Only ${configured.join(' and ')||'no provider'} configured. A coverage comparison needs at least two providers — with one provider nothing can be marked unique.</div>`:'';
  qs('#content').innerHTML=`<div class="page-actions"><div><h2>City discovery</h2><p>Select a city, run both providers, download the records unique to each.</p></div></div>${warn}
  <div class="cov-grid"><form class="panel cov-form" id="covForm">
    <h3>1 · Select area</h3>
    <label>Province<select id="covProvince">${provs.map((p,i)=>`<option value="${i}">${esc(p.province)}</option>`).join('')}</select></label>
    <label>City<select id="covCity"></select></label>
    <label>Coverage<select id="covCoverage"><option value="CORE">Core — central commercial area (cheaper)</option><option value="FULL">Full — whole urban extent (much more expensive)</option></select></label>
    <label>Tile radius (metres)<input id="covTile" type="number" value="400" min="100" max="2000" step="50"></label>
    <button class="secondary wide" type="submit">Calculate cost</button>
  </form>
  <div class="panel"><h3>2 · Cost before you run</h3><div id="covEstimate"><p class="muted">Choose an area and calculate. This makes no provider calls and costs nothing.</p></div></div></div>
  <div class="panel"><div class="panel-title"><h3>Runs</h3><button class="secondary" onclick="refreshJobs()">↻ Refresh</button></div><div id="covJobs"></div></div>`;
  qs('#covProvince').onchange=fillCities; qs('#covForm').onsubmit=doEstimate;
  fillCities(); await refreshJobs();
}
function fillCities(){
  const p=cov.regions.provinces[qs('#covProvince').value];
  qs('#covCity').innerHTML=p.cities.map(c=>`<option value="${c.code}">${esc(c.name)}</option>`).join('');
}
async function doEstimate(e){
  e.preventDefault();
  qs('#covEstimate').innerHTML='<p class="muted">Calculating…</p>';
  try{
    const body={project_id:state.project.id,city_code:qs('#covCity').value,coverage:qs('#covCoverage').value,tile_radius_m:Number(qs('#covTile').value)};
    const est=await api('/jobs/estimate',{method:'POST',body:JSON.stringify(body)});
    cov.estimate={...body,est};
    const rows=Object.entries(est.providers).map(([p,v])=>`<tr><td>${p} sweep</td><td>${v.calls_expected} calls · ${usd(v.cost_expected_usd)}</td></tr>`).join('');
    const incomplete=!est.cost_is_complete?`<div class="cost-box cost-warn">Cost is incomplete: no rate configured for ${est.unpriced_operations.join(', ')}. Set it in backend/.env or this run is unpriced.</div>`:'';
    const big=est.coverage==='FULL'?'<div class="cost-box cost-warn">FULL coverage sweeps the whole urban extent. Check the figure below carefully before confirming.</div>':'';
    qs('#covEstimate').innerHTML=`${big}${incomplete}
      <div class="cost-box"><table><tr><td>Area</td><td>${esc(est.city)} · ${est.coverage} · ${est.radius_m} m</td></tr><tr><td>Tiles</td><td>${est.tiles}</td></tr>${rows}<tr><td>Sweep total</td><td class="cost-big">${usd(est.sweep_cost_expected_usd)}</td></tr></table></div>
      <p class="muted" style="font-size:11px">${esc(est.probe_note)}</p>
      <button class="primary wide" onclick="startJob()">Run discovery for ${esc(est.city)}</button>`;
  }catch(err){qs('#covEstimate').innerHTML=`<div class="alert error">${esc(err.message)}</div>`}
}
async function startJob(){
  if(!cov.estimate)return;
  const e=cov.estimate.est;
  if(!confirm(`Run live discovery for ${e.city} (${e.coverage})?\n\nEstimated sweep cost: ${usd(e.sweep_cost_expected_usd)}\nProbing is charged on top.\n\nThis spends real money against your Google and AWS accounts.`))return;
  try{
    await api('/jobs',{method:'POST',body:JSON.stringify({...cov.estimate,est:undefined,confirm:true})});
    await refreshJobs(); startPolling();
  }catch(err){alert(err.message)}
}
async function refreshJobs(){
  cov.jobs=await api(`/jobs?project_id=${state.project.id}`);
  const el=qs('#covJobs'); if(!el)return;
  if(!cov.jobs.length){el.innerHTML='<p class="muted">No runs yet.</p>';return}
  el.innerHTML=cov.jobs.map(j=>{
    const running=j.status==='RUNNING'||j.status==='PENDING';
    const idx=STAGES.indexOf(j.stage);
    const track=STAGES.map((s,i)=>`<div class="${i<idx?'done':i===idx?'active':''}">${STAGE_LABEL[s]}</div>`).join('');
    const probe=j.probes_total?` · probed ${j.probes_done}/${j.probes_total}`:'';
    const ev=j.evidence_split||{};
    // Probe evidence and area-coverage evidence are different strengths and are
    // never blended into one number; show the split under each headline count.
    const split=(p,a)=>(p||a)?`<div class="cell-sub">${p||0} probe · ${a||0} area</div>`:'';
    const free=j.coverage_resolved?` · ${j.coverage_resolved} resolved free`:'';
    const when=new Date(j.started_at).toLocaleString();
    return `<div><div class="job-row">
      <div><strong>${esc(j.city_name)}</strong><div class="cell-sub">${esc(j.province)} · ${j.coverage} · ${esc(when)}</div></div>
      <div>${badge(j.status)}</div>
      <div><b>${j.grab_only_count}</b><div class="cell-sub">Grab only</div>${split(ev.grab_probe,ev.grab_area)}</div>${j.here_only_count?`<div><b>${j.here_only_count}</b><div class="cell-sub">HERE only</div><div class="cell-sub" title="No probe stage for HERE yet">sweep-derived</div></div>`:''}
      <div><b>${j.google_only_count}</b><div class="cell-sub">Google only</div>${split(ev.google_probe,ev.google_area)}</div>
      <div><b>${j.matched_count}</b><div class="cell-sub">In both</div></div>
      <div><b>${j.unresolved_count}</b><div class="cell-sub">Unresolved</div></div>
      <div>${j.stage==='FINISHED'||!running?`<button class="primary" onclick="downloadJob(${j.id})">⇩ Excel</button>`:'<span class="muted">running…</span>'}</div>
    </div>${running?`<div class="stage-track">${track}</div>`:''}
    <div class="cell-sub" style="margin:-4px 0 12px 2px">${j.api_calls} calls · spent ${usd(j.actual_cost_usd)} (estimated ${usd(j.est_cost_usd)})${probe}${free}${j.error?` · <span style="color:#b91c1c">${esc(j.error)}</span>`:''}</div></div>`;
  }).join('');
}
function startPolling(){
  if(cov.timer)clearInterval(cov.timer);
  cov.timer=setInterval(async()=>{
    if(!location.hash.startsWith('#coverage')){clearInterval(cov.timer);cov.timer=null;return}
    await refreshJobs();
    if(!cov.jobs.some(j=>j.status==='RUNNING'||j.status==='PENDING')){clearInterval(cov.timer);cov.timer=null}
  },3000);
}
async function downloadJob(id){
  const job=cov.jobs.find(j=>j.id===id);
  try{
    const r=await api(`/jobs/${id}/export.xlsx`);
    const b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');
    a.href=u;a.download=`GeoDiscover_${(job?.city_name||'city').replace(/\W+/g,'_')}.xlsx`;a.click();URL.revokeObjectURL(u);
  }catch(e){alert(e.message)}
}

// ---- Controlled provider-run views ------------------------------------------------------
// These read provider_places, i.e. what the provider APIs actually returned.
// The seeded demo records live in a different table and never appear here.
const live={kpis:null,page:1,filters:{}};
const VERDICTS=['MATCHED','UNIQUE_VERIFIED','POSSIBLE_MATCH','UNRESOLVED'];
const VERDICT_LABEL={MATCHED:'In both',UNIQUE_VERIFIED:'Unique',POSSIBLE_MATCH:'Needs review',UNRESOLVED:'Unresolved'};
const BUCKET_COLOR={BOTH:'#2563eb',GRAB_ONLY:'#16a34a',GOOGLE_ONLY:'#f59e0b',POSSIBLE:'#7c3aed',UNRESOLVED:'#64748b'};

function bucketOf(r){
  if(r.verdict==='MATCHED')return 'BOTH';
  if(r.verdict==='UNIQUE_VERIFIED')return r.provider==='GRAB'?'GRAB_ONLY':'GOOGLE_ONLY';
  if(r.verdict==='POSSIBLE_MATCH')return 'POSSIBLE';
  return 'UNRESOLVED';
}
async function liveKpis(){live.kpis=await api(`/comparison/${state.project.id}/kpis`);return live.kpis}
function noDataPanel(what){
  return `<div class="panel" style="text-align:center;padding:44px"><h3>No provider-run data yet</h3>
    <p class="muted">${what} reads the records returned by the GrabMaps and Google Places APIs. HERE coverage is compared on the Area Comparison page.
    Nothing has been discovered for this project yet.</p>
    <p><a href="#coverage" class="primary" style="display:inline-block;padding:10px 18px;border-radius:8px;text-decoration:none">Go to City Discovery</a></p>
    <p class="muted" style="font-size:11px;margin-top:14px">The seeded demo records are kept separately and are not shown here.</p></div>`;
}

async function dashboard(){
  const k=await liveKpis();
  if(!k.G_grab_total&&!k.K_google_total){qs('#content').innerHTML=noDataPanel('The executive dashboard');return}
  const inv=k.invariant_grab_partition&&k.invariant_google_partition&&k.invariant_unique_has_probe_evidence;
  const ev=(p,a)=>`<small>${p} probe · ${a} area coverage</small>`;
  qs('#content').innerHTML=`
  <div class="hero-panel"><div><p class="eyebrow">LIVE PROVIDER COMPARISON</p>
    <h2>${pct(k.google_coverage_gap_pct)} of GrabMaps POI candidates were not matched in this controlled run</h2>
    <p>Each candidate carries probe or area-coverage evidence. Final active-business and customer-release claims still require enrichment, full Google exclusion and QA.</p></div>
    <div class="hero-score"><strong>${k.GU_grab_only_verified}</strong><span>Grab-side incremental candidates</span></div></div>
  <div class="metrics-grid">
    ${metric('GrabMaps POIs',k.G_grab_total,'Discovered and category-filtered')}
    ${metric('Google POIs',k.K_google_total,'Discovered and category-filtered')}
    ${metric('Present in both',k.M_matched,`${pct(k.overlap_jaccard_pct)} overlap`)}
    ${metric('Grab incremental candidates',k.GU_grab_only_verified,`${k.GU_grab_only_probe_verified} probe · ${k.GU_grab_only_area_verified} area`,'accent')}
    ${metric('Google incremental candidates',k.KU_google_only_verified,`${k.KU_google_only_probe_verified} probe · ${k.KU_google_only_area_verified} area`)}
    ${metric('Needs review',k.P_grab_possible+k.P_google_possible,'Ambiguous pairings')}
    ${metric('Unresolved',k.U_grab_unresolved+k.U_google_unresolved,'Insufficient evidence either way')}
    ${metric('Coordinate agreement',k.median_coordinate_delta_m===null?'—':`${k.median_coordinate_delta_m} m`,'Median offset on matched pairs')}
  </div>
  <div class="social-strip">
    <div><span>Grab contactability</span><strong>${pct(k.grab_contactability_pct)}</strong></div>
    <div><span>Google contactability</span><strong>${pct(k.google_contactability_pct)}</strong></div>
    <div><span>Recovered by probe</span><strong>${k.places_recovered_by_probe}</strong></div>
    <div><span>Grab resolved</span><strong>${pct(k.grab_resolved_pct)}</strong></div>
  </div>
  <div class="two-col">${bars('GrabMaps by city',k.grab_by_city)}${bars('Google by city',k.google_by_city)}</div>
  <div class="two-col">${bars('GrabMaps outcome',k.grab_by_verdict)}${bars('Google outcome',k.google_by_verdict)}</div>
  <div class="invariant-row">
    <div class="ok"><span>${k.invariant_grab_partition?'✓':'✕'}</span><span><strong>Grab set partitions</strong><small>matched + unique + review + unresolved = total</small></span></div>
    <div class="ok"><span>${k.invariant_google_partition?'✓':'✕'}</span><span><strong>Google set partitions</strong><small>no record counted twice or lost</small></span></div>
    <div class="ok"><span>${k.invariant_unique_has_probe_evidence?'✓':'✕'}</span><span><strong>Evidence-led</strong><small>${k.unique_records_missing_probe_evidence} unique records lack evidence</small></span></div>
  </div>
  ${inv?'':'<div class="alert error">An invariant failed. This dataset is not fit to issue.</div>'}`;
}

async function workbench(){
  const k=await liveKpis();
  if(!k.G_grab_total&&!k.K_google_total){qs('#content').innerHTML=noDataPanel('The POI workbench');return}
  const cities=await api(`/comparison/${state.project.id}/cities`);
  qs('#content').innerHTML=`<div class="page-actions"><div><h2>POI workbench</h2>
    <p>Provider records returned during the controlled GrabMaps and Google Places run, with the evidence behind each classification.</p></div></div>
  <div class="toolbar">
    <div class="searchbox"><span style="position:absolute;left:12px;top:10px">⌕</span><input id="lvQ" placeholder="Search business name"></div>
    <select id="lvProvider"><option value="">Both providers</option><option value="GRAB">GrabMaps</option><option value="GOOGLE">Google</option></select>
    <select id="lvVerdict"><option value="">All outcomes</option>${VERDICTS.map(v=>`<option value="${v}">${VERDICT_LABEL[v]}</option>`).join('')}</select>
    <select id="lvCity"><option value="">All cities</option>${cities.map(c=>`<option value="${esc(c.city)}">${esc(c.city)} (${c.count})</option>`).join('')}</select>
    <button class="secondary" onclick="live.page=1;loadPlaces()">Apply</button>
  </div><div id="lvTable"></div>`;
  qs('#lvQ').addEventListener('keydown',e=>{if(e.key==='Enter'){live.page=1;loadPlaces()}});
  await loadPlaces();
}
async function loadPlaces(){
  const p=new URLSearchParams({page:live.page,page_size:50});
  const q=qs('#lvQ')?.value,pr=qs('#lvProvider')?.value,vd=qs('#lvVerdict')?.value,ct=qs('#lvCity')?.value;
  if(q)p.set('q',q); if(pr)p.set('provider',pr); if(vd)p.set('verdict',vd); if(ct)p.set('city',ct);
  const data=await api(`/comparison/${state.project.id}/places?${p}`);
  qs('#lvTable').innerHTML=`<div class="table-wrap"><table>
    <thead><tr><th>Business</th><th>Provider</th><th>City</th><th>Outcome</th><th>Contact</th><th>Coordinates</th><th></th></tr></thead>
    <tbody>${data.items.map(r=>`<tr>
      <td><div class="poi-name"><strong>${esc(r.name)}</strong><span>${esc((r.categories||[]).slice(0,2).join(', '))}</span></div></td>
      <td>${badge(r.provider)}</td>
      <td>${esc(r.city||'—')}</td>
      <td><span class="status-badge" style="background:${BUCKET_COLOR[bucketOf(r)]}22;color:${BUCKET_COLOR[bucketOf(r)]}">${bucketOf(r).replaceAll('_',' ')}</span></td>
      <td>${esc(r.phone_e164||r.website||'—')}</td>
      <td class="cell-sub">${r.lat!==null?`${r.lat.toFixed(5)}, ${r.lng.toFixed(5)}`:'—'}</td>
      <td><button class="text-button" onclick="openPlace(${r.id})">Evidence</button></td></tr>`).join('')}</tbody></table></div>
    <div class="page-actions" style="margin-top:12px"><span class="muted">${data.total} records · page ${data.page} of ${data.pages}</span>
      <span>${data.page>1?`<button class="secondary" onclick="live.page--;loadPlaces()">← Previous</button> `:''}
      ${data.page<data.pages?`<button class="secondary" onclick="live.page++;loadPlaces()">Next →</button>`:''}</span></div>`;
}
async function openPlace(id){
  const r=await api(`/comparison/places/${id}`);
  const e=r.evidence;
  const strength={PROBE:'STRONG — live lookup, no category filter',AREA_COVERAGE:'MODERATE — swept area, category filter applies'};
  qs('#drawerWrap').innerHTML=`<div class="drawer-backdrop" onclick="closeDrawer(event)"><aside class="drawer" onclick="event.stopPropagation()">
    <div class="drawer-title"><div><span>${esc(r.provider)} · ${esc(r.provider_place_id)}</span><h2>${esc(r.name)}</h2></div>
      <button onclick="qs('#drawerWrap').innerHTML=''">×</button></div>
    <div class="record-banner"><span class="status-badge" style="background:${BUCKET_COLOR[bucketOf(r)]}22;color:${BUCKET_COLOR[bucketOf(r)]}">${bucketOf(r).replaceAll('_',' ')}</span>${r.discovered_by_probe?'<span class="demo-tag">FOUND BY PROBE</span>':''}</div>
    <div class="detail-grid">
      <div><span>Categories</span><strong>${esc((r.categories||[]).join(', ')||'—')}</strong></div>
      <div><span>City</span><strong>${esc(r.city||'—')}</strong></div>
      <div><span>Address</span><strong>${esc(r.address||'—')}</strong></div>
      <div><span>Coordinates</span><strong>${r.lat!==null?`${r.lat}, ${r.lng}`:'—'}</strong></div>
      <div><span>Phone</span><strong>${esc(r.phone_e164||'Not provided')}</strong></div>
      <div><span>Website</span><strong>${esc(r.website||'Not provided')}</strong></div>
    </div>
    <div class="eligibility-box"><h3>Evidence for this verdict</h3>
      ${e?`<p><strong>${esc(e.evidence_method)}</strong> — ${esc(strength[e.evidence_method]||'')}</p>
           <p>${esc(e.reason)}</p>
           <p class="cell-sub">Checked against ${esc(e.probed_provider)} · ${e.result_count} result(s) · best score ${e.best_score??'—'} · ${new Date(e.probed_at).toLocaleString()}</p>`
         :'<p class="muted">No uniqueness evidence stored. This record is unresolved: we have not established whether the other provider lists it.</p>'}</div>
    ${r.counterparts.length?`<div class="eligibility-box"><h3>Paired records</h3>
      ${r.counterparts.map(c=>`<p><strong>${esc(c.name)}</strong> (${esc(c.provider)})<br>
        <span class="cell-sub">${esc(c.decision)} · score ${c.score} · ${c.distance_m} m apart · ${esc(c.method)}<br>
        ${esc(Object.entries((c.signals||{}).contributions||{}).map(([kk,vv])=>`${kk}=${vv}`).join(', '))}</span></p>`).join('')}</div>`:''}
    <div class="eligibility-box"><h3>Raw provider payload</h3>
      <pre style="white-space:pre-wrap;font-size:10px;max-height:220px;overflow:auto">${esc(JSON.stringify(r.raw_payload,null,1).slice(0,4000))}</pre></div>
  </aside></div>`;
}

async function mapView(){
  const k=await liveKpis();
  if(!k.G_grab_total&&!k.K_google_total){qs('#content').innerHTML=noDataPanel('Map intelligence');return}
  const geo=await api(`/comparison/${state.project.id}/report.geojson`);
  const feats=geo.features.filter(f=>f.geometry?.coordinates?.length===2);
  if(!feats.length){qs('#content').innerHTML=noDataPanel('Map intelligence');return}
  const lngs=feats.map(f=>f.geometry.coordinates[0]),lats=feats.map(f=>f.geometry.coordinates[1]);
  const minX=Math.min(...lngs),maxX=Math.max(...lngs),minY=Math.min(...lats),maxY=Math.max(...lats);
  const spanX=(maxX-minX)||0.01,spanY=(maxY-minY)||0.01;
  const counts={};feats.forEach(f=>{counts[f.properties.bucket]=(counts[f.properties.bucket]||0)+1});
  qs('#content').innerHTML=`<div class="page-actions"><div><h2>Map intelligence</h2>
    <p>${feats.length} controlled-run records plotted from provider coordinates. Bounds ${minY.toFixed(4)}, ${minX.toFixed(4)} to ${maxY.toFixed(4)}, ${maxX.toFixed(4)}.</p></div></div>
  <div class="map-legend">${Object.entries(BUCKET_COLOR).map(([b,c])=>`<span><i style="background:${c}"></i>${b.replaceAll('_',' ')} (${counts[b]||0})</span>`).join('')}</div>
  <div class="static-map">${feats.map(f=>{
    const [x,y]=f.geometry.coordinates;
    const left=4+((x-minX)/spanX)*92, top=96-((y-minY)/spanY)*92;
    const c=BUCKET_COLOR[f.properties.bucket]||'#64748b';
    return `<div class="pin" style="left:${left}%;top:${top}%;background:${c};width:11px;height:11px"></div>
            <div class="pin-label" style="left:${left}%;top:${top}%">${esc(f.properties.name)} · ${esc(f.properties.bucket)}</div>`;
  }).join('')}<div class="simple-map-note">Controlled-run provider coordinates · linear projection of the data bounding box</div></div>`;
}

// Pages this deployment serves. The other view functions above are unreferenced
// and left in place: they are one-liners that call each other, and pruning them
// piecemeal breaks the file. Removing the routes is what takes the pages away.
const views={projects,coverage,imports,
             area:(...a)=>window.areaView(...a)};
async function route(){const view=(location.hash||'#area').slice(1);document.querySelectorAll('#nav a').forEach(a=>a.classList.toggle('active',a.dataset.view===view));const titles={area:'Area Comparison',coverage:'City Discovery',projects:'Projects',imports:'Data Import'};qs('#pageTitle').textContent=titles[view]||'GeoDiscover';await (views[view]||views.area)()}
qs('#loginForm').addEventListener('submit',login);qs('#logout').addEventListener('click',logout);window.addEventListener('hashchange',route);qs('#projectSelect').addEventListener('change',async e=>{state.project=state.projects.find(p=>p.id==e.target.value);await route()});start();
