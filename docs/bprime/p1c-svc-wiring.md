# B′ P1c 服务接线参考补丁

基线：services/project_status_updates.py，1239行，SHA256 ac595f0986b5380c5408a26198e9b78e01395c8d557b50d7bee6f7d195955f1a；core/repos/project_status.py，1150行，SHA256 a71ff93b9256276e78f405cebe8ba8528fd9f2fa2d5fef8fc1c48d1ef7778b2f，保持不变。服务预算+32/−16，diff48，最终1255行。行号均指基线，以内容锚点定位。

## 段 P：预检 P1—P5
P1：两份基线匹配；仓储模块级导出KEEP_CURRENT、ProjectStatusConfigDigestMismatchError和compute_policy_config_digest；核心两条返回路径raw均已归一化。
P2：935行与1147—1165行同属保存方法；新增expected_digest、conn、result、response无局部名冲突；credential_ref在替换区仅作调用实参，之后无引用。
P3：原setter返回值未使用；连接上下文进入时无事务，退出提交或回滚并关闭，与原setter包装同构。
P4：GET与核心raw顶层键同为binding、authorities、latest_audit；转换器可直接读取；现有保存返回断言无整dict相等。
P5：916—1146行不遍历payload全部键写入或审计；文档创建后实施前须完成U-BPRIME-TXN-APPLY用户验收。任一不符停止报告。

## 段 D：导入，+3/−0
紧接基线24行导入块之后插入：
```
from core.repos.project_status import (
    KEEP_CURRENT, ProjectStatusConfigDigestMismatchError, compute_policy_config_digest,
)
```

## 段 E：允许键，+1/−0
仅在925行的intervalMinutes元素后追加一行，其他元素及unknown报错不变：
```
            "expectedConfigDigest",
```

## 段 A：事务接线，+18/−13
将1147—1160行整体替换为下文；try行仅作上下文保留。原935行及此前业务校验保持不变；段F插在首行之后、KEEP_CURRENT判断之前。
```
        expected_digest = payload.get('expectedConfigDigest')
        if expected_digest is not None and 'credentialRef' not in payload:
            credential_ref = KEEP_CURRENT
        try:
            with self._db.get_connection() as conn:
                result = self._db._save_policy_txn(
                    conn, deliverable_id, mode, enabled, external_key,
                    _json_dumps(match_rule), _json_dumps(mapping), normalized_authority,
                    credential_ref=credential_ref, interval_minutes=interval_minutes,
                    expected_sync_config_revision=(
                        int(binding.get('sync_config_revision') or 0)
                        if project_status_supports_record_set(deliverable_id)
                        else None
                    ),
                    # 绑定配置审计在保存事务内写入（B′ P1a）；字段归属用 API 字段名记审计。
                    actor=actor,
                    audit_field_names=PROJECT_STATUS_FIELD_NAME_TO_API,
                    expected_config_digest=expected_digest,
                )
```

## 段 B：异常映射，+2/−0
在原1161行父类except之前插入；父类分支逐字保留：
```
        except ProjectStatusConfigDigestMismatchError:
            raise ProjectStatusPolicyError({'expectedConfigDigest': '绑定已发生变化，请刷新配置后重试'}) from None
```

## 段 C：返回事务快照，+4/−3
将1163—1165行整体替换，删去保存后的GET及assert，不改转换器或独立GET方法：
```
        response = self._policy_to_api(result.raw)
        response['configDigest'] = compute_policy_config_digest(
            deliverable_id, result.raw['binding'], result.raw['authorities'])
        return response
```

## 段 F：格式校验，+4/−0
在段A首行之后插入：
```
        if expected_digest is not None and (not isinstance(expected_digest, str)
                or len(expected_digest) != 70 or not expected_digest.startswith('cfgd1:')
                or any(ch not in '0123456789abcdef' for ch in expected_digest[6:])):
            raise ProjectStatusPolicyError({'expectedConfigDigest': '配置摘要格式无效'}) from None
```
缺省或null沿用旧路径；其余必须为cfgd1:加64位小写十六进制；不trim、不转换大小写。短路保证非字符串不被切片。格式错误在核心调用前返回字段错误；格式合法但过期由段B处理。显式credentialRef（含null）不替换为哨兵。

## 段 V：核对与验收交接
保存方法内原setter调用为0，保存后第二次GET为0，首次预读GET保留；连接调用为1；子类except先于父类；configDigest追加在旧响应末尾。核对段F先于哨兵赋值、核心调用，仓储SHA不变、仅服务生产文件有修改。不改web/app.py、DDL、tests/conftest.py及P1b冻结节点。实施后由Host按实施卡发起用户测试交接，有效回执且版本一致才可完成。静态31+2=33，尚未运行；既有回归不能证明新摘要、哨兵及格式分支覆盖。
