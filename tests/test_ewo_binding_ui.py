import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('sor_dom_helper', Path(__file__).with_name('test_sor_ui_behavior.py'))
_helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helper)
run_node_vm_test = _helper.run_node_vm_test


def test_migrating_editor_sets_explicit_version_and_manual_scalar_authority():
    result = run_node_vm_test('''
    const render = vm.runInContext('renderSyncBindingEditor', context);
    const host = doc.createElement('div'); doc.body.appendChild(host);
    const item = {id:'VPI-T2-D3',name:'EWO',sourceInfo:{reportType:'ewo',aggregate:true}};
    const policy = {mode:'hybrid',enabled:true,externalKey:'E-1',credentialAvailable:true,
      matchRule:{reportType:'ewo',aggregate:true,modelInfo:'SYNTHETIC'},
      mapping:{owner:'engineer',plannedDate:'due',note:'summary'},
      fieldAuthority:{owner:'automatic',plannedDate:'automatic',note:'automatic'}};
    render(host,item,policy);
    const mode = host.querySelector('[name="ewoBindingMode"]');
    const owner = host.querySelector('[data-authority-field="owner"]');
    const date = host.querySelector('[data-authority-field="plannedDate"]');
    const enabled = host.querySelector('[name="enabled"]');
    const before = {mode:mode.value, owner:owner.checked, enabled:enabled.checked};
    mode.value='record_set'; mode.dispatchEvent({type:'change'});
    let sent = null;
    global.fetch = async (path,options) => { sent=JSON.parse(options.body); throw new Error('stop after capture'); };
    host.querySelector('form').dispatchEvent({type:'submit',preventDefault(){}});
    await new Promise(resolve=>setTimeout(resolve,0));
    return {before,owner:owner.checked,date:date.checked,disabled:owner.disabled,enabled:enabled.checked,sent};
    ''')
    assert result['before'] == {'mode': 'legacy', 'owner': True, 'enabled': True}
    assert result['owner'] is False and result['date'] is False
    assert result['disabled'] is True and result['enabled'] is False
    assert result['sent']['bindingContractVersion'] == '2'
    assert result['sent']['matchRule']['bindingMode'] == 'record_set'
    assert result['sent']['externalKey'] is None
    assert result['sent']['mapping'] == {'note': 'summary'}
