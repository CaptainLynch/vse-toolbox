// System query modes as data. A mode is a schema (endpoints, field group,
// number fields, result kind); query.js has one code path for all of them.
//
// ARAS_MODES keeps the legacy app.js ARAS_MODES keys and values verbatim
// (tests/test_plugin_system_query.py compares them), plus `system`/`label`.
// TDC_MODES carries the deliverable workbench TDC forms (TDC_ENDPOINTS and
// the server's _TDC_*_FIELDS) in the same shape.

export const ARAS_BASE_URL = "http://ecm.sgmw.com.cn/innovatorserver";
export const TDC_BASE_URL = "https://tdc.sgmw.com.cn";

const WILDCARD_TITLE = "支持 * 模糊和 | 并集";

function text(name, label, extra = {}) {
  return { name, label, type: "text", ...extra };
}
function date(name, label) {
  return { name, label, type: "date" };
}
function number(name, label, defaultValue) {
  return { name, label, type: "number", min: 1, defaultValue: String(defaultValue) };
}

/** Field groups, mirroring the legacy `data-mode-fields` blocks in dashboard.html. */
export const FIELD_GROUPS = {
  ewo: {
    fields: [
      text("ewo_no", "EWO 编号", { placeholder: "*171|*172", title: WILDCARD_TITLE }),
      text("project_code", "项目代码", { placeholder: "*310S*|*730S*", title: WILDCARD_TITLE }),
      text("subject_keyword", "主题关键词", { placeholder: "*关键词*", title: WILDCARD_TITLE }),
      text("change_type", "变更类型"),
      text("change_sub_type", "变更子类型"),
      text("area", "区域", { placeholder: "*区域*", title: WILDCARD_TITLE }),
      text("state", "状态"),
      text("rsp_department", "响应部门", { placeholder: "*部门*", title: WILDCARD_TITLE }),
      date("submit_start", "提交开始"),
      date("submit_end", "提交结束"),
      number("page", "页码", 1),
      number("page_size", "每页条数", 50),
      number("max_records", "最大记录数", 2000),
    ],
    dateRanges: [["submit_start", "submit_end"]],
  },
  paa: {
    fields: [
      text("paa_no", "PAA 编号", { placeholder: "*编号*", title: WILDCARD_TITLE }),
      text("ewo_no", "EWO 编号", { placeholder: "*编号*", title: WILDCARD_TITLE }),
      text("state", "状态"),
      text("area", "区域", { placeholder: "*区域*", title: WILDCARD_TITLE }),
      text("base", "基地", { placeholder: "*基地*", title: WILDCARD_TITLE }),
      text("department", "业务部门", { placeholder: "技术中心-车体工程", title: WILDCARD_TITLE }),
      text("vehicle_keyword", "车辆关键词", { placeholder: "*310S*|*730S*", title: WILDCARD_TITLE }),
      date("submit_start", "提交开始"),
      date("submit_end", "提交结束"),
      date("mtl_rq_start", "物料需求开始"),
      date("mtl_rq_end", "物料需求结束"),
      number("page", "页码", 1),
      number("page_size", "每页条数", 50),
      number("max_records", "最大记录数", 2000),
      number("max_pages", "最大页数", 20),
    ],
    dateRanges: [["submit_start", "submit_end"], ["mtl_rq_start", "mtl_rq_end"]],
  },
  ncr: {
    fields: [
      date("buy_start", "采购开始"),
      date("buy_end", "采购结束"),
      date("pe_start", "PE 开始"),
      date("pe_end", "PE 结束"),
      text("ncr_no", "NCR 编号", { placeholder: "*编号*", title: "搜索符号将原样传给 NCR 服务" }),
      text("project_names", "项目名称", {
        placeholder: "F610S,F610S DG 或 *610*",
        title: "逗号分隔项目；搜索符号将原样传给 NCR 服务",
        list: true,
      }),
      text("department", "业务部门", { placeholder: "技术中心-车体工程" }),
      text("section_code", "区段代码（高级字段）", {
        note: "系统会把业务部门自动映射为区段代码：BA/BE/BI/EXT/INT/SES/VE",
      }),
      text("change_type", "变更类型"),
      text("othercondition", "其他条件", { defaultValue: "0" }),
    ],
    dateRanges: [["buy_start", "buy_end"], ["pe_start", "pe_end"]],
  },
  "tdc-data-model": {
    fields: [
      // serial_number 是 API 层键名，语义是第 0 列实例号 incident（纯数字），不是流水单号；
      // 流水单号（documentNo）不是 TDC 查询参数，只能全量抓取后本地精确匹配。
      text("serial_number", "实例号(incident)"),
      text("document_no", "流水单号", { placeholder: "例如 3D-00001193；填写后走全量抓取 + 本地精确匹配，较慢" }),
      text("applicant", "申请人"),
      text("department", "部门"),
      text("section", "科室"),
      date("application_start", "申请开始"),
      date("application_end", "申请结束"),
      text("project_model", "项目车型"),
      text("part_number", "零件号"),
      text("model_number", "模型编号"),
      text("status", "状态"),
    ],
    dateRanges: [["application_start", "application_end"]],
  },
  "tdc-sor": {
    fields: [
      text("serial_number", "流水号"),
      text("process_type", "流程类型"),
      text("car_type_project", "车型项目", { placeholder: "例如：E262S（车型项目，可手动输入）", carTypeProject: true }),
      text("applicant", "申请人"),
      text("title", "标题"),
      text("department", "部门"),
      text("section", "科室"),
      date("application_start", "申请开始"),
      date("application_end", "申请结束"),
      text("part_number", "零件号"),
      text("part_name", "零件名称"),
      text("version", "版本"),
      text("sor_number", "SOR 编号"),
      text("latest_completed_node", "最近完成节点"),
      text("approval_status", "审批状态"),
    ],
    dateRanges: [["application_start", "application_end"]],
  },
  "tdc-a-face": { fields: [], dateRanges: [] },
};

