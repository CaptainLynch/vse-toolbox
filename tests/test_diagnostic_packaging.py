from pathlib import Path
import ast


def test_scheduler_package_contains_report_contract_for_recorded_exports():
    source = Path('VSE-Toolbox.spec').read_text(encoding='utf-8')
    tree = ast.parse(source)
    analysis = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'Analysis')
    datas = ast.literal_eval(next(k.value for k in analysis.keywords if k.arg == 'datas'))
    assert ('core/report_headers.json', 'core') in datas
