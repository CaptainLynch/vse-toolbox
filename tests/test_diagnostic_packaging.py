from pathlib import Path
import ast


def test_scheduler_package_contains_report_contract_for_recorded_exports():
    """录屏导出依赖的报表列头契约必须随应用包分发（VSE-WebUI.spec datas）。

    W15-01 起 CLI 专属的 VSE-Toolbox.spec 已下线，打包守卫指向现行应用包。
    datas 使用 *collect 展开式，无法 literal_eval，故按字面量断言。
    """
    source = Path('VSE-WebUI.spec').read_text(encoding='utf-8')
    assert "('core/report_headers.json', 'core')" in source
