# 生产环境数模设计审核流程报表与 SOR 信息采集指引

> 目的：本机 VPN 当前只能验证 Aras 交付物链路。请在公司生产网络中按本文件采集最小必要证据，带回后再完成数模报表与 SOR 的字段契约、筛选映射和 UI 验证。不要把密码、Token、Cookie 或 Authorization 原文带出生产环境。

## 一、采集原则

- 只记录 URL 路径、HTTP 方法、状态码、耗时、脱敏后的请求参数和响应字段摘要。
- 过滤 `Authorization`、`Cookie`、`Set-Cookie`、Token、密码、私钥、Session ID 等字段；导出前执行一键脱敏并人工复核。
- 优先使用浏览器 DevTools 的 Network “Copy as cURL (sanitized)” 或项目 Debug 工具 JSON 导出，不复制完整响应正文。
- 每个场景至少保存一次成功请求和一次无结果请求，并记录查询条件、时间、账号角色（只写角色，不写账号）。

## 二、数模设计审核流程报表（TDC Data Model）

### 需要做什么

1. 登录生产 TDC，打开“数模设计审核流程报表”。
2. 分别执行以下查询：
   - 无筛选（若权限允许，限制最小页数）；
   - 流程/单号；
   - 部门、科室；
   - 车型项目；
   - 零件号、车型号；
   - 申请开始/结束日期。
3. 对每次查询记录 Network 请求的路径、方法、状态码、耗时、参数键名、响应顶层键名和一条脱敏字段样例。
4. 导出 XLSX/CSV 一次，记录导出请求及文件列名顺序。
5. 对“无结果”条件保存响应摘要，确认是空数组、业务错误还是权限/登录跳转。

### 必须带回的内容

```text
场景：
查询条件（脱敏）：
请求方法/路径：
状态码/耗时：
请求参数键名和值类型（不含敏感值）：
响应顶层键名：
记录数组路径：
字段名清单与一条脱敏样例：
分页字段：
导出列名：
无结果时的响应摘要：
```

重点确认前端显示名与后端参数的对应关系，尤其是 `incident`、`superDepartment`、`department`、`projectModel`、`partNumber`、`modelNumber` 以及日期字段。

## 三、SOR 报表

### 需要做什么

1. 打开生产 TDC 的 SOR 查询页面。
2. 先执行部门查询（已知可返回结果），再执行车型项目查询：
   - 使用下拉框选择一个车型项目；
   - 记录项目显示编号/名称与内部 ID（内部 ID 只记录哈希或末 4 位）；
   - 仅输入显示编号/名称，不选择下拉项；
   - 同时选择车型项目和部门。
3. 对每次查询记录 Network 请求和响应摘要，重点比较：
   - `carTypeProject`；
   - `carTypeProjectAll[0]`（是否为内部项目 ID）；
   - `deptName`、`sectionName`；
   - 分页参数、结果数组路径和总数。
4. 导出一次 SOR 结果，记录导出请求路径和列名。

### 必须带回的内容

```text
场景：部门 / 车型项目下拉 / 车型文本 / 车型+部门
项目显示值（脱敏）：
项目内部 ID 形态（仅哈希或末4位）：
请求方法/路径：
关键参数键名和值类型：
状态码/耗时：
响应记录数与记录数组路径：
无结果响应摘要：
导出路径与列名：
```

## 四、推荐采集包结构

```text
production-capture/
  README.md                 # 按本文填写的场景索引
  data-model/
    query-success.json      # 脱敏摘要
    query-empty.json
    export-metadata.json
  sor/
    department-success.json
    project-dropdown.json
    project-success.json
    project-empty.json
    combined-success.json
    export-metadata.json
```

不要放入完整 XLSX/CSV 业务数据；如必须验证列结构，只保留列名、记录数和 1 条已脱敏样例。

## 五、回传前检查

- [ ] 已删除密码、Token、Cookie、Authorization、私钥和完整凭据。
- [ ] 已删除完整业务响应，仅保留字段/参数摘要和脱敏样例。
- [ ] 已标明生产时间、版本号、关联 ID（如有）。
- [ ] 已分别提供成功、无结果、导出三类证据。
- [ ] SOR 车型项目已同时记录显示值与内部 ID 的参数位置。