/** TDC operation controls shared by all TDC modes (legacy deliverable form). */
export const TDC_OPERATION_FIELDS = [
  number("page", "页码", 1),
  number("page_size", "每页条数", 50),
  number("max_pages", "最大页数（全量）", 100),
  number("max_records", "最大记录数（全量）", 10000),
];

export const TDC_PREVIEW_SOURCES = [
  { value: "list_endpoint", label: "快速查询（list 接口）" },
  { value: "official_export", label: "官方 Excel 精确预览（较慢）" },
];

export const ARAS_MODES = {
  ewo: {
    system: "aras",
    label: "EWO",
    endpoint: "/api/aras/ewo/query",
    exportEndpoint: "/api/aras/ewo/export",
    exportNumberNames: ["max_records", "max_pages"],
    exportLabel: "全量导出 CSV",
    defaultFileName: "aras-ewo-export.csv",
    submitLabel: "查询预览",
    fieldGroup: "ewo",
    filterNames: ["ewo_no", "project_code", "subject_keyword", "change_type", "change_sub_type", "area", "state", "rsp_department", "submit_start", "submit_end"],
    numberNames: ["page", "page_size", "max_records"],
    preferredColumns: ["_no", "_eplmwriteneplcode", "_subject", "_area", "_sort_type", "_rsp_department", "_submit_time", "state"],
    resultKind: "rows",
    xmlCapture: true,
  },
  paa: {
    system: "aras",
    label: "PAA",
    endpoint: "/api/aras/paa/query",
    crawlAllEndpoint: "/api/aras/paa/crawl-all",
    exportEndpoint: "/api/aras/paa/export",
    exportNumberNames: ["max_records", "max_pages"],
    exportLabel: "全量导出 CSV",
    crawlAllLabel: "获取全部结果",
    defaultFileName: "aras-paa-export.csv",
    submitLabel: "查询预览",
    fieldGroup: "paa",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "department", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    numberNames: ["page", "page_size", "max_records", "max_pages"],
    preferredColumns: [],
    resultKind: "rows",
    xmlCapture: true,
  },
  "ncr-progress": {
    system: "aras",
    label: "NCR 进度",
    endpoint: "/api/aras/ncr/progress",
    downloadEndpoint: "/api/aras/ncr/progress/download",
    exportLabel: "生成并下载",
    defaultFileName: "aras-ncr-progress.xlsx",
    submitLabel: "执行查询",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "department", "section_code", "change_type", "othercondition"],
    numberNames: [],
    preferredColumns: [],
    resultKind: "rows",
    preview: true,
  },
  "ncr-detail": {
    system: "aras",
    label: "NCR 明细",
    endpoint: "/api/aras/ncr/detail",
    downloadEndpoint: "/api/aras/ncr/detail/download",
    exportLabel: "生成并下载",
    defaultFileName: "aras-ncr-detail.xlsx",
    submitLabel: "执行查询",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "department", "section_code", "change_type", "othercondition"],
    numberNames: [],
    preferredColumns: [],
    resultKind: "rows",
    preview: true,
  },
};

