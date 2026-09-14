from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.html"
REPOSITORY_JS = ROOT / "docs" / "assets" / "rigp_case_repository.js"
SHELL_JS = ROOT / "docs" / "assets" / "rigp_shell_v2.js"
JOURNAL_JS = ROOT / "docs" / "assets" / "rigp_shell_case_journal.js"


def test_case_repository_is_loaded_before_case_app():
    html = INDEX.read_text(encoding="utf-8")
    repo_pos = html.index("assets/rigp_case_repository.js")
    app_pos = html.index("assets/rigp_case_app.js")
    shell_pos = html.index("assets/rigp_shell_v2.js")
    journal_pos = html.index("assets/rigp_shell_case_journal.js")
    assert repo_pos < app_pos < shell_pos < journal_pos
    assert html.count("assets/rigp_case_repository.js") == 1


def test_case_repository_declares_remote_ready_contract_without_backend_dependency():
    js = REPOSITORY_JS.read_text(encoding="utf-8")
    assert "RIGP-CASE-REPOSITORY-v1" in js
    assert "RIGP-CASE-ADAPTER-v1" in js
    assert "attachRemote" in js
    assert "load" in js and "persist" in js
    assert "remote-ready-cache" in js
    assert "rigp_cases_v1" in js
    assert "supabase" not in js.lower()
    assert "data/investigative_findings.json" not in js


def test_shell_and_journal_use_repository_without_direct_localstorage_access():
    for path in (SHELL_JS, JOURNAL_JS):
        js = path.read_text(encoding="utf-8")
        assert "RIGPCaseRepository" in js
        assert "localStorage" not in js
        assert "rigp_cases_v1" not in js
    assert "caseRepo?.subscribe" in SHELL_JS.read_text(encoding="utf-8")
    assert "caseRepo?.subscribe" in JOURNAL_JS.read_text(encoding="utf-8")


def test_case_repository_javascript_syntax():
    node = shutil.which("node")
    assert node, "Node.js is required to validate browser JavaScript syntax"
    for path in (REPOSITORY_JS, SHELL_JS, JOURNAL_JS):
        subprocess.run([node, "--check", str(path)], check=True)


def test_case_repository_preserves_legacy_ui_and_can_attach_remote_adapter():
    node = shutil.which("node")
    assert node, "Node.js is required to exercise the browser repository contract"
    script = r'''
const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
class Storage {
  constructor(){this.map=new Map()}
  getItem(k){return this.map.has(k)?this.map.get(k):null}
  setItem(k,v){this.map.set(k,String(v))}
  removeItem(k){this.map.delete(k)}
}
const localStorage=new Storage();
localStorage.setItem('rigp_cases_v1',JSON.stringify([{case_id:'local-1',case_ref:'RIGP-L1',status:'TRIAGE',finding_ids:['f1'],evidence:[],updated_at:'2026-09-14T10:00:00Z'}]));
const window={localStorage,Storage,addEventListener(){},dispatchEvent(){}};
global.window=window;
global.Storage=Storage;
global.CustomEvent=class CustomEvent{constructor(type,opts={}){this.type=type;this.detail=opts.detail}};
const source=fs.readFileSync(process.argv[1],'utf8');
vm.runInThisContext(source,{filename:process.argv[1]});
(async()=>{
  const repo=window.RIGPCaseRepository;
  assert.equal(repo.version,'RIGP-CASE-REPOSITORY-v1');
  assert.equal(repo.list().length,1);
  assert.equal(repo.findByFinding('f1').case_id,'local-1');

  // El núcleo legado aún puede escribir por la clave histórica durante la transición.
  localStorage.setItem('rigp_cases_v1',JSON.stringify([
    {case_id:'local-1',case_ref:'RIGP-L1',status:'TRIAGE',finding_ids:['f1'],evidence:[],updated_at:'2026-09-14T10:00:00Z'},
    {case_id:'local-2',case_ref:'RIGP-L2',status:'EN_REVISION',finding_ids:['f2'],evidence:[],updated_at:'2026-09-14T11:00:00Z'}
  ]));
  assert.equal(repo.list().length,2);

  let persisted=0;
  await repo.attachRemote({
    async load(){return [{case_id:'remote-1',case_ref:'RIGP-R1',status:'TRIAGE',finding_ids:['f3'],evidence:[],updated_at:'2026-09-14T12:00:00Z'}]},
    async persist(rows){persisted++;assert.ok(Array.isArray(rows))}
  });
  assert.equal(repo.list().length,3);
  assert.equal(repo.describe().remote_state,'ready');

  repo.upsert({case_id:'local-3',case_ref:'RIGP-L3',status:'TRIAGE',finding_ids:['f4'],evidence:[],updated_at:'2026-09-14T13:00:00Z'});
  await repo.flush();
  assert.ok(persisted>=1);
  assert.equal(repo.get('local-3').case_ref,'RIGP-L3');
})().catch(err=>{console.error(err);process.exit(1)});
'''
    subprocess.run([node, "-e", script, str(REPOSITORY_JS)], check=True)