export const TDC_MODES = {
  "tdc-data-model": {
    system: "tdc",
    label: "TDC 数模",
    title: "TDC 数模设计审核流程报表",
    endpoint: "/api/tdc/data-model/query",
    crawlAllEndpoint: "/api/tdc/data-model/crawl-all",
    exportEndpoint: "/api/tdc/data-model/export",
    exportLabel: "导出 XLSX",
    crawlAllLabel: "全量抓取",
    defaultFileName: "tdc_data_model.xlsx",
    submitLabel: "查询预览",
    fieldGroup: "tdc-data-model",
    filterNames: ["serial_number", "document_no", "applicant", "department", "section", "application_start", "application_end", "project_model", "part_number", "model_number", "status"],
    numberNames: ["page", "page_size"],
    crawlNumberNames: ["page_size", "max_pages", "max_records"],
    preferredColumns: [],
    resultKind: "rows",
    previewSource: true,
  },
  "tdc-sor": {
    system: "tdc",
    label: "TDC SOR",
    title: "TDC SOR 流程报表",
    endpoint: "/api/tdc/sor/query",
    crawlAllEndpoint: "/api/tdc/sor/crawl-all",
    exportEndpoint: "/api/tdc/sor/export",
    carTypeProjectsEndpoint: "/api/tdc/sor/car-type-projects",
    exportLabel: "导出 XLSX",
    crawlAllLabel: "全量抓取",
    defaultFileName: "tdc_sor_part_details.xlsx",
    submitLabel: "查询预览",
    fieldGroup: "tdc-sor",
    filterNames: ["serial_number", "process_type", "car_type_project", "applicant", "title", "department", "section", "application_start", "application_end", "part_number", "part_name", "version", "sor_number", "latest_completed_node", "approval_status"],
    numberNames: ["page", "page_size"],
    crawlNumberNames: ["page_size", "max_pages", "max_records"],
    preferredColumns: [],
    resultKind: "rows",
    previewSource: true,
  },
  "tdc-a-face": {
    system: "tdc",
    label: "TDC A 面",
    title: "TDC A 面",
    endpoint: "/api/tdc/a-face/query",
    crawlAllEndpoint: "/api/tdc/a-face/crawl-all",
    exportEndpoint: "/api/tdc/a-face/export",
    exportLabel: "导出 XLSX",
    crawlAllLabel: "全量抓取",
    defaultFileName: "tdc_a_face.xlsx",
    submitLabel: "查询预览",
    fieldGroup: "tdc-a-face",
    filterNames: [],
    numberNames: ["page", "page_size"],
    crawlNumberNames: ["page_size", "max_pages", "max_records"],
    preferredColumns: [],
    resultKind: "rows",
    blockedNotice: "TDC A 面契约待验证/阻断：服务端暂不执行查询，操作会返回契约阻断说明。",
  },
};

export const MODES = { ...ARAS_MODES, ...TDC_MODES };
export const MODE_IDS = Object.keys(MODES);
export const DEFAULT_MODE = "ewo";

export const SYSTEMS = [
  { id: "aras", title: "Aras", baseUrl: ARAS_BASE_URL },
  { id: "tdc", title: "TDC", baseUrl: TDC_BASE_URL },
];

export const COMMAND_LABELS = Object.fromEntries(MODE_IDS.map((id) => [id, MODES[id].label]));

export const RESULT_KIND_LABELS = { rows: "列表", summary: "摘要" };

/** Deep-link aliases (legacy handleHashChange accepted these spellings). */
export const MODE_ALIASES = {
  tdc_sor: "tdc-sor",
  sor: "tdc-sor",
  tdc_data_model: "tdc-data-model",
  "data-model": "tdc-data-model",
  tdc_a_face: "tdc-a-face",
  "a-face": "tdc-a-face",
};

/** Deep-link identifier param per field group → the field it fills. */
export const DEEP_LINK_FIELDS = {
  ewo: { param: "ewo_no", field: "ewo_no" },
  paa: { param: "paa_no", field: "paa_no" },
  ncr: { param: "ncr_no", field: "ncr_no", altParams: ["ncrNo"] },
  "tdc-data-model": { param: "serial_number", field: "serial_number" },
  "tdc-sor": { param: "serial_number", field: "serial_number" },
};
