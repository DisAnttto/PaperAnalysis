/* ============================================================
   MedLit QA Console — app.js
   Vanilla JS, no dependencies.
   ============================================================ */

"use strict";

// ── State ──────────────────────────────────────────────────────────────────
let _results              = [];    // final ranked results (populated on stream done)
let _streamedResults      = [];    // partial results during streaming (cleared on done)
let _evDetailOpen         = null;  // idx of open evidence detail row, or null
let _sortCol              = "rank";
let _sortDir              = "asc";
let _detailData           = {};    // pmid -> {paper, extraction, normalized, ranked}
/** PMID string when an inline detail row is open under the results table; null if closed. */
let _detailOpenPmid       = null;
let _metricsOfInterest    = [];    // list of {name: string, value: string} objects
let _lang                 = "en";  // "en" | "zh"
let _healthData           = null;  // last /health response
let _searchAbortController = null; // AbortController for the active stream
/** @type {Record<string, { id: string, name: string, request: object, golden_pmids?: string[], expectations?: object }>} */
let _goldCasesById = {};
/** ID of the currently active gold case (null when no gold case is selected). */
let _activeGoldCaseId = null;

// ── i18n ───────────────────────────────────────────────────────────────────
const _T = {
  // App / status bar
  brand:            { en: "MedLit QA Console",        zh: "MedLit 医学文献分析台" },
  btn_try_example:  { en: "Try Example",              zh: "示例" },
  btn_clear_all_work: { en: "Clear all work",          zh: "清空工作台" },

  // Search panel
  search_heading:   { en: "Search",                   zh: "搜索" },
  presets_label:    { en: "Presets:",                 zh: "预设：" },
  label_gold_cases: { en: "Gold test cases",          zh: "黄金测试用例" },
  opt_gold_case_none: { en: "— Select a gold case —", zh: "— 选择黄金用例 —" },
  label_keywords:   { en: "Keywords (optional)",      zh: "关键词（可选）" },
  ph_keywords:      { en: "e.g. 39350227 or TIAB phrase", zh: "例如 39350227 或 TIAB 短语" },
  hint_keywords:    { en: "Comma-separated; numbers pin PMID via [UID].", zh: "逗号分隔；纯数字将按 PMID [UID] 限定。" },
  preset_iol:       { en: "Hydrophobic IOL",          zh: "疏水丙烯酸 IOL" },
  preset_faricimab: { en: "Faricimab nAMD",           zh: "法瑞西单抗 nAMD" },
  preset_glaucoma:  { en: "Glaucoma Device",          zh: "青光眼器械" },
  preset_dexa:      { en: "Dexamethasone DME",        zh: "地塞米松 DME" },
  preset_contact:   { en: "Contact Lens DED",         zh: "接触镜干眼" },

  label_query:           { en: "Query",               zh: "查询" },
  ph_query:              { en: "e.g. intraocular lens cataract outcomes", zh: "例如 白内障 人工晶体 手术效果" },
  label_target_type:     { en: "Target type",         zh: "目标类型" },
  opt_device:            { en: "device",              zh: "器械" },
  opt_drug:              { en: "drug",                zh: "药物" },
  opt_both:              { en: "both",                zh: "两者" },

  // Device fields
  summary_device:            { en: "Device fields",       zh: "器械字段" },
  label_product_name:        { en: "Product name",         zh: "产品名称" },
  ph_product_name:           { en: "e.g. AcrySof IQ",      zh: "例如 AcrySof IQ" },
  label_device_category:     { en: "Device category",      zh: "器械类别" },
  ph_device_category:        { en: "e.g. intraocular_lens", zh: "例如 intraocular_lens" },
  label_manufacturer:        { en: "Manufacturer",         zh: "制造商" },
  ph_manufacturer:           { en: "e.g. Alcon",           zh: "例如 Alcon" },
  label_intended_use:        { en: "Intended use",         zh: "预期用途" },
  ph_intended_use:           { en: "e.g. cataract surgery", zh: "例如 白内障手术" },
  label_indications:         { en: "Indications",          zh: "适应症" },
  ph_indications:            { en: "e.g. cataract, glaucoma", zh: "例如 白内障、青光眼" },
  hint_comma_sep:            { en: "(comma-sep)",           zh: "（逗号分隔）" },
  label_anatomical_site:     { en: "Anatomical site",      zh: "解剖部位" },
  ph_anatomical_site:        { en: "e.g. lens_capsule",    zh: "例如 lens_capsule" },
  label_material_family:     { en: "Material family",      zh: "材料大类" },
  ph_material_family:        { en: "e.g. acrylic",         zh: "例如 acrylic" },
  label_material_subtype:    { en: "Material subtype",     zh: "材料子类" },
  ph_material_subtype:       { en: "e.g. hydrophobic_acrylic", zh: "例如 hydrophobic_acrylic" },
  label_material_features:   { en: "Material features",   zh: "材料特性" },
  ph_material_features:      { en: "e.g. aspheric, uv_filter", zh: "例如 aspheric、uv_filter" },
  label_key_features:        { en: "Key features",        zh: "关键特性" },
  ph_key_features:           { en: "e.g. trifocal, PanOptix", zh: "例如 trifocal、PanOptix" },

  // Drug fields
  summary_drug:              { en: "Drug fields",          zh: "药物字段" },
  label_active_ingredient:   { en: "Active ingredient",    zh: "活性成分" },
  ph_active_ingredient:      { en: "e.g. ranibizumab",     zh: "例如 ranibizumab" },
  label_drug_class:          { en: "Drug class",           zh: "药物分类" },
  ph_drug_class:             { en: "e.g. anti_vegf",       zh: "例如 anti_vegf" },
  label_route:               { en: "Route",                zh: "给药途径" },
  ph_route:                  { en: "e.g. intravitreal",    zh: "例如 玻璃体内注射" },

  // Metrics of Interest
  summary_metrics:    { en: "Metrics of Interest",  zh: "关注指标" },
  preset_cataract:    { en: "Cataract / IOL",        zh: "白内障 / IOL" },
  preset_retina:      { en: "Anti-VEGF / Retina",    zh: "抗VEGF / 视网膜" },
  preset_glaucoma_m:  { en: "Glaucoma",              zh: "青光眼" },
  ph_metric_input:    { en: "e.g. BCVA, IOP, injection frequency", zh: "例如 BCVA、IOP、注射频率" },
  btn_add:            { en: "Add",                   zh: "添加" },
  btn_clear_all:      { en: "Clear all",             zh: "清除全部" },
  metric_value_ph:    { en: "e.g. 20 mmHg",              zh: "如 20 mmHg" },
  metric_count_n:     {
    en: (n) => `${n} metric${n > 1 ? "s" : ""} added`,
    zh: (n) => `已添加 ${n} 项指标`,
  },

  // Filters
  summary_filters:   { en: "Search Filters",          zh: "搜索筛选" },
  summary_dev_shortcuts: { en: "QA presets & gold cases", zh: "QA 预设与黄金用例" },
  label_num_papers:  { en: "Number of papers",        zh: "论文数量" },
  label_pool_size:   { en: "Pool size (per database)", zh: "每数据库检索池大小" },
  opt_pool_50:       { en: "50 papers",              zh: "50 篇" },
  opt_pool_100:      { en: "100 papers",             zh: "100 篇" },
  opt_pool_200:      { en: "200 papers",             zh: "200 篇" },
  opt_5_papers:      { en: "5 papers",               zh: "5 篇" },
  opt_10_papers:     { en: "10 papers",              zh: "10 篇" },
  opt_20_papers:     { en: "20 papers",              zh: "20 篇" },
  opt_50_papers:     { en: "50 papers",              zh: "50 篇" },
  label_year_range:  { en: "Publication year range", zh: "发表年份范围" },
  ph_year_from:      { en: "From",                   zh: "起始年份" },
  ph_year_to:        { en: "To",                     zh: "截止年份" },
  label_country:     { en: "Country / affiliation",  zh: "国家 / 机构" },
  ph_country:        { en: "e.g. United States, China", zh: "例如 China、United States" },

  // Weights
  summary_weights:   { en: "Ranking weights",         zh: "排名权重" },
  weight_R:          { en: "Relevance (R)",           zh: "相关性 (R)" },
  weight_P:          { en: "Product sim (P)",         zh: "产品相似度 (P)" },
  weight_M:          { en: "Metric favor (M)",        zh: "指标匹配度 (M)" },
  weight_E:          { en: "Evidence (E)",            zh: "证据质量 (E)" },
  warning_weights:   { en: "Weights must sum to 1.0", zh: "权重之和必须为 1.0" },
  warning_pool_size: {
    en: "Pool size must be at least the number of papers to extract.",
    zh: "检索池大小必须不小于要提取的论文数量。",
  },

  // Buttons
  btn_run_search:    { en: "Run Search",   zh: "开始搜索" },
  btn_clear:         { en: "Clear",        zh: "清除" },

  // Evidence tab
  tab_search:             { en: "Literature Search",                                           zh: "文献搜索" },
  tab_evidence:           { en: "Correlated Evidence",                                         zh: "关联证据" },
  ev_heading:             { en: "Correlated Evidence",                                         zh: "关联证据检索" },
  ev_label_seed:          { en: "Seed identifier",                                             zh: "种子标识符" },
  ev_summary_profile:     { en: "Profile (optional)",                                          zh: "产品信息（可选）" },
  ev_label_product_name:  { en: "Product name",                                                zh: "产品名称" },
  ev_label_ingredient:    { en: "Active ingredient / device",                                  zh: "活性成分 / 器械名称" },
  ev_label_route:         { en: "Route",                                                       zh: "给药途径" },
  ev_label_indication:    { en: "Indication (comma-sep)",                                      zh: "适应症（逗号分隔）" },
  ev_label_endpoints:     { en: "Key endpoints (comma-sep)",                                   zh: "关键终点（逗号分隔）" },
  ev_label_product_type:  { en: "Product type",                                                zh: "产品类型" },
  ev_opt_unknown:         { en: "Unknown",                                                     zh: "未知" },
  ev_btn_run:             { en: "Find Evidence",                                               zh: "查找证据" },
  ev_progress_msg:        { en: "Searching all sources\u2026",                                 zh: "正在检索所有数据源\u2026" },
  ev_sources_label:       { en: "Sources:",                                                    zh: "数据源：" },
  ev_results_heading:     { en: "Evidence Results",                                            zh: "证据结果" },
  ev_col_source:          { en: "Source",                                                      zh: "数据源" },
  ev_col_tier:            { en: "Tier",                                                        zh: "层级" },
  ev_col_identifier:      { en: "Identifier",                                                  zh: "标识符" },
  ev_col_corr:            { en: "Corr",                                                        zh: "相关度" },
  ev_col_strength:        { en: "Strength",                                                    zh: "证据强度" },
  ev_col_expl:            { en: "Expl",                                                        zh: "解释价值" },
  ev_col_relation:        { en: "Relation",                                                    zh: "关系类型" },
  ev_empty_state:         { en: "Enter a seed identifier above and click Find Evidence.",      zh: "请输入种子标识符并点击「查找证据」。" },
  ev_presets_label:       { en: "Evidence seeds:",                                            zh: "证据种子：" },
  ev_seed_hint:           { en: "PMID, 510(k) K-number, NCT, PMA, DEN — fans out to all databases.", zh: "支持 PMID、510(k) K 号、NCT、PMA、DEN，自动跨库检索。" },
  ev_preset_faricimab:    { en: "Faricimab nAMD",                                             zh: "法瑞西单抗 nAMD" },
  ev_preset_ozurdex:      { en: "Ozurdex DME",                                                zh: "Ozurdex DME" },
  ev_preset_panoptix:     { en: "PanOptix IOL",                                               zh: "PanOptix IOL" },
  ev_preset_idxdr:        { en: "IDx-DR De Novo",                                             zh: "IDx-DR 创新分类" },
  ev_preset_kardia:       { en: "KardiaMobile 510(k)",                                        zh: "KardiaMobile 510(k)" },

  btn_stop:          { en: "Stop",         zh: "停止" },
  btn_close:         { en: "✕ Close",      zh: "✕ 关闭" },
  btn_copy:          { en: "Copy",         zh: "复制" },
  btn_copied:        { en: "Copied!",      zh: "已复制！" },
  lang_toggle:       { en: "中文",          zh: "English" },
  prog_stopped:      { en: "Search stopped — showing partial results.", zh: "搜索已停止 — 显示部分结果。" },

  // Table headers
  col_rank:      { en: "#",        zh: "#" },
  col_title:     { en: "Title",    zh: "标题" },
  col_year:      { en: "Year",     zh: "年份" },
  col_pmid:      { en: "PMID",     zh: "PMID" },
  col_score:     { en: "Score",    zh: "综合分" },
  col_R:         { en: "Relevance", zh: "相关性" },
  col_R_title:   { en: "Relevance — query & topic match",           zh: "相关性 — 查询与主题匹配度" },
  col_P:         { en: "Product",   zh: "产品相似度" },
  col_P_title:   { en: "Product Similarity — device/drug match",    zh: "产品相似度 — 器械/药物匹配" },
  col_M:         { en: "Metric",    zh: "指标匹配度" },
  col_M_title:   { en: "Metric Favorability — target metric match", zh: "指标匹配度 — 目标指标符合程度" },
  col_E:         { en: "Evidence",  zh: "证据质量" },
  col_E_title:   { en: "Evidence Quality — study design & sample size", zh: "证据质量 — 研究设计与样本量" },
  col_metrics:   { en: "Metrics of Interest", zh: "关注指标" },
  col_metrics_title: {
    en: "When you list metrics of interest only (no structured target metrics), each chip shows whether that name counted toward the Metric (M) score — same rules as the ranker (synonyms & token match on extracted names).",
    zh: "仅填写关注指标（未设置结构化目标指标）时，每个标签是否与 Metric (M) 列计分一致 — 与排名器相同（同义词与分词匹配提取名称）。",
  },
  col_rationale: { en: "Rationale", zh: "排名依据" },

  // Results header
  results_heading:   { en: "Results",   zh: "结果" },

  // Progress messages (some are functions for interpolation)
  prog_connecting:   { en: "Connecting…",       zh: "连接中…" },
  prog_searching:    { en: "Searching all databases…", zh: "正在搜索所有数据库…" },
  prog_no_papers:    { en: "No papers found.",  zh: "未找到相关论文。" },
  prog_found: {
    en: (n) => `Found ${n} paper${n !== 1 ? "s" : ""}. Starting extraction…`,
    zh: (n) => `找到 ${n} 篇论文，开始提取…`,
  },
  prog_triaging: {
    en: (pool, n) => `Found ${pool} papers. AI selecting top ${n}…`,
    zh: (pool, n) => `找到 ${pool} 篇论文。AI 正在筛选前 ${n} 篇…`,
  },
  prog_triage_done: {
    en: (n) => `Triage complete — extracting ${n} paper${n !== 1 ? "s" : ""}…`,
    zh: (n) => `筛选完成 — 正在提取 ${n} 篇论文…`,
  },
  prog_extracting: {
    en: (cur, tot, title) => `Extracting ${cur}/${tot} — ${title}`,
    zh: (cur, tot, title) => `提取中 ${cur}/${tot} — ${title}`,
  },
  prog_processed: {
    en: (cur, tot) => `Processed ${cur}/${tot || "?"} papers`,
    zh: (cur, tot) => `已处理 ${cur}/${tot || "?"} 篇`,
  },
  prog_done: {
    en: (n) => `Done — ${n} paper${n !== 1 ? "s" : ""} ranked`,
    zh: (n) => `完成 — 已对 ${n} 篇论文排名`,
  },
  count_so_far: {
    en: (n) => `(${n} paper${n !== 1 ? "s" : ""} so far…)`,
    zh: (n) => `(已处理 ${n} 篇…)`,
  },
  count_final: {
    en: (n) => `(${n} paper${n !== 1 ? "s" : ""})`,
    zh: (n) => `(共 ${n} 篇)`,
  },

  // Pipeline stepper
  step_pubmed_title:  { en: "Database Search",  zh: "数据库检索" },
  step_triage_title:  { en: "AI Triage",      zh: "AI 筛选" },
  step_extract_title: { en: "Extract + Score", zh: "提取 + 评分" },
  step_pubmed_active: { en: "Searching all databases…", zh: "正在搜索所有数据库…" },
  step_pubmed_done: {
    en: (n) => `${n} result${n !== 1 ? "s" : ""} fetched`,
    zh: (n) => `已获取 ${n} 条结果`,
  },
  step_triage_active: {
    en: (pool, n) => `Selecting top ${n} from ${pool} papers…`,
    zh: (pool, n) => `从 ${pool} 篇中筛选前 ${n} 篇…`,
  },
  step_triage_done: {
    en: (n) => `${n} paper${n !== 1 ? "s" : ""} selected`,
    zh: (n) => `已选出 ${n} 篇论文`,
  },
  step_triage_summary: {
    en: (sel, tot) => `Selected ${sel} of ${tot} papers for extraction.`,
    zh: (sel, tot) => `已从 ${tot} 篇中选出 ${sel} 篇进入提取。`,
  },
  step_extract_active: {
    en: (cur, tot) => `Extracting ${cur} / ${tot}…`,
    zh: (cur, tot) => `提取中 ${cur} / ${tot}…`,
  },
  step_extract_done: {
    en: (n) => `${n} paper${n !== 1 ? "s" : ""} ranked`,
    zh: (n) => `${n} 篇论文已排名`,
  },
  step_demo_pubmed_done: { en: "Demo fixtures", zh: "演示数据" },

  // Detail panel headings
  detail_metadata:        { en: "Paper Metadata",        zh: "论文元数据" },
  detail_abstract_h:      { en: "Abstract",              zh: "摘要" },
  no_abstract:            { en: "(no abstract)",         zh: "（无摘要）" },
  detail_ranking_h:       { en: "Ranking Breakdown",     zh: "排名分解" },
  detail_norm_fields_h:   { en: "Normalized Fields",     zh: "标准化字段" },
  detail_metrics_h:       { en: "Extracted Metrics",     zh: "提取指标" },
  detail_extraction_h:    { en: "Extraction Result",     zh: "提取结果" },
  detail_normalized_h:    { en: "Normalized Product",    zh: "标准化产品" },
  detail_links_h:         { en: "View paper",              zh: "查看论文" },
  link_pubmed:            { en: "PubMed",                  zh: "PubMed" },
  link_doi:               { en: "DOI resolver",            zh: "DOI 解析" },
  link_publisher:         { en: "Article page",            zh: "文章页面" },
  no_paper_link:          { en: "No external link available (numeric PMID or DOI needed).", zh: "暂无外部链接（需要数字 PMID 或 DOI）。" },

  // Normalized fields table labels
  nf_field:             { en: "Field",              zh: "字段" },
  nf_normalized:        { en: "Normalized value",   zh: "标准化值" },
  nf_signal_score:      { en: "Signal score",       zh: "信号分" },
  nf_device_category:   { en: "Device category",    zh: "器械类别" },
  nf_material_family:   { en: "Material family",    zh: "材料大类" },
  nf_material_subtype:  { en: "Material subtype",   zh: "材料子类" },
  nf_material_features: { en: "Material features",  zh: "材料特性" },
  nf_anatomical_site:   { en: "Anatomical site",    zh: "解剖部位" },
  nf_indications:       { en: "Indications",        zh: "适应症" },
  nf_product_name:      { en: "Product name",       zh: "产品名称" },
  nf_manufacturer:      { en: "Manufacturer",       zh: "制造商" },
  nf_key_features:      { en: "Key features",       zh: "关键特性" },
  nf_ingredient:        { en: "Active ingredient",  zh: "活性成分" },
  nf_drug_class:        { en: "Drug class",         zh: "药物分类" },
  nf_route:             { en: "Route",              zh: "给药途径" },
  nf_formulation:       { en: "Formulation features", zh: "制剂特性" },
  nf_confidence:        { en: "Confidence",         zh: "置信度" },
  nf_no_data:           { en: "No normalized product data for this paper.", zh: "本文无标准化产品数据。" },

  // Breakdown dimension labels
  dim_composite:  { en: "Composite",        zh: "综合分" },
  dim_R:          { en: "Relevance (R)",    zh: "相关性 (R)" },
  dim_P:          { en: "Product sim (P)",  zh: "产品相似度 (P)" },
  dim_M:          { en: "Metric favor (M)", zh: "指标匹配度 (M)" },
  dim_E:          { en: "Evidence (E)",     zh: "证据质量 (E)" },
  bd_dimension:   { en: "Dimension",        zh: "维度" },
  bd_score:       { en: "Score",            zh: "得分" },
  bd_weight:      { en: "Weight",           zh: "权重" },

  // Flags
  flag_excluded:      { en: "excluded: ",                 zh: "已排除：" },
  flag_metric_est:    { en: "metric scores estimated",    zh: "指标分数为估算值" },
  flag_metric_incomp: { en: "metric scores incomplete",   zh: "指标分数不完整" },
  flag_evidence_est:  { en: "evidence score estimated",   zh: "证据分数为估算值" },

  // Meta keys in detail panel
  meta_pmid:      { en: "PMID",       zh: "PMID" },
  meta_doi:       { en: "DOI",        zh: "DOI" },
  meta_journal:   { en: "Journal",    zh: "期刊" },
  meta_published: { en: "Published",  zh: "发表日期" },
  meta_authors:   { en: "Authors",    zh: "作者" },
  meta_mesh:      { en: "MeSH terms", zh: "MeSH 术语" },
  meta_keywords:  { en: "Keywords",   zh: "关键词" },

  // Metrics table headers
  mth_metric:   { en: "Metric",   zh: "指标" },
  mth_value:    { en: "Value",    zh: "数值" },
  mth_category: { en: "Category", zh: "类别" },
  mth_evidence: { en: "Evidence", zh: "证据" },

  // Metric match badge tooltip
  metric_match_tip: {
    en: (n, t) => `${n} of your ${t} metrics found`,
    zh: (n, t) => `找到 ${t} 项关注指标中的 ${n} 项`,
  },
  moi_none_specified: { en: "none specified", zh: "未指定指标" },
  moi_not_found:      { en: "not found",      zh: "未找到" },
  moi_pill_m: {
    en: "Counted toward Metric (M) score",
    zh: "已计入指标匹配度 (M)",
  },
  moi_not_counts_m: {
    en: "Not counted toward Metric (M)",
    zh: "未计入指标匹配度 (M)",
  },
  moi_cell_coverage_tip: {
    en: (ratio) =>
      `M uses coverage ${ratio}. “M” badge = counted; strikethrough = not counted (synonym/token rules on extracted metric names).`,
    zh: (ratio) =>
      `M 按覆盖率 ${ratio} 计分。带 “M” 角标 = 已计入；删除线 = 未计入（对提取指标名称做同义词/分词匹配）。`,
  },
  moi_extracted_no_display_value: {
    en: "extracted but no value to display here",
    zh: "已提取但此处无可用数值",
  },
  rel_high:    { en: "HIGH",    zh: "高" },
  rel_medium:  { en: "MEDIUM",  zh: "中" },
  rel_low:     { en: "LOW",     zh: "低" },

  // Health chips
  health_prefix:  { en: "health: ", zh: "健康：" },
  mode_prefix:    { en: "mode: ",   zh: "模式：" },
  pubmed_live:    { en: "live",     zh: "实时" },
  pubmed_mocked:  { en: "mocked",   zh: "模拟" },

  // Empty state
  empty_state: {
    en: 'Parse a finding above, fill the search fields, or expand <strong>QA presets &amp; gold cases</strong> — then click <strong>Run Search</strong>.',
    zh: '在上方解析发现、填写搜索项，或展开<strong>QA 预设与黄金用例</strong>，然后点击<strong>开始搜索</strong>。',
  },

  // Error
  err_detail: { en: "Failed to load detail: ", zh: "加载详情失败：" },

  // Natural-language chat box
  nl_label:               { en: "Describe your finding",             zh: "描述您的临床发现" },
  nl_placeholder:         { en: "e.g. Postop day 1 IOP was 20 mmHg in the test group vs 18 mmHg in control, statistically significant", zh: "例如：术后1天试验组眼压20mmHg，对照组18mmHg，两组间存在统计学差异" },
  btn_nl_parse:           { en: "Parse Finding",                     zh: "解析" },
  nl_parsing:             { en: "Parsing\u2026",                     zh: "解析中\u2026" },
  nl_done:                { en: "Fields filled",                     zh: "已填充字段" },
  nl_done_n: {
    en: (n) => `${n} field${n > 1 ? "s" : ""} filled`,
    zh: (n) => `已填充 ${n} 个字段`,
  },
  nl_nothing:             { en: "Nothing extracted — try adding product name, metric, or PMID", zh: "未提取到字段，请尝试添加产品名称、指标或 PMID" },
  nl_error:               { en: "Parse failed",                      zh: "解析失败" },
  nl_timeout:             { en: "Parse timed out (45 s) — try a shorter input", zh: "解析超时（45 秒），请缩短输入" },

  nl_preview_summary:     { en: "Parse breakdown (step 1)",           zh: "解析分解（第一步）" },
  nl_preview_specs:       { en: "Paper / product specs",             zh: "文献/产品要点" },
  nl_preview_finding:       { en: "Clinical finding (metric)",         zh: "临床发现（指标）" },
  nl_preview_intent:        { en: "Search intent (papers to find)",    zh: "检索意图（要找的文献）" },
  nl_preview_empty:         { en: "—",                                 zh: "—" },
  nl_prev_name_source:      { en: "Product (as written)",            zh: "产品（原文）" },
  nl_prev_name:             { en: "Product (English)",               zh: "产品（英文）" },
  nl_prev_type:             { en: "Type",                            zh: "类型" },
  nl_prev_manufacturer:     { en: "Manufacturer",                    zh: "生产商" },
  nl_prev_category:         { en: "Category",                        zh: "类别" },
  nl_prev_intended_use:     { en: "Intended use",                    zh: "预期用途" },
  nl_prev_indications:      { en: "Indications",                     zh: "适应症" },
  nl_prev_procedure:        { en: "Procedure",                     zh: "术式/操作" },
  nl_prev_active_ingredient:{ en: "Active ingredient",               zh: "活性成分" },
  nl_prev_drug_class:       { en: "Drug class",                      zh: "药物类别" },
  nl_prev_route:            { en: "Route",                           zh: "给药途径" },
  nl_prev_metric:           { en: "Metric",                        zh: "指标" },
  nl_prev_unit:             { en: "Unit",                          zh: "单位" },
  nl_prev_timepoint:        { en: "Timepoint",                     zh: "时间点" },
  nl_prev_observed:         { en: "Test / observed",                 zh: "试验组/观测值" },
  nl_prev_control:          { en: "Control",                       zh: "对照" },
  nl_prev_significant:      { en: "Statistically significant",     zh: "统计学差异" },
};

/** Translate a key, optionally calling with interpolation args if the value is a function. */
function _t(key, ...args) {
  const entry = _T[key];
  if (!entry) return key;
  const val = entry[_lang] ?? entry.en ?? key;
  return typeof val === "function" ? val(...args) : val;
}

// ── Language toggle ─────────────────────────────────────────────────────────
function toggleLang() {
  _lang = _lang === "en" ? "zh" : "en";
  _applyLang();
}

function _applyLang() {
  document.documentElement.lang = _lang === "zh" ? "zh-CN" : "en";

  // Update textContent for all data-i18n elements
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.dataset.i18n;
    const val = _T[key];
    if (!val) return;
    const text = val[_lang] ?? val.en;
    if (typeof text === "string") {
      // Some keys have HTML (e.g. empty_state) — use innerHTML, others use textContent
      if (text.includes("<")) {
        el.innerHTML = text;
      } else {
        el.textContent = text;
      }
    }
  });

  // Update placeholder attributes
  document.querySelectorAll("[data-i18n-ph]").forEach(el => {
    el.placeholder = _t(el.dataset.i18nPh);
  });

  // Update title attributes
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    el.title = _t(el.dataset.i18nTitle);
  });

  // Update lang toggle button
  const langBtn = document.getElementById("btn-lang");
  if (langBtn) langBtn.textContent = _t("lang_toggle");

  // Re-render health chips if we have data
  if (_healthData) _updateHealthChips(_healthData);

  // Re-render metric chip count text
  _renderMetricChips();

  // Re-render results table if any results exist
  if (_results.length > 0 || _streamedResults.length > 0) {
    _renderTableBody();
  }

  // Re-render inline detail row if it is open
  if (_detailOpenPmid && _detailData[_detailOpenPmid]) {
    _renderDetail(_detailOpenPmid);
  }
}

// ── Presets ────────────────────────────────────────────────────────────────
const PRESETS = {
  iol_hydrophobic: {
    query:           "hydrophobic acrylic intraocular lens cataract",
    target_type:     "device",
    product_name:    "AcrySof IQ",
    device_category: "intraocular_lens",
    indications:     "cataract",
    material_family: "acrylic",
    material_subtype:"hydrophobic_acrylic",
    material_features:"aspheric, uv_filter",
    active_ingredient:"",
    drug_class:      "",
    route:           "",
    metrics:         ["BCVA", "UDVA", "IOP", "endothelial cell loss", "posterior capsule opacification", "refractive prediction error"],
  },
  // Gold inputs curated from PMID 39350227 abstract (Grimaldi et al., 2024).
  // Live regression JSON: tests/collection/cases.json (id faricimab_namd_39350227).
  faricimab_namd: {
    query:           "intravitreal faricimab treatment-naive nAMD prospective real-world",
    pool_size:       30,
    max_results:     5,
    target_type:     "drug",
    product_name:    "faricimab",
    device_category: "",
    intended_use:    "efficacy, safety and durability of intravitreal faricimab in treatment-naive neovascular AMD (real-world prospective cohort)",
    indications:     "nAMD, neovascular age-related macular degeneration, treatment-naive",
    material_family: "",
    material_subtype: "",
    material_features: "",
    active_ingredient: "faricimab",
    drug_class:      "anti_vegf",
    route:           "intravitreal",
    metrics: [
      "BCVA",
      "CST",
      "macular volume",
      "dry macula",
      "injection interval",
    ],
  },
  glaucoma_device: {
    query:           "iStent MIGS glaucoma trabecular",
    target_type:     "device",
    product_name:    "iStent",
    device_category: "glaucoma_device",
    indications:     "glaucoma",
    material_family: "",
    material_subtype:"",
    material_features:"",
    active_ingredient:"",
    drug_class:      "",
    route:           "",
    metrics:         ["IOP reduction", "IOP", "visual field mean deviation", "RNFL thickness", "medication count", "surgical success rate"],
  },
  dexa_dme: {
    query:           "dexamethasone intravitreal diabetic macular edema",
    target_type:     "drug",
    product_name:    "Ozurdex",
    device_category: "",
    indications:     "diabetic_macular_edema",
    material_family: "",
    material_subtype:"",
    material_features:"",
    active_ingredient:"dexamethasone",
    drug_class:      "corticosteroid",
    route:           "intravitreal",
    metrics:         ["BCVA change", "central retinal thickness", "injection frequency", "retinal fluid resolution"],
  },
  contact_dry_eye: {
    query:           "drug-eluting contact lens dry eye cyclosporine",
    target_type:     "both",
    product_name:    "",
    device_category: "contact_lens",
    indications:     "dry_eye",
    material_family: "hydrogel",
    material_subtype:"silicone_hydrogel",
    material_features:"drug_eluting",
    active_ingredient:"cyclosporine",
    drug_class:      "immunomodulator",
    route:           "topical",
    metrics:         ["TBUT", "Schirmer score", "OSDI score", "corneal staining", "symptom score"],
  },
};

// ── Metric presets ─────────────────────────────────────────────────────────
const METRIC_PRESETS = {
  cataract_iol: [
    "BCVA", "UDVA", "IOP",
    "endothelial cell loss", "posterior capsule opacification",
    "refractive prediction error",
  ],
  antivegf_retina: [
    "BCVA change",
    "central retinal thickness",
    "retinal fluid resolution",
    "complete dryness rate",
    "treatment interval",
    "injection frequency",
  ],
  glaucoma: [
    "IOP reduction", "IOP", "visual field mean deviation",
    "RNFL thickness", "medication count", "surgical success rate",
  ],
};

// ── Gold case validation ────────────────────────────────────────────────────

/**
 * Glaucoma-procedure title terms — mirrors app/services/triage and
 * tests/collection/checks. Must be kept in sync manually.
 */
const _GLAUCOMA_PROCEDURE_TERMS = [
  "trabeculectomy",
  "trabeculotomy",
  "goniotomy",
  "goniosynechialysis",
  "canaloplasty",
  "viscocanalostomy",
  "gatt",
  "trabectome",
];

/**
 * Run client-side validation of search results against gold expectations.
 * Returns { passed: bool, checks: [{label, passed, detail}] }.
 */
function _runGoldValidation(results, expectations) {
  const checks = [];

  const pmidToRow = {};
  for (const r of results) {
    if (r.pmid != null) pmidToRow[String(r.pmid)] = r;
  }

  const goldenPmids = expectations.golden_pmids || [];
  const goldenSet = new Set(goldenPmids);

  // 1. Golden PMID presence
  for (const pmid of goldenPmids) {
    const present = pmid in pmidToRow;
    checks.push({
      label: `Anchor PMID ${pmid} present in results`,
      passed: present,
      detail: present ? `rank ${pmidToRow[pmid].rank}` : "not found",
    });
  }

  // 2. Composite score floors
  const minComposite = expectations.min_composite_by_pmid || {};
  for (const [pmid, minC] of Object.entries(minComposite)) {
    if (goldenSet.has(pmid)) continue; // already checked in presence above
    const row = pmidToRow[pmid];
    if (!row) {
      checks.push({ label: `PMID ${pmid} composite ≥ ${minC}`, passed: false, detail: "not in results" });
    } else {
      const got = parseFloat(row.composite_score ?? 0);
      checks.push({
        label: `PMID ${pmid} composite ≥ ${minC}`,
        passed: got >= minC,
        detail: `got ${got.toFixed(3)}`,
      });
    }
  }

  // Composite floors for golden PMIDs (combined check)
  for (const pmid of goldenPmids) {
    if (!(pmid in minComposite)) continue;
    const row = pmidToRow[pmid];
    if (!row) continue; // already failed presence check
    const minC = minComposite[pmid];
    const got = parseFloat(row.composite_score ?? 0);
    checks.push({
      label: `PMID ${pmid} composite ≥ ${minC}`,
      passed: got >= minC,
      detail: `got ${got.toFixed(3)}`,
    });
  }

  // 3. Rank ceilings
  const maxRank = expectations.max_rank_by_pmid || {};
  for (const pmid of goldenPmids) {
    if (!(pmid in maxRank)) continue;
    const row = pmidToRow[pmid];
    if (!row) continue; // already failed presence
    const maxR = maxRank[pmid];
    const got = row.rank;
    checks.push({
      label: `PMID ${pmid} rank ≤ ${maxR}`,
      passed: got != null && parseInt(got) <= maxR,
      detail: `got rank ${got}`,
    });
  }

  // 4. M-dimension activity
  if (expectations.min_m_nonzero_count != null) {
    const minCount = expectations.min_m_nonzero_count;
    const mActive = results.filter(r => (r.metric_favorability_score || 0) > 0).length;
    checks.push({
      label: `M-dimension active in ≥ ${minCount} results`,
      passed: mActive >= minCount,
      detail: `${mActive} results have M > 0`,
    });
  }

  // 5. Glaucoma-procedure cap
  if (expectations.max_glaucoma_procedure_in_top_n != null) {
    const [maxCount, topN] = expectations.max_glaucoma_procedure_in_top_n;
    const topRows = [...results]
      .sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999))
      .slice(0, topN);
    const hits = topRows.filter(r =>
      _GLAUCOMA_PROCEDURE_TERMS.some(term => (r.title || "").toLowerCase().includes(term))
    );
    checks.push({
      label: `Glaucoma-procedure papers ≤ ${maxCount} in top ${topN}`,
      passed: hits.length <= maxCount,
      detail: hits.length === 0
        ? "none found"
        : `${hits.length} found: ${hits.map(r => r.title).join("; ").substring(0, 120)}`,
    });
  }

  const allPassed = checks.every(c => c.passed);
  return { passed: allPassed, checks };
}

function _hideGoldValidationPanel() {
  const panel = document.getElementById("gold-validation-panel");
  if (panel) panel.classList.add("hidden");
}

function _showGoldValidationPanel(caseName, validation) {
  const panel = document.getElementById("gold-validation-panel");
  if (!panel) return;

  const { passed, checks } = validation;
  const bannerClass = passed ? "gv-pass" : "gv-fail";
  const bannerText  = passed ? "PASS — all gold expectations met" : "FAIL — some gold expectations not met";

  const checkRows = checks.map(c => `
    <li class="gv-check ${c.passed ? "gv-check-pass" : "gv-check-fail"}">
      <span class="gv-icon">${c.passed ? "✓" : "✗"}</span>
      <span class="gv-check-label">${_escHtml(c.label)}</span>
      <span class="gv-check-detail">${_escHtml(c.detail || "")}</span>
    </li>
  `).join("");

  panel.innerHTML = `
    <div class="gv-banner ${bannerClass}">
      <strong>Gold Case:</strong> ${_escHtml(caseName)} &nbsp;—&nbsp; ${bannerText}
    </div>
    <ul class="gv-checklist">${checkRows}</ul>
  `;
  panel.classList.remove("hidden");
}

// ── Gold cases (loaded from /api/v1/qa/gold-cases) ───────────────────────────
function _resetGoldCaseSelect() {
  const sel = document.getElementById("f-gold-case");
  if (!sel) return;
  sel.value = "";
}

async function loadGoldCasesIntoSelect() {
  const sel = document.getElementById("f-gold-case");
  if (!sel) return;
  try {
    const resp = await fetch("/api/v1/qa/gold-cases");
    if (!resp.ok) return;
    const data = await resp.json();
    _goldCasesById = {};
    while (sel.options.length > 1) sel.remove(1);
    for (const c of data.cases || []) {
      if (!c || !c.id) continue;
      _goldCasesById[c.id] = c; // includes expectations from backend
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name || c.id;
      if (c.golden_pmids && c.golden_pmids.length) {
        opt.title = `Golden PMID(s): ${c.golden_pmids.join(", ")}`;
      }
      sel.appendChild(opt);
    }
  } catch (e) {
    console.warn("loadGoldCasesIntoSelect:", e);
  }
}

function onGoldCaseSelect() {
  const sel = document.getElementById("f-gold-case");
  if (!sel) return;
  const id = sel.value;
  if (!id) {
    _activeGoldCaseId = null;
    _hideGoldValidationPanel();
    return;
  }
  const c = _goldCasesById[id];
  if (!c || !c.request) return;
  _activeGoldCaseId = id;
  _hideGoldValidationPanel();
  // Use fillSearchRequest (not fillGoldCaseInteractive) to replay ALL fields:
  // query, keywords, target_product, metrics_of_interest, weights, pool_size, max_results.
  fillSearchRequest(c.request);
}

/**
 * Fill the form from a gold-case request as an interactive preset.
 *
 * Copies query, target profile, and metrics of interest — but deliberately
 * ignores keywords (PMID-pinning), pool_size, max_results, and weights so
 * the user's current pool/extract settings are preserved and the full triage
 * pipeline runs as it would in real use.
 */
function fillGoldCaseInteractive(req) {
  if (!req || typeof req !== "object") return;

  _setField("f-query", req.query || "");

  // Intentionally clear keywords — PMID pins from the regression case
  // should not constrain an interactive search.
  _setField("f-keywords", "");

  const tp = req.target_product || {};
  _setField("f-target-type", tp.target_type || "device");
  _setField("f-product-name", tp.product_name != null ? String(tp.product_name) : "");
  _setField("f-device-category", tp.device_category != null ? String(tp.device_category) : "");
  _setField("f-manufacturer", tp.manufacturer != null ? String(tp.manufacturer) : "");
  _setField("f-intended-use", tp.intended_use != null ? String(tp.intended_use) : "");
  const ind = tp.indications;
  _setField(
    "f-indications",
    Array.isArray(ind) ? ind.map(String).join(", ") : (ind != null ? String(ind) : ""),
  );
  _setField("f-anatomical-site", tp.anatomical_site != null ? String(tp.anatomical_site) : "");
  _setField("f-material-family", tp.material_family != null ? String(tp.material_family) : "");
  _setField("f-material-subtype", tp.material_subtype != null ? String(tp.material_subtype) : "");
  const mf = tp.material_features;
  _setField(
    "f-material-features",
    Array.isArray(mf) ? mf.map(String).join(", ") : (mf != null ? String(mf) : ""),
  );
  const kfeat = tp.key_features;
  _setField(
    "f-key-features",
    Array.isArray(kfeat) ? kfeat.map(String).join(", ") : (kfeat != null ? String(kfeat) : ""),
  );
  _setField("f-active-ingredient", tp.active_ingredient != null ? String(tp.active_ingredient) : "");
  _setField("f-drug-class", tp.drug_class != null ? String(tp.drug_class) : "");
  _setField("f-route", tp.route != null ? String(tp.route) : "");

  if (req.metrics_of_interest && req.metrics_of_interest.length) {
    _setMetrics(req.metrics_of_interest.map(String));  // string[] → normalised by _setMetrics
    const md = document.getElementById("metrics-details");
    if (md) md.open = true;
  }

  // Open the relevant target product section(s)
  const tt = tp.target_type || "device";
  const panel = document.getElementById("search-panel");
  const details = panel ? panel.querySelectorAll(":scope > details") : [];
  const devDet = details[0];
  const drugDet = details[1];
  if (tt === "device") {
    if (devDet) devDet.open = true;
    if (drugDet) drugDet.open = false;
  } else if (tt === "drug") {
    if (devDet) devDet.open = false;
    if (drugDet) drugDet.open = true;
  } else {
    if (devDet) devDet.open = true;
    if (drugDet) drugDet.open = true;
  }

  // Optional search filters — carry over if present, otherwise leave blank
  _setField("f-year-min", req.min_year != null ? String(req.min_year) : "");
  _setField("f-year-max", req.max_year != null ? String(req.max_year) : "");
  _setField("f-country", req.country != null ? String(req.country) : "");

  // pool_size, max_results, and weights are intentionally NOT applied here —
  // the user controls those fields and we must not override them.

  // Populate evidence profile fields so the multi-source pipeline gets rich context
  _fillEvidenceProfileFromPreset({
    product_type:      tp.target_type || "unknown",
    product_name:      tp.product_name || "",
    active_ingredient: tp.active_ingredient || "",
    route:             tp.route || "",
    indications:       Array.isArray(tp.indications) ? tp.indications.join(", ") : (tp.indications || ""),
    metrics:           req.metrics_of_interest || [],  // always raw strings from request object
  });
}

/**
 * Populate the evidence profile sidebar fields from a preset or gold case.
 * Called by fillPreset() and fillGoldCaseInteractive() so every search
 * automatically carries product context into the multi-source pipeline.
 * Evidence-specific overrides (ev-product-name, etc.) are only set when
 * the caller does not already have values in those fields — this way
 * explicit evidence presets are not overwritten.
 */
function _fillEvidenceProfileFromPreset({ product_type, product_name, active_ingredient, route, indications, metrics }) {
  // Map target_type → ev-product-type value (select options: drug, device, unknown)
  const typeMap = { drug: "drug", biologic: "drug", device: "device", both: "unknown" };
  const evType = typeMap[product_type] || "unknown";
  _setField("ev-product-type", evType);

  // Only fill ev-* fields if they are currently empty (don't overwrite explicit evidence presets)
  const _setIfEmpty = (id, val) => {
    const el = document.getElementById(id);
    if (el && !el.value.trim() && val) el.value = val;
  };
  _setIfEmpty("ev-product-name", product_name);
  _setIfEmpty("ev-ingredient",   active_ingredient);
  _setIfEmpty("ev-route",        route);
  _setIfEmpty("ev-indication",   Array.isArray(indications) ? indications.join(", ") : indications);
  if (metrics && metrics.length) {
    _setIfEmpty("ev-endpoints", Array.isArray(metrics) ? metrics.slice(0, 5).join(", ") : metrics);
  }
}

/** Apply a ``SearchRequest``-shaped object (e.g. from gold cases.json) to the form. */
function fillSearchRequest(req) {
  if (!req || typeof req !== "object") return;

  _setField("f-query", req.query || "");

  const kws = req.keywords;
  _setField(
    "f-keywords",
    Array.isArray(kws) && kws.length ? kws.map(String).join(", ") : "",
  );

  const tp = req.target_product || {};
  _setField("f-target-type", tp.target_type || "device");
  _setField("f-product-name", tp.product_name != null ? String(tp.product_name) : "");
  _setField("f-device-category", tp.device_category != null ? String(tp.device_category) : "");
  _setField("f-manufacturer", tp.manufacturer != null ? String(tp.manufacturer) : "");
  _setField("f-intended-use", tp.intended_use != null ? String(tp.intended_use) : "");
  const ind = tp.indications;
  _setField(
    "f-indications",
    Array.isArray(ind) ? ind.map(String).join(", ") : (ind != null ? String(ind) : ""),
  );
  _setField("f-anatomical-site", tp.anatomical_site != null ? String(tp.anatomical_site) : "");
  _setField("f-material-family", tp.material_family != null ? String(tp.material_family) : "");
  _setField("f-material-subtype", tp.material_subtype != null ? String(tp.material_subtype) : "");
  const mf = tp.material_features;
  _setField(
    "f-material-features",
    Array.isArray(mf) ? mf.map(String).join(", ") : (mf != null ? String(mf) : ""),
  );
  const kfeat = tp.key_features;
  _setField(
    "f-key-features",
    Array.isArray(kfeat) ? kfeat.map(String).join(", ") : (kfeat != null ? String(kfeat) : ""),
  );
  _setField("f-active-ingredient", tp.active_ingredient != null ? String(tp.active_ingredient) : "");
  _setField("f-drug-class", tp.drug_class != null ? String(tp.drug_class) : "");
  _setField("f-route", tp.route != null ? String(tp.route) : "");

  if (req.metrics_of_interest && req.metrics_of_interest.length) {
    _setMetrics(req.metrics_of_interest.map(String));
    const md = document.getElementById("metrics-details");
    if (md) md.open = true;
  }

  const tt = tp.target_type || "device";
  const panel = document.getElementById("search-panel");
  const details = panel ? panel.querySelectorAll(":scope > details") : [];
  const devDet = details[0];
  const drugDet = details[1];
  if (tt === "device") {
    if (devDet) devDet.open = true;
    if (drugDet) drugDet.open = false;
  } else if (tt === "drug") {
    if (devDet) devDet.open = false;
    if (drugDet) drugDet.open = true;
  } else {
    if (devDet) devDet.open = true;
    if (drugDet) drugDet.open = true;
  }

  if (req.pool_size != null) {
    const poolSel = document.getElementById("f-pool-size");
    if (poolSel) {
      const v = String(req.pool_size);
      if ([...poolSel.options].some(o => o.value === v)) poolSel.value = v;
    }
  }
  if (req.max_results != null) {
    const mrSel = document.getElementById("f-max-results");
    if (mrSel) {
      const v = String(req.max_results);
      if ([...mrSel.options].some(o => o.value === v)) mrSel.value = v;
    }
  }

  _setField("f-year-min", req.min_year != null ? String(req.min_year) : "");
  _setField("f-year-max", req.max_year != null ? String(req.max_year) : "");
  _setField("f-country", req.country != null ? String(req.country) : "");

  if (req.weights && typeof req.weights === "object") {
    const w = req.weights;
    if (w.R != null) _setField("w-R", String(w.R));
    if (w.P != null) _setField("w-P", String(w.P));
    if (w.M != null) _setField("w-M", String(w.M));
    if (w.E != null) _setField("w-E", String(w.E));
  }
}

// ── Preset fill ────────────────────────────────────────────────────────────
function fillPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  _resetGoldCaseSelect();
  _setField("f-query",            p.query);
  _setField("f-target-type",      p.target_type);
  _setField("f-product-name",     p.product_name || "");
  _setField("f-device-category",  p.device_category || "");
  _setField("f-indications",      p.indications || "");
  _setField("f-intended-use",     p.intended_use ?? "");
  _setField("f-material-family",  p.material_family || "");
  _setField("f-material-subtype", p.material_subtype || "");
  _setField("f-material-features",p.material_features || "");
  _setField("f-key-features", Array.isArray(p.key_features) ? p.key_features.join(", ") : (p.key_features || ""));
  _setField("f-manufacturer", p.manufacturer || "");
  _setField("f-active-ingredient",p.active_ingredient || "");
  _setField("f-drug-class",       p.drug_class || "");
  _setField("f-route",            p.route || "");
  _setField("f-keywords",         p.keywords && p.keywords.length ? p.keywords.join(", ") : "");

  if (p.metrics && p.metrics.length) {
    _setMetrics(p.metrics);
    document.getElementById("metrics-details").open = true;
  }

  const panel = document.getElementById("search-panel");
  const det = panel ? panel.querySelectorAll(":scope > details") : [];
  const devDet = det[0];
  const drugDet = det[1];
  if (p.target_type === "device") {
    if (devDet) devDet.open = true;
    if (drugDet) drugDet.open = false;
  } else if (p.target_type === "drug") {
    if (devDet) devDet.open = false;
    if (drugDet) drugDet.open = true;
  } else {
    if (devDet) devDet.open = true;
    if (drugDet) drugDet.open = true;
  }

  if (p.pool_size != null) {
    const sel = document.getElementById("f-pool-size");
    if (sel) {
      const v = String(p.pool_size);
      if ([...sel.options].some(o => o.value === v)) sel.value = v;
    }
  }
  if (p.max_results != null) {
    const sel = document.getElementById("f-max-results");
    if (sel) {
      const v = String(p.max_results);
      if ([...sel.options].some(o => o.value === v)) sel.value = v;
    }
  }

  // Populate evidence profile fields so the multi-source pipeline gets rich context
  _fillEvidenceProfileFromPreset({
    product_type:      p.target_type || "unknown",
    product_name:      p.product_name || "",
    active_ingredient: p.active_ingredient || "",
    route:             p.route || "",
    indications:       p.indications || "",
    metrics:           p.metrics || [],
  });
}

function _setField(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  el.value = val;
}

// ── Metric chip management ─────────────────────────────────────────────────

/** Return the name strings from the current metric list (for payload / extraction hints). */
function _metricNames() {
  return _metricsOfInterest.map(m => m.name);
}

function addMetricFromInput() {
  const input = document.getElementById("f-metric-input");
  if (!input) return;
  const raw = input.value.trim();
  if (!raw) return;
  raw.split(",").map(s => s.trim()).filter(Boolean).forEach(m => _addMetric(m));
  input.value = "";
  input.focus();
}

function _addMetric(nameOrObj) {
  const entry = typeof nameOrObj === "string"
    ? { name: nameOrObj, value: "" }
    : { name: nameOrObj.name || "", value: nameOrObj.value || "" };
  if (!entry.name) return;
  if (_metricsOfInterest.some(m => m.name === entry.name)) return;
  _metricsOfInterest.push(entry);
  _renderMetricChips();
}

function removeMetric(name) {
  _metricsOfInterest = _metricsOfInterest.filter(m => m.name !== name);
  _renderMetricChips();
}

function _updateMetricValue(name, val) {
  const entry = _metricsOfInterest.find(m => m.name === name);
  if (entry) entry.value = val;
}

function clearAllMetrics() {
  _metricsOfInterest = [];
  _renderMetricChips();
}

function fillMetricPreset(name) {
  const metrics = METRIC_PRESETS[name];
  if (!metrics) return;
  _setMetrics(metrics);
}

/**
 * Set the full metric list. Accepts string[] or {name, value?}[] — both
 * are normalised to the internal {name, value} shape.
 */
function _setMetrics(list) {
  _metricsOfInterest = list.map(item =>
    typeof item === "string" ? { name: item, value: "" } : { name: item.name || "", value: item.value || "" }
  ).filter(e => e.name);
  _renderMetricChips();
}

function _renderMetricChips() {
  const container = document.getElementById("metric-chips");
  const countEl   = document.getElementById("metric-count");
  if (!container) return;

  container.innerHTML = _metricsOfInterest.map(m => {
    const safeName  = m.name.replace(/'/g, "\\'").replace(/"/g, "&quot;");
    const safeVal   = (m.value || "").replace(/"/g, "&quot;");
    return `<span class="metric-chip">
      <span class="metric-chip-label">${_escHtml(m.name)}</span>
      <button class="chip-remove" onclick="removeMetric('${safeName}')" title="${_t("btn_clear")}">×</button>
      <input class="metric-chip-input"
             type="text"
             placeholder="${_t("metric_value_ph")}"
             value="${safeVal}"
             aria-label="${_escHtml(m.name)} target value"
             oninput="_updateMetricValue('${safeName}', this.value)"
             onfocus="this.select()" />
    </span>`;
  }).join("");

  if (countEl) {
    countEl.textContent = _metricsOfInterest.length
      ? _t("metric_count_n", _metricsOfInterest.length)
      : "";
  }
}

// ── Form helpers ───────────────────────────────────────────────────────────
function clearForm() {
  ["f-query","f-keywords","f-product-name","f-device-category","f-manufacturer",
   "f-intended-use","f-indications","f-anatomical-site","f-material-family",
   "f-material-subtype","f-material-features","f-key-features","f-active-ingredient",
   "f-drug-class","f-route","f-year-min","f-year-max","f-country"].forEach(id => _setField(id, ""));
  _setField("f-target-type", "device");
  _setField("f-max-results", "20");
  _resetGoldCaseSelect();
  _activeGoldCaseId = null;
  _hideGoldValidationPanel();
  clearAllMetrics();
  // Also clear the evidence-specific fields now in the unified sidebar
  ["ev-seed","ev-product-name","ev-ingredient","ev-route","ev-indication","ev-endpoints"]
    .forEach(id => _setField(id, ""));
  _setField("ev-product-type", "unknown");
  document.getElementById("ev-error")?.classList.add("hidden");
  _setField("f-nl-input", "");
  document.getElementById("nl-status")?.classList.add("hidden");
  clearNlParsePreview();
  _clearEvidenceResults();
}

function _clearEvidenceResults() {
  document.getElementById("ev-results")?.classList.add("hidden");
  document.getElementById("ev-source-row")?.classList.add("hidden");
  document.getElementById("ev-progress")?.classList.add("hidden");
  const tbody = document.getElementById("ev-tbody");
  if (tbody) tbody.innerHTML = "";
  const cnt = document.getElementById("ev-results-count");
  if (cnt) cnt.textContent = "";
  _evDetailOpen = null;
}

/** Reset form, abort any in-flight search, and clear results / detail / pipeline UI. */
function clearAllWork() {
  stopSearch();

  _results = [];
  _streamedResults = [];
  _detailData = {};
  _sortCol = "rank";
  _sortDir = "asc";

  clearForm();
  _setField("f-pool-size", "100");
  _setField("w-R", "0.35");
  _setField("w-P", "0.25");
  _setField("w-M", "0.20");
  _setField("w-E", "0.20");
  document.getElementById("weight-sum-warning")?.classList.add("hidden");
  _setField("f-metric-input", "");

  _hideError();
  closeDetail();

  _pipeline = null;

  document.getElementById("progress-section")?.classList.add("hidden");
  document.getElementById("results-section")?.classList.add("hidden");
  document.getElementById("empty-state")?.classList.remove("hidden");
  _clearEvidenceResults();

  const tbody = document.getElementById("results-tbody");
  if (tbody) tbody.innerHTML = "";

  const rc = document.getElementById("results-count");
  if (rc) rc.textContent = "";

  const badge = document.getElementById("results-mode-badge");
  if (badge) {
    badge.textContent = "";
    badge.className = "chip";
  }

  const btn = document.getElementById("btn-search");
  if (btn) btn.disabled = false;
  document.getElementById("btn-stop")?.classList.add("hidden");

  const d1 = document.getElementById("step-1-detail");
  const d2 = document.getElementById("step-2-detail");
  if (d1) d1.innerHTML = "";
  if (d2) d2.innerHTML = "";
  const sub = document.getElementById("step-extract-subline");
  if (sub) sub.textContent = "";
  const pp = document.getElementById("progress-papers");
  if (pp) pp.innerHTML = "";
  const bar = document.getElementById("progress-bar");
  if (bar) bar.style.width = "0%";
}

function _buildSearchPayload() {
  const csv = id => (document.getElementById(id)?.value || "")
    .split(",").map(s => s.trim()).filter(Boolean);

  const weights = {};
  ["R","P","M","E"].forEach(k => {
    const v = parseFloat(document.getElementById("w-"+k)?.value);
    if (!isNaN(v)) weights[k] = v;
  });
  const sum = Object.values(weights).reduce((a,b) => a+b, 0);
  const warn = document.getElementById("weight-sum-warning");
  if (Math.abs(sum - 1.0) > 0.01) {
    warn.classList.remove("hidden");
    return null;
  }
  warn.classList.add("hidden");

  const targetProfile = {
    target_type: document.getElementById("f-target-type")?.value || "device",
  };

  const strFields = {
    product_name:     "f-product-name",
    device_category:  "f-device-category",
    manufacturer:     "f-manufacturer",
    intended_use:     "f-intended-use",
    anatomical_site:  "f-anatomical-site",
    material_family:  "f-material-family",
    material_subtype: "f-material-subtype",
    active_ingredient:"f-active-ingredient",
    drug_class:       "f-drug-class",
    route:            "f-route",
  };
  for (const [key, elId] of Object.entries(strFields)) {
    const val = document.getElementById(elId)?.value?.trim();
    if (val) targetProfile[key] = val;
  }
  const indications = csv("f-indications");
  if (indications.length) targetProfile.indications = indications;
  const matFeatures = csv("f-material-features");
  if (matFeatures.length) targetProfile.material_features = matFeatures;

  const payload = {
    query: document.getElementById("f-query")?.value?.trim() || "",
    target_product: targetProfile,
    weights: weights,
  };

  const maxResults = parseInt(document.getElementById("f-max-results")?.value || "20", 10);
  if (!isNaN(maxResults)) payload.max_results = maxResults;

  const poolSize = parseInt(document.getElementById("f-pool-size")?.value || "100", 10);
  if (!isNaN(poolSize)) payload.pool_size = poolSize;

  const pr = payload.max_results ?? 20;
  const ps = payload.pool_size ?? 100;
  if (ps < pr) {
    _showError(_t("warning_pool_size"));
    return null;
  }

  const minYear = parseInt(document.getElementById("f-year-min")?.value || "", 10);
  const maxYear = parseInt(document.getElementById("f-year-max")?.value || "", 10);
  if (!isNaN(minYear) && minYear > 0) payload.min_year = minYear;
  if (!isNaN(maxYear) && maxYear > 0) payload.max_year = maxYear;

  const country = document.getElementById("f-country")?.value?.trim();
  if (country) payload.country = country;

  const kwRaw = document.getElementById("f-keywords")?.value?.trim();
  if (kwRaw) {
    const keywords = kwRaw.split(",").map(s => s.trim()).filter(Boolean);
    if (keywords.length) payload.keywords = keywords;
  }

  const keyFeatures = csv("f-key-features");
  if (keyFeatures.length) targetProfile.key_features = keyFeatures;

  const metricNames = _metricNames();
  if (metricNames.length) {
    payload.metrics_of_interest = metricNames;
  }

  // Build target_metrics for metrics that have a numeric target value
  const targetMetrics = [];
  for (const m of _metricsOfInterest) {
    if (!m.value) continue;
    // Parse the first number from the value string (handles "20 mmHg", "20.5", etc.)
    const num = parseFloat(m.value);
    if (isNaN(num) || num <= 0) continue;
    targetMetrics.push({
      metric_name_normalized: m.name.toLowerCase().replace(/\s+/g, "_"),
      direction: "closer_better",
      target: num,
      // Decay range = 50% of target so a paper ±50% away scores 0
      normalisation_range: Math.max(num * 0.5, 1),
    });
  }
  if (targetMetrics.length) {
    payload.target_metrics = targetMetrics;
  }

  return payload;
}

// ── SSE helpers + pipeline stepper (single state machine) ────────────────────
function _parseSSEBuffer(buffer) {
  const parsed = [];
  const blocks = buffer.split("\n\n");
  const remaining = blocks.pop() ?? "";

  for (const block of blocks) {
    if (!block.trim()) continue;
    let eventType = "message";
    const dataLines = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        dataLines.push(line.slice(6));
      }
    }
    if (dataLines.length) {
      try {
        parsed.push({ type: eventType, data: JSON.parse(dataLines.join("\n")) });
      } catch (e) {
        console.warn("SSE JSON parse failed for event:", eventType, e, dataLines.join("\n").slice(0, 200));
      }
    }
  }
  return { parsed, remaining };
}

/** @type {null | {
 *   phase: string,
 *   poolTotal: number,
 *   maxResults: number,
 *   poolPapers: Array<{pmid: string, title: string}>,
 *   acceptedSet: Set<string>,
 *   acceptedCount: number,
 *   extractTotal: number,
 *   extractCount: number,
 *   progressNumerator: number,
 *   lastTriageIndex: number,
 *   lastTriagePmid: string,
 *   demoMode: boolean,
 *   earlyDoneMsg: string | null,
 *   demoStatusMsg: string,
 *   resultTotal: number,
 *   progressDetailLine: string,
 * }} */
let _pipeline = null;

function _resetPipeline() {
  _pipeline = {
    phase: "searching",
    poolTotal: 0,
    maxResults: 0,
    poolPapers: [],
    sourceCounts: {},
    acceptedSet: new Set(),
    acceptedCount: 0,
    extractTotal: 0,
    extractCount: 0,
    progressNumerator: 0,
    lastTriageIndex: 0,
    lastTriagePmid: "",
    demoMode: false,
    earlyDoneMsg: null,
    demoStatusMsg: "",
    resultTotal: 0,
    progressDetailLine: "",
  };
}

function _spinnerLine(text) {
  return `<div class="step-active-line"><span class="step-spinner"></span><span>${_escHtml(text)}</span></div>`;
}

function _renderPoolListHTML() {
  if (!_pipeline || !_pipeline.poolPapers.length) return "";
  const triaged = ["extracting", "done", "stopped"].includes(_pipeline.phase);
  const n = _pipeline.poolTotal || _pipeline.poolPapers.length;
  const srcCounts = _pipeline.sourceCounts || {};
  const srcParts = Object.entries(srcCounts).filter(([, v]) => v > 0).map(([k, v]) => `${k}: ${v}`);
  const srcSuffix = srcParts.length ? ` (${srcParts.join(", ")})` : "";
  let html = `<div class="pool-fetch-summary">${_escHtml(`Fetched ${n} result${n !== 1 ? "s" : ""} from all databases${srcSuffix}`)}</div>`;
  html += `<ul class="pool-list${triaged ? " triaged" : ""}" id="pool-list-main">`;
  for (const p of _pipeline.poolPapers) {
    const id = String(p.pmid);
    const src = p.source || "PubMed";
    const acc = _pipeline.acceptedSet.has(id);
    const rej = triaged && !acc;
    const cls = acc ? " pool-accepted" : rej ? " pool-rejected" : "";
    const srcClass = src.toLowerCase().replace(/[^a-z]/g, "");
    html += `<li data-pmid="${_escHtml(id)}" class="${cls.trim()}">`;
    html += `<span class="pool-source source-badge-sm ${srcClass}">${_escHtml(src)}</span>`;
    html += `<span class="pool-pmid">${_escHtml(id)}</span>`;
    html += `<span class="pool-title">${_escHtml(p.title || "—")}</span>`;
    html += `<span class="pool-check" aria-hidden="true">${acc ? "✓" : ""}</span>`;
    html += `</li>`;
  }
  html += `</ul>`;
  return html;
}

function _renderPipeline() {
  if (!_pipeline) return;

  const s1 = document.getElementById("step-1");
  const s2 = document.getElementById("step-2");
  const s3 = document.getElementById("step-3");
  const d1 = document.getElementById("step-1-detail");
  const d2 = document.getElementById("step-2-detail");
  const b1 = document.getElementById("step-1-badge");
  const b2 = document.getElementById("step-2-badge");
  const b3 = document.getElementById("step-3-badge");
  const bar = document.getElementById("progress-bar");
  const sub = document.getElementById("step-extract-subline");

  const ph = _pipeline.phase;

  let st1 = "pending";
  let st2 = "pending";
  let st3 = "pending";

  if (ph === "searching") {
    st1 = "active";
  } else if (ph === "triaging") {
    st1 = "done";
    st2 = "active";
  } else if (ph === "extracting") {
    st1 = "done";
    st2 = "done";
    st3 = "active";
  } else if (ph === "demo") {
    st1 = "done";
    st2 = "done";
    st3 = "active";
  } else if (ph === "done" || ph === "stopped") {
    st1 = "done";
    st2 = "done";
    st3 = "done";
  }

  if (s1) s1.dataset.status = st1;
  if (s2) s2.dataset.status = st2;
  if (s3) s3.dataset.status = st3;

  if (b1) {
    if (ph === "done" && _pipeline.demoMode) {
      b1.textContent = _t("step_demo_pubmed_done");
    } else if (ph === "searching" && !_pipeline.poolPapers.length) b1.textContent = "";
    else if (_pipeline.poolTotal > 0) b1.textContent = _t("step_pubmed_done", _pipeline.poolTotal);
    else if (_pipeline.poolPapers.length) b1.textContent = _t("step_pubmed_done", _pipeline.poolPapers.length);
    else b1.textContent = "";
  }

  if (d1) {
    if (_pipeline.earlyDoneMsg) {
      d1.innerHTML = `<div class="step-active-line">${_escHtml(_pipeline.earlyDoneMsg)}</div>`;
    } else if (ph === "done" && _pipeline.demoMode) {
      d1.innerHTML = "";
    } else if (_pipeline.demoMode && ph === "demo") {
      d1.innerHTML = _spinnerLine(_pipeline.demoStatusMsg || _t("step_demo_pubmed_done"));
    } else if (ph === "searching") {
      if (!_pipeline.poolPapers.length) {
        d1.innerHTML = _spinnerLine(_t("step_pubmed_active"));
      } else {
        d1.innerHTML = _renderPoolListHTML();
      }
    } else {
      d1.innerHTML = _renderPoolListHTML();
    }
  }

  if (b2) {
    if (ph === "done" && _pipeline.demoMode) {
      b2.textContent = "—";
    } else if (ph === "triaging") b2.textContent = "";
    else if (["extracting", "done", "stopped", "demo"].includes(ph) && _pipeline.extractTotal > 0) {
      b2.textContent = _t("step_triage_done", _pipeline.extractTotal);
    } else if (_pipeline.acceptedCount > 0) b2.textContent = _t("step_triage_done", _pipeline.acceptedCount);
    else if (ph === "demo") b2.textContent = "—";
    else b2.textContent = "";
  }

  if (d2) {
    if (ph === "done" && _pipeline.demoMode) {
      d2.innerHTML = "";
    } else if (ph === "triaging") {
      if (_pipeline.lastTriagePmid) {
        d2.innerHTML = `<div class="triage-live-line">${_escHtml(String(_pipeline.lastTriageIndex))} · PMID ${_escHtml(_pipeline.lastTriagePmid)}</div>`;
      } else {
        d2.innerHTML = _spinnerLine(_t("step_triage_active", _pipeline.poolTotal || 0, _pipeline.maxResults || 0));
      }
    } else if (["extracting", "done", "stopped", "demo"].includes(ph)) {
      const sel = _pipeline.extractTotal || _pipeline.acceptedCount;
      const tot = _pipeline.poolTotal || _pipeline.poolPapers.length;
      d2.innerHTML = `<div class="triage-done-summary">${_escHtml(_t("step_triage_summary", sel, tot))}</div>`;
    } else {
      d2.innerHTML = "";
    }
  }

  const extTot = _pipeline.extractTotal;
  if (b3) {
    if (ph === "done") {
      b3.textContent =
        _pipeline.resultTotal > 0 ? _t("step_extract_done", _pipeline.resultTotal) : "";
    } else if (ph === "stopped") {
      b3.textContent = "";
    } else if (extTot > 0) {
      b3.textContent = `${_pipeline.extractCount} / ${extTot}`;
    } else {
      b3.textContent = "";
    }
  }

  if (bar) {
    const pct = extTot > 0 ? Math.min(100, Math.round((_pipeline.progressNumerator / extTot) * 100)) : 0;
    bar.style.width = pct + "%";
  }
  if (sub) {
    if (ph === "extracting" || ph === "demo") {
      if (_pipeline.progressDetailLine) {
        sub.textContent = _pipeline.progressDetailLine;
      } else if (_pipeline.extractCount > 0) {
        sub.textContent = _t("prog_processed", _pipeline.extractCount, extTot);
      } else {
        sub.textContent = _t("step_extract_active", 0, extTot);
      }
    } else if (ph === "done" || ph === "stopped") {
      sub.textContent = ph === "stopped" ? _t("prog_stopped") : _t("prog_processed", _pipeline.extractCount, extTot);
    } else {
      sub.textContent = "";
    }
  }
}

function _addProgressPaper(title, pmid) {
  const el = document.getElementById("progress-papers");
  if (!el) return;
  const item = document.createElement("div");
  item.className = "progress-paper-item";
  item.innerHTML = `<span class="pp-pmid">${_escHtml(pmid)}</span> ${_escHtml(title)}`;
  el.insertBefore(item, el.firstChild);
  while (el.children.length > 3) el.removeChild(el.lastChild);
}

function _addOrUpdateResultRow(r) {
  const tbody = document.getElementById("results-tbody");
  if (!tbody) return;

  const id = String(r.pmid);
  const wasDetailOpen = _detailOpenPmid === id;

  const existing = tbody.querySelector(`tr[data-pmid="${id}"]:not(.detail-row)`);
  if (existing) {
    const nxt = existing.nextElementSibling;
    if (nxt?.classList.contains("detail-row") && nxt.dataset.detailFor === id) {
      nxt.remove();
    }
    existing.remove();
  }

  const tr = document.createElement("tr");
  tr.dataset.pmid = r.pmid;
  tr.onclick = () => expandRow(r.pmid, r);
  tr.classList.add("result-incoming");

  const _streamGoldenPmids = (() => {
    if (!_activeGoldCaseId) return new Set();
    const gc = _goldCasesById[_activeGoldCaseId];
    return new Set((gc && gc.expectations && gc.expectations.golden_pmids) || []);
  })();
  const isGoldenStream = r.pmid && _streamGoldenPmids.has(String(r.pmid));
  if (isGoldenStream) tr.classList.add("gold-anchor-row");
  const pmidBadgeStream = isGoldenStream
    ? `<span class="gold-anchor-badge" title="Gold anchor PMID">gold</span>`
    : "";

  tr.innerHTML = `
    <td class="rank">${r.rank}</td>
    <td>${_escHtml(r.title || "—")}</td>
    <td>${r.published_date ? r.published_date.substring(0,4) : "—"}</td>
    <td><code>${r.pmid || "—"}</code>${pmidBadgeStream}</td>
    ${_scoreCell(r.composite_score)}
    ${_richScoreCell(r.relevance_score, _relLabel(r.relevance_label))}
    ${_richScoreCell(r.product_similarity_score, r.product_label)}
    ${_richScoreCell(r.metric_favorability_score, null)}
    ${_evidenceScoreCell(r.evidence_quality_score, r.evidence_label, r.evidence_breakdown)}
    ${_moiCell(r)}
    <td class="rationale">${_escHtml(r.ranking_rationale || "")}</td>
  `;
  tbody.appendChild(tr);

  if (wasDetailOpen && _detailData[id]) {
    _detailData[id].ranked = r;
    _detailOpenPmid = id;
    tr.classList.add("selected");
    const detailTr = _insertDetailRowAfter(tr, id);
    _i18nRefreshSubtree(detailTr);
    _renderDetail(id);
    _flushDetailExpandOpen(detailTr);
  }

  requestAnimationFrame(() => tr.classList.add("result-visible"));
}

// ── Stop search ────────────────────────────────────────────────────────────
function stopSearch() {
  if (_searchAbortController) {
    _searchAbortController.abort();
    _searchAbortController = null;
  }
  if (_pipeline) {
    _pipeline.phase = "stopped";
    _renderPipeline();
  }
}

// ── Run search ─────────────────────────────────────────────────────────────
// ── Unified search dispatcher ──────────────────────────────────────────────
async function runUnifiedSearch() {
  const query = document.getElementById("f-query")?.value?.trim() || "";
  const seed  = document.getElementById("ev-seed")?.value?.trim() || "";

  if (!query && !seed) {
    _showError("Please enter a query and/or a seed identifier.");
    return;
  }

  _hideError();
  document.getElementById("ev-error")?.classList.add("hidden");
  document.getElementById("empty-state")?.classList.add("hidden");

  // Always run both pipelines in parallel:
  // - PubMed SSE stream (only when query is provided)
  // - Multi-source correlated evidence (always — uses query as fallback when no seed)
  const pubmedPromise  = query ? runSearch() : Promise.resolve();
  const evidencePromise = _runEvidenceFetch(seed || null, query || null);

  await Promise.all([pubmedPromise, evidencePromise]);
}

async function _runEvidenceFetch(seed, query) {
  const errEl = document.getElementById("ev-error");
  if (errEl) errEl.classList.add("hidden");

  // Evidence-specific profile fields (ev-* inputs) take priority;
  // fall back to the main device/drug sidebar fields so presets enrich the search
  // without requiring the user to fill the evidence profile separately.
  const evProductType = document.getElementById("ev-product-type")?.value || "";
  const evProductName = document.getElementById("ev-product-name")?.value?.trim() || "";
  const evIngredient  = document.getElementById("ev-ingredient")?.value?.trim() || "";
  const evRoute       = document.getElementById("ev-route")?.value?.trim() || "";
  const evIndication  = (document.getElementById("ev-indication")?.value || "")
    .split(",").map(s => s.trim()).filter(Boolean);
  const evEndpoints   = (document.getElementById("ev-endpoints")?.value || "")
    .split(",").map(s => s.trim()).filter(Boolean);

  // Main sidebar fallbacks
  const mainTargetType  = document.getElementById("f-target-type")?.value || "unknown";
  const mainProductName = document.getElementById("f-product-name")?.value?.trim() || "";
  const mainIngredient  = document.getElementById("f-active-ingredient")?.value?.trim() || "";
  const mainRoute       = document.getElementById("f-route")?.value?.trim() || "";
  const mainIndications = (document.getElementById("f-indications")?.value || "")
    .split(",").map(s => s.trim()).filter(Boolean);

  // Merge: ev-specific fields override main sidebar fields
  const productType  = (evProductType && evProductType !== "unknown") ? evProductType : mainTargetType;
  const productName  = evProductName  || mainProductName;
  const ingredient   = evIngredient   || mainIngredient;
  const route        = evRoute        || mainRoute;
  const indication   = evIndication.length ? evIndication : mainIndications;
  const endpoints    = evEndpoints.length  ? evEndpoints  : [..._metricsOfInterest];

  const payload = {};
  if (seed)  payload.seed  = seed;
  if (query) payload.query = query;

  // Always send a profile so the backend has product context for each database
  payload.profile = {
    product_type: productType || "unknown",
    product_name: productName || null,
    active_ingredient: ingredient || null,
    route: route || null,
    indication,
    key_metrics_or_endpoints: endpoints,
    key_thresholds: [],
  };

  document.getElementById("ev-progress")?.classList.remove("hidden");
  document.getElementById("ev-results")?.classList.add("hidden");
  document.getElementById("ev-source-row")?.classList.add("hidden");
  const progMsg = document.getElementById("ev-progress-msg");
  if (progMsg) progMsg.textContent = _t("ev_progress_msg");

  try {
    const resp = await fetch("/api/v1/retrieval/correlate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    renderEvidenceResults(data);
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  } finally {
    document.getElementById("ev-progress")?.classList.add("hidden");
  }
}

async function runSearch() {
  const payload = _buildSearchPayload();
  if (!payload) return;

  _results = [];
  _streamedResults = [];
  _sortCol = "rank";
  _sortDir = "asc";
  _hideError();
  closeDetail();

  const btn = document.getElementById("btn-search");
  const stopBtn = document.getElementById("btn-stop");
  btn.disabled = true;
  if (stopBtn) stopBtn.classList.remove("hidden");

  document.getElementById("empty-state").classList.add("hidden");
  document.getElementById("progress-section").classList.remove("hidden");
  document.getElementById("results-section").classList.remove("hidden");
  document.getElementById("results-tbody").innerHTML = "";
  document.getElementById("results-count").textContent = "";

  const badge = document.getElementById("results-mode-badge");
  badge.textContent = "";
  badge.className = "chip";

  _resetPipeline();
  _renderPipeline();
  const d1 = document.getElementById("step-1-detail");
  if (d1) d1.innerHTML = _spinnerLine(_t("prog_connecting"));
  const pp = document.getElementById("progress-papers");
  if (pp) pp.innerHTML = "";
  const bar = document.getElementById("progress-bar");
  if (bar) bar.style.width = "0%";

  let totalPapers = 0;
  let processedCount = 0;

  _searchAbortController = new AbortController();

  try {
    const resp = await fetch("/api/v1/search/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: _searchAbortController.signal,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || resp.statusText);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { parsed, remaining } = _parseSSEBuffer(buffer);
      buffer = remaining;

      for (const { type, data } of parsed) {
        switch (type) {
          case "status": {
            if (data.total !== undefined) totalPapers = data.total;
            const phase = data.phase;
            if (phase === "searching") {
              _pipeline.phase = "searching";
            } else if (phase === "triaging") {
              if (_pipeline.phase === "extracting" || _pipeline.phase === "done") break;
              _pipeline.phase = "triaging";
              if (data.pool_total != null) _pipeline.poolTotal = data.pool_total;
              if (data.max_results != null) _pipeline.maxResults = data.max_results;
              if (data.source_counts) _pipeline.sourceCounts = data.source_counts;
            } else if (phase === "extracting") {
              _pipeline.phase = "extracting";
              const tot = data.total ?? totalPapers;
              _pipeline.extractTotal = tot;
              totalPapers = tot;
              if (data.pool_total != null) _pipeline.poolTotal = data.pool_total;
              _pipeline.progressNumerator = 0;
              _pipeline.progressDetailLine = "";
              const ppEl = document.getElementById("progress-papers");
              if (ppEl) ppEl.innerHTML = "";
            } else if (phase === "done") {
              _pipeline.phase = "done";
              _pipeline.earlyDoneMsg = data.message || _t("prog_no_papers");
            } else if (phase === "demo") {
              _pipeline.demoMode = true;
              _pipeline.phase = "demo";
              _pipeline.demoStatusMsg = data.message || "";
              totalPapers = data.total || totalPapers;
            }
            _renderPipeline();
            break;
          }

          case "pool": {
            for (const p of data.papers || []) {
              if (p && p.pmid) _pipeline.poolPapers.push({ pmid: String(p.pmid), title: p.title || "", source: p.source || "PubMed" });
            }
            _pipeline.poolTotal = Math.max(_pipeline.poolTotal, _pipeline.poolPapers.length);
            _pipeline.phase = "searching";
            _renderPipeline();
            break;
          }

          case "accept": {
            const id = String(data.pmid || "");
            if (id) _pipeline.acceptedSet.add(id);
            _pipeline.lastTriageIndex = data.index || 0;
            _pipeline.lastTriagePmid = id;
            _pipeline.acceptedCount = _pipeline.acceptedSet.size;
            _renderPipeline();
            break;
          }

          case "progress": {
            totalPapers = data.total || totalPapers;
            _pipeline.extractTotal = totalPapers;
            _pipeline.progressNumerator = Math.max(0, (data.current || 1) - 1);
            _pipeline.progressDetailLine = _t(
              "prog_extracting",
              data.current,
              totalPapers,
              data.title || data.pmid
            );
            _renderPipeline();
            break;
          }

          case "result":
            processedCount++;
            _pipeline.progressDetailLine = "";
            _streamedResults = _streamedResults.filter((r) => r.pmid !== data.pmid);
            _streamedResults.push(data);
            _addOrUpdateResultRow(data);
            _addProgressPaper(data.title || data.pmid, data.pmid);
            _pipeline.extractCount = processedCount;
            _pipeline.progressNumerator = processedCount;
            _pipeline.extractTotal = totalPapers || _pipeline.extractTotal;
            document.getElementById("results-count").textContent = _t("count_so_far", processedCount);
            _renderPipeline();
            break;

          case "error":
            if (data.fatal) throw new Error(data.message);
            console.warn("Non-fatal extraction error:", data);
            break;

          case "done":
            _pipeline.resultTotal = data.total ?? 0;
            _streamedResults = [];
            if (data.results && data.results.length) {
              _results = data.results;
              const modeBadge = document.getElementById("results-mode-badge");
              modeBadge.textContent = data.mode || "live";
              modeBadge.className = "chip " + (data.mode === "demo" ? "warn" : "ok");
              document.getElementById("results-count").textContent = _t("count_final", data.total);
              _renderTableBody();
              // Gold case validation — run after table is rendered
              if (_activeGoldCaseId) {
                const gc = _goldCasesById[_activeGoldCaseId];
                if (gc && gc.expectations) {
                  const validation = _runGoldValidation(_results, gc.expectations);
                  _showGoldValidationPanel(gc.name || gc.id, validation);
                }
              }
            }
            if (data.mode === "demo") {
              _pipeline.phase = "done";
              _pipeline.demoMode = true;
            } else if ((data.total ?? 0) === 0) {
              _pipeline.phase = "done";
            } else {
              _pipeline.phase = "done";
              _pipeline.extractCount = data.total;
              _pipeline.progressNumerator = data.total;
            }
            _renderPipeline();
            { const sb = document.getElementById("btn-stop"); if (sb) sb.classList.add("hidden"); }
            setTimeout(() => {
              document.getElementById("progress-section").classList.add("hidden");
            }, 2500);
            break;
        }
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      _pipeline.phase = "stopped";
      _pipeline.progressNumerator = processedCount;
      _renderPipeline();
      if (_streamedResults.length > 0) {
        document.getElementById("results-count").textContent = _t("count_final", _streamedResults.length);
        _renderTableBody();
      }
      setTimeout(() => {
        document.getElementById("progress-section").classList.add("hidden");
      }, 2000);
    } else {
      _showError(e.message);
      document.getElementById("progress-section").classList.add("hidden");
    }
  } finally {
    btn.disabled = false;
    _searchAbortController = null;
    const sb2 = document.getElementById("btn-stop");
    if (sb2) sb2.classList.add("hidden");
  }
}

// ── Render results table ───────────────────────────────────────────────────
function _renderResults(data) {
  const badge = document.getElementById("results-mode-badge");
  badge.textContent = data.mode;
  badge.className = "chip " + (data.mode === "demo" ? "warn" : "ok");

  document.getElementById("results-count").textContent =
    _t("count_final", _results.length);

  _renderTableBody();
}

// Map display column names to actual result object fields
const _COL_FIELD = {
  year: "published_date",
};

function _sortValue(row, col) {
  const field = _COL_FIELD[col] ?? col;
  return row[field] ?? 0;
}

function _renderTableBody() {
  const source = _results.length > 0 ? _results : _streamedResults;
  const sorted = [...source].sort((a, b) => {
    let va = _sortValue(a, _sortCol);
    let vb = _sortValue(b, _sortCol);
    if (typeof va === "string") va = va.toLowerCase();
    if (typeof vb === "string") vb = vb.toLowerCase();
    if (va < vb) return _sortDir === "asc" ? -1 : 1;
    if (va > vb) return _sortDir === "asc" ? 1  : -1;
    return 0;
  });

  const tbody = document.getElementById("results-tbody");
  const reopenPmid = _detailOpenPmid;
  const hadDetailData = reopenPmid && _detailData[reopenPmid];

  tbody.innerHTML = "";

  // Build set of golden PMIDs for the active gold case (empty set when no gold case active)
  const _activeGoldenPmids = (() => {
    if (!_activeGoldCaseId) return new Set();
    const gc = _goldCasesById[_activeGoldCaseId];
    return new Set((gc && gc.expectations && gc.expectations.golden_pmids) || []);
  })();

  sorted.forEach(r => {
    const tr = document.createElement("tr");
    tr.dataset.pmid = r.pmid;
    tr.onclick = () => expandRow(r.pmid, r);

    const isGolden = r.pmid && _activeGoldenPmids.has(String(r.pmid));
    if (isGolden) tr.classList.add("gold-anchor-row");

    const pmidBadge = isGolden
      ? `<span class="gold-anchor-badge" title="Gold anchor PMID">gold</span>`
      : "";

    tr.innerHTML = `
      <td class="rank">${r.rank}</td>
      <td>${_escHtml(r.title || "—")}</td>
      <td>${r.published_date ? r.published_date.substring(0,4) : "—"}</td>
      <td><code>${r.pmid || "—"}</code>${pmidBadge}</td>
      ${_scoreCell(r.composite_score)}
      ${_richScoreCell(r.relevance_score, _relLabel(r.relevance_label))}
      ${_richScoreCell(r.product_similarity_score, r.product_label)}
      ${_richScoreCell(r.metric_favorability_score, null)}
      ${_evidenceScoreCell(r.evidence_quality_score, r.evidence_label, r.evidence_breakdown)}
      ${_moiCell(r)}
      <td class="rationale">${_escHtml(r.ranking_rationale || "")}</td>
    `;
    tbody.appendChild(tr);
  });

  if (reopenPmid && hadDetailData) {
    const tr = tbody.querySelector(`tr[data-pmid="${reopenPmid}"]:not(.detail-row)`);
    if (tr) {
      const freshRow = sorted.find(x => String(x.pmid) === String(reopenPmid));
      if (freshRow) _detailData[reopenPmid].ranked = freshRow;
      tr.classList.add("selected");
      _detailOpenPmid = reopenPmid;
      const detailTr = _insertDetailRowAfter(tr, reopenPmid);
      _i18nRefreshSubtree(detailTr);
      _renderDetail(reopenPmid);
      _flushDetailExpandOpen(detailTr);
    } else {
      _detailOpenPmid = null;
    }
  }
}

function _scoreCell(val, decimals = 3) {
  if (val == null) return `<td class="score"><span>—</span></td>`;
  const v = parseFloat(val);
  const cls = v >= 0.65 ? "score-high" : v >= 0.35 ? "score-mid" : "score-low";
  return `<td class="score"><span class="${cls}">${v.toFixed(decimals)}</span></td>`;
}

/** Score cell with a human-readable label beneath the number. */
function _richScoreCell(val, label, decimals = 3) {
  if (val == null) return `<td class="score score-rich"><span>—</span></td>`;
  const v = parseFloat(val);
  const cls = v >= 0.65 ? "score-high" : v >= 0.35 ? "score-mid" : "score-low";
  const labelHtml = label
    ? `<span class="score-label">${_escHtml(label)}</span>`
    : "";
  return `<td class="score score-rich"><span class="${cls}">${v.toFixed(decimals)}</span>${labelHtml}</td>`;
}

/** Evidence column: extra decimals + hover title with deterministic breakdown. */
function _evidenceScoreCell(val, label, breakdown) {
  if (val == null) return `<td class="score score-rich"><span>—</span></td>`;
  const v = parseFloat(val);
  const cls = v >= 0.65 ? "score-high" : v >= 0.35 ? "score-mid" : "score-low";
  const labelHtml = label
    ? `<span class="score-label">${_escHtml(label)}</span>`
    : "";
  const tip = breakdown ? _evidenceBreakdownTitle(breakdown) : "";
  const titleAttr = tip ? ` title="${_attrEscape(tip)}"` : "";
  return `<td class="score score-rich"${titleAttr}><span class="${cls}">${v.toFixed(3)}</span>${labelHtml}</td>`;
}

function _moiByNameLookup(extracted) {
  const byName = {};
  for (const m of extracted) {
    const key = (m.metric_name_normalized || m.metric_name_raw || "").toLowerCase();
    if (key) byName[key] = m;
  }
  return byName;
}

/** Best-effort match from extracted rows for display values (substring rules). */
function _moiLookupExtracted(byName, name) {
  const key = name.toLowerCase();
  let hit = byName[key];
  if (!hit) {
    hit = Object.values(byName).find(m => {
      const mk = (m.metric_name_normalized || m.metric_name_raw || "").toLowerCase();
      return mk.includes(key) || key.includes(mk);
    });
  }
  return hit || null;
}

/** Build the Metrics of Interest cell for a result row.
 *
 * - If the user specified metrics of interest, show each one with its
 *   extracted value (or "not found" dimmed).
 * - When the API sends coverage_mode (metrics-of-interest-only search),
 *   strike / “M” badge follow the same matched set as the Metric (M) score.
 * - Otherwise fall back to client-only substring matching.
 */
function _moiCell(r) {
  const extracted = r.extracted_metrics || [];

  if (!_metricsOfInterest.length) {
    // Fallback: total count
    if (!extracted.length) return `<td class="moi-cell"><span class="moi-empty">—</span></td>`;
    return `<td class="moi-cell"><span class="metric-count-badge">${extracted.length}</span></td>`;
  }

  const byName = _moiByNameLookup(extracted);
  const bd = r.metric_favorability_breakdown;
  const useScoring =
    bd &&
    bd.coverage_mode === true &&
    bd.matched !== null &&
    typeof bd.matched === "object" &&
    !Array.isArray(bd.matched);

  const matchedForM = useScoring ? new Set(Object.keys(bd.matched)) : null;
  const cellTip =
    useScoring && bd.coverage_ratio
      ? _t("moi_cell_coverage_tip", bd.coverage_ratio)
      : "";

  const items = _metricsOfInterest.map(entry => {
    const name   = entry.name;
    const target = entry.value ? parseFloat(entry.value) : null;
    const hit    = _moiLookupExtracted(byName, name);
    const val    = hit ? _shortMetricValue(hit) : "";

    if (useScoring && matchedForM) {
      const countsM = matchedForM.has(name);
      const pill = countsM
        ? `<span class="moi-m-pill" title="${_attrEscape(_t("moi_pill_m"))}">M</span>`
        : "";
      let tip = countsM ? _t("moi_pill_m") : _t("moi_not_counts_m");
      if (val) tip += ` — ${val}`;
      else if (hit) tip += ` — ${_t("moi_extracted_no_display_value")}`;
      if (!isNaN(target) && target) tip += ` (target: ${entry.value})`;
      const titleAttr = ` title="${_attrEscape(tip)}"`;

      if (countsM) {
        return `<span class="moi-item moi-found moi-counts-m"${titleAttr}>${_escHtml(name)}${pill}${val ? `: <strong>${val}</strong>` : ""}</span>`;
      }
      return `<span class="moi-item moi-missing"${titleAttr}>${_escHtml(name)}</span>`;
    }

    if (hit) {
      const targetSuffix = (!isNaN(target) && target) ? ` <span class="moi-target">(target: ${_escHtml(entry.value)})</span>` : "";
      return `<span class="moi-item moi-found" title="${_escHtml(name)}">${_escHtml(name)}${val ? `: <strong>${val}</strong>` : ""}${targetSuffix}</span>`;
    }
    return `<span class="moi-item moi-missing" title="${_t("moi_not_found")}: ${_escHtml(name)}">${_escHtml(name)}</span>`;
  });

  const tdAttrs =
    cellTip !== ""
      ? ` title="${_attrEscape(cellTip)}" data-moi-coverage="1"`
      : "";
  return `<td class="moi-cell"${tdAttrs}><div class="moi-list">${items.join("")}</div></td>`;
}

/** Compact single-value string for a metric (number + unit). */
function _shortMetricValue(m) {
  if (!m) return "";
  if ((m.value_type === "numeric" || m.value_type === "percentage") && m.numeric_value != null) {
    return m.unit ? `${m.numeric_value} ${m.unit}` : String(m.numeric_value);
  }
  if (m.value_type === "range" && m.value_min != null && m.value_max != null) {
    return m.unit ? `${m.value_min}–${m.value_max} ${m.unit}` : `${m.value_min}–${m.value_max}`;
  }
  if (m.text_value) return m.text_value.substring(0, 20);
  return "";
}

/** Translate a relevance label for display. */
function _relLabel(label) {
  if (!label) return null;
  const key = "rel_" + label.toLowerCase();
  return _t(key) || label;
}

// ── Sort ───────────────────────────────────────────────────────────────────
function sortTable(col) {
  if (_sortCol === col) {
    _sortDir = _sortDir === "asc" ? "desc" : "asc";
  } else {
    _sortCol = col;
    _sortDir = col === "rank" ? "asc" : "desc";
  }
  document.querySelectorAll("#results-table thead th").forEach(th => {
    th.removeAttribute("data-sort");
    if (th.dataset.col === col) th.setAttribute("data-sort", _sortDir);
  });
  _renderTableBody();
}

// ── Inline detail row (dropdown under clicked paper) ───────────────────────
const _DETAIL_COLSPAN = 11;

/** Apply current language strings to a dynamically inserted subtree. */
function _i18nRefreshSubtree(root) {
  if (!root) return;
  root.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.dataset.i18n;
    const val = _T[key];
    if (!val) return;
    const text = val[_lang] ?? val.en;
    if (typeof text === "string") {
      if (text.includes("<")) el.innerHTML = text;
      else el.textContent = text;
    }
  });
  root.querySelectorAll("[data-i18n-ph]").forEach(el => {
    el.placeholder = _t(el.dataset.i18nPh);
  });
  root.querySelectorAll("[data-i18n-title]").forEach(el => {
    el.title = _t(el.dataset.i18nTitle);
  });
}

/** Insert skeleton markup for the paper detail panel directly after a result row. */
function _insertDetailRowAfter(tr, pmid) {
  const detailTr = document.createElement("tr");
  detailTr.className = "detail-row";
  detailTr.dataset.detailFor = String(pmid);
  detailTr.innerHTML = `
    <td colspan="${_DETAIL_COLSPAN}">
      <div class="detail-expand">
        <div class="detail-inline">
          <div class="detail-header">
            <h2 id="detail-title"></h2>
            <button type="button" class="close-btn" onclick="closeDetail()" data-i18n="btn_close">✕ Close</button>
          </div>
          <div class="detail-card">
            <h3 data-i18n="detail_metadata">Paper Metadata</h3>
            <div id="detail-meta" class="meta-grid"></div>
          </div>
          <div class="detail-card" id="detail-abstract-card">
            <h3 data-i18n="detail_abstract_h">Abstract</h3>
            <p id="detail-abstract"></p>
          </div>
          <div class="detail-card">
            <h3 data-i18n="detail_ranking_h">Ranking Breakdown</h3>
            <div id="detail-ranking"></div>
          </div>
          <div class="detail-card" id="detail-normalized-fields-card">
            <h3 data-i18n="detail_norm_fields_h">Normalized Fields</h3>
            <div id="detail-normalized-fields"></div>
          </div>
          <div class="detail-card" id="detail-metrics-card">
            <h3 data-i18n="detail_metrics_h">Extracted Metrics</h3>
            <div id="detail-metrics-content"></div>
          </div>
          <div class="detail-card">
            <div class="json-header">
              <h3 data-i18n="detail_extraction_h">Extraction Result</h3>
              <button type="button" class="copy-btn" onclick="copyJson('extraction', this)" data-i18n="btn_copy">Copy</button>
            </div>
            <pre id="json-extraction" class="json-block"></pre>
          </div>
          <div class="detail-card">
            <div class="json-header">
              <h3 data-i18n="detail_normalized_h">Normalized Product</h3>
              <button type="button" class="copy-btn" onclick="copyJson('normalized', this)" data-i18n="btn_copy">Copy</button>
            </div>
            <pre id="json-normalized" class="json-block"></pre>
          </div>
          <div class="detail-card" id="detail-links-card">
            <h3 data-i18n="detail_links_h">View paper</h3>
            <div id="detail-paper-links" class="detail-paper-links"></div>
          </div>
        </div>
      </div>
    </td>
  `;
  tr.insertAdjacentElement("afterend", detailTr);
  return detailTr;
}

/** Animate detail panel to its natural height, then drop max-height so content can grow (e.g. fonts). */
function _flushDetailExpandOpen(detailTr) {
  const expand = detailTr?.querySelector(".detail-expand");
  if (!expand) return;

  expand.classList.add("open");
  expand.style.maxHeight = "0px";

  const inner = expand.querySelector(".detail-inline");
  const targetPx = Math.max(
    0,
    expand.scrollHeight,
    inner ? inner.scrollHeight : 0,
  );

  const releaseCap = () => {
    if (expand.isConnected && expand.classList.contains("open")) {
      expand.style.maxHeight = "none";
    }
  };

  if (targetPx === 0) {
    releaseCap();
    return;
  }

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      expand.style.maxHeight = `${targetPx}px`;
    });
  });

  expand.addEventListener(
    "transitionend",
    (ev) => {
      if (ev.propertyName !== "max-height") return;
      releaseCap();
    },
    { once: true },
  );

  window.setTimeout(() => {
    if (expand.style.maxHeight !== "none") releaseCap();
  }, 600);
}

// ── Expand detail ──────────────────────────────────────────────────────────
async function expandRow(pmid, rankedRow) {
  const tbody = document.getElementById("results-tbody");
  const id = String(pmid);
  const targetTr = tbody?.querySelector(`tr[data-pmid="${id}"]:not(.detail-row)`);
  if (!targetTr) return;

  const next = targetTr.nextElementSibling;
  if (next?.classList.contains("detail-row") && next.dataset.detailFor === id) {
    closeDetail();
    return;
  }

  closeDetail();
  targetTr.classList.add("selected");
  _detailOpenPmid = id;

  try {
    const resp = await fetch(`/api/v1/papers/${id}/detail`);
    if (!resp.ok) throw new Error(resp.statusText);
    const d = await resp.json();
    _detailData[id] = {...d, ranked: rankedRow};
    const detailTr = _insertDetailRowAfter(targetTr, id);
    _i18nRefreshSubtree(detailTr);
    _renderDetail(id);
    _flushDetailExpandOpen(detailTr);
    detailTr.scrollIntoView({behavior: "smooth", block: "nearest"});
  } catch (e) {
    _showError(_t("err_detail") + e.message);
    targetTr.classList.remove("selected");
    _detailOpenPmid = null;
  }
}

function _renderDetail(pmid) {
  const d = _detailData[pmid];
  if (!d) return;

  const detailTr = document.querySelector(`#results-tbody tr.detail-row[data-detail-for="${String(pmid)}"]`);
  if (!detailTr) return;

  document.getElementById("detail-title").textContent = d.paper?.title || pmid;

  // Meta
  const meta = d.paper || {};
  const metaEl = document.getElementById("detail-meta");
  metaEl.innerHTML = [
    [_t("meta_pmid"),      meta.pmid],
    [_t("meta_doi"),       meta.doi],
    [_t("meta_journal"),   meta.journal],
    [_t("meta_published"), meta.published_date],
    [_t("meta_authors"),   (meta.authors || []).join(", ")],
    [_t("meta_mesh"),      (meta.mesh_terms || []).join(", ")],
    [_t("meta_keywords"),  (meta.keywords || []).join(", ")],
  ].filter(([,v]) => v).map(([k,v]) =>
    `<span class="key">${k}</span><span class="val">${_escHtml(String(v))}</span>`
  ).join("");

  // Abstract
  const abs = document.getElementById("detail-abstract");
  abs.textContent = meta.abstract || _t("no_abstract");

  // Ranking breakdown
  const r = d.ranked || {};
  const wu = r.weights_used || {};
  const excl = r.dimensions_excluded || [];
  const breakdown = document.getElementById("detail-ranking");
  const dims = [
    {label: _t("dim_composite"), key: "composite_score",           w: null},
    {label: _t("dim_R"),         key: "relevance_score",           w: wu.R},
    {label: _t("dim_P"),         key: "product_similarity_score",  w: wu.P},
    {label: _t("dim_M"),         key: "metric_favorability_score", w: wu.M},
    {label: _t("dim_E"),         key: "evidence_quality_score",    w: wu.E},
  ];
  breakdown.innerHTML = `<div class="breakdown-grid">
    <strong>${_t("bd_dimension")}</strong><strong>${_t("bd_score")}</strong><strong>${_t("bd_weight")}</strong>
  </div>` + dims.map(dim => {
    const v = r[dim.key];
    const pct = v != null ? Math.round(v * 100) : 0;
    const cls = v >= 0.65 ? "score-high" : v >= 0.35 ? "score-mid" : "score-low";
    const barW = v != null ? pct : 0;
    const wLabel = dim.w != null ? dim.w.toFixed(2) : "—";
    return `<div class="breakdown-grid">
      <span class="dim">${dim.label}</span>
      <div class="score-bar-wrap"><div class="score-bar" style="width:${barW}%"></div></div>
      <span class="breakdown-val ${cls}">${v != null ? v.toFixed(2) : "—"} (w=${wLabel})</span>
    </div>`;
  }).join("");

  const flags = [];
  if (excl.length) flags.push(_t("flag_excluded") + excl.join(", "));
  if (r.metric_score_estimated)  flags.push(_t("flag_metric_est"));
  if (r.metric_score_incomplete) flags.push(_t("flag_metric_incomp"));
  if (r.evidence_score_estimated) flags.push(_t("flag_evidence_est"));
  if (flags.length) {
    breakdown.innerHTML += `<div class="flag-row">⚠ ${flags.join(" | ")}</div>`;
  }
  if (r.evidence_breakdown) {
    breakdown.innerHTML += `<div class="flag-row evidence-formula"><span class="key">Evidence breakdown</span> <span class="val">${_escHtml(_evidenceBreakdownTitle(r.evidence_breakdown))}</span></div>`;
  }

  // Normalized product fields card
  _renderNormalizedFields(d.normalized, r);

  // Extracted metrics card
  const metricsCard = document.getElementById("detail-metrics-card");
  const metricsContent = document.getElementById("detail-metrics-content");
  const allMetrics = d.extraction?.metrics || [];
  if (allMetrics.length === 0) {
    metricsCard.classList.add("hidden");
  } else {
    metricsCard.classList.remove("hidden");
    const interestSet = new Set(_metricsOfInterest.map(m => m.toLowerCase()));
    const rows = allMetrics.map(m => {
      const name = m.metric_name_normalized || m.metric_name_raw || "—";
      const isHighlighted = interestSet.has(name.toLowerCase());
      const value = _formatMetricValue(m);
      const unit = m.unit ? `<span class="metric-unit">${_escHtml(m.unit)}</span>` : "";
      const cat = m.metric_category ? `<span class="metric-cat">${_escHtml(m.metric_category)}</span>` : "";
      const snippet = m.evidence_snippet
        ? `<span class="metric-snippet">"${_escHtml(m.evidence_snippet.substring(0, 100))}${m.evidence_snippet.length > 100 ? "…" : ""}"</span>`
        : "";
      return `<tr class="${isHighlighted ? "metric-highlight" : ""}">
        <td class="metric-name">${isHighlighted ? '<span class="metric-interest-tag">★</span> ' : ""}${_escHtml(name)}</td>
        <td class="metric-value">${value}${unit}</td>
        <td>${cat}</td>
        <td class="metric-evidence">${snippet}</td>
      </tr>`;
    }).join("");
    metricsContent.innerHTML = `
      <table class="metrics-table">
        <thead><tr>
          <th>${_t("mth_metric")}</th>
          <th>${_t("mth_value")}</th>
          <th>${_t("mth_category")}</th>
          <th>${_t("mth_evidence")}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  document.getElementById("json-extraction").textContent =
    JSON.stringify(d.extraction, null, 2);

  document.getElementById("json-normalized").textContent =
    JSON.stringify(d.normalized, null, 2);

  const linksEl = document.getElementById("detail-paper-links");
  if (linksEl) linksEl.innerHTML = _paperLinksHtml(meta);
}

/** Normalize DOI string for https://doi.org/... */
function _normalizeDoi(doi) {
  if (!doi || typeof doi !== "string") return null;
  let s = doi.trim();
  if (!s) return null;
  const lower = s.toLowerCase();
  if (lower.startsWith("https://doi.org/")) s = s.slice(16);
  else if (lower.startsWith("http://doi.org/")) s = s.slice(15);
  else if (lower.startsWith("doi:")) s = s.slice(4).trim();
  return s || null;
}

function _isSafeHttpUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

/** Build HTML for PubMed / DOI / publisher links from paper metadata. */
function _paperLinksHtml(meta) {
  const links = [];
  const src = meta.source_url;
  if (src && typeof src === "string") {
    const t = src.trim();
    if (t && _isSafeHttpUrl(t)) {
      links.push({ href: t, label: _t("link_publisher") });
    }
  }
  const pmidRaw = meta.pmid;
  if (pmidRaw != null && /^\d+$/.test(String(pmidRaw).trim())) {
    const p = String(pmidRaw).trim();
    links.push({
      href: `https://pubmed.ncbi.nlm.nih.gov/${p}/`,
      label: _t("link_pubmed"),
    });
  }
  const doiNorm = _normalizeDoi(meta.doi);
  if (doiNorm) {
    links.push({
      href: `https://doi.org/${encodeURIComponent(doiNorm)}`,
      label: _t("link_doi"),
    });
  }
  if (links.length === 0) {
    return `<p class="detail-paper-links-empty">${_escHtml(_t("no_paper_link"))}</p>`;
  }
  const items = links.map(
    ({ href, label }) =>
      `<li><a href="${_attrEscape(href)}" target="_blank" rel="noopener noreferrer">${_escHtml(label)}</a></li>`,
  );
  return `<ul class="detail-paper-links-list">${items.join("")}</ul>`;
}

function _renderNormalizedFields(normalized, ranked) {
  const card    = document.getElementById("detail-normalized-fields-card");
  const content = document.getElementById("detail-normalized-fields");
  if (!card || !content) return;

  const norm = normalized || {};
  const signals = ranked?.breakdowns?.P?.signals || {};

  // Helper: render one signal score pill
  function _sigPill(key) {
    const v = signals[key];
    if (v == null) return `<span class="nf-sig-none">—</span>`;
    const cls = v >= 0.65 ? "score-high" : v >= 0.35 ? "score-mid" : "score-low";
    return `<span class="nf-sig ${cls}">${v.toFixed(2)}</span>`;
  }

  // Helper: render a list value
  function _list(arr) {
    return arr && arr.length ? _escHtml(arr.join(", ")) : `<em>—</em>`;
  }

  // Helper: render a single value
  function _val(v) {
    return v ? _escHtml(String(v)) : `<em>—</em>`;
  }

  const rows = [];

  if (norm.device) {
    const d = norm.device;
    rows.push([_t("nf_device_category"),   _val(d.device_category_normalized),              _sigPill("device_category")]);
    rows.push([_t("nf_material_family"),   _val(d.material?.family),                        `<span class="nf-sig-none">—</span>`]);
    rows.push([_t("nf_material_subtype"),  _val(d.material?.subtype),                       _sigPill("material_subtype")]);
    rows.push([_t("nf_material_features"), _list(d.material?.features),                     _sigPill("material_features")]);
    rows.push([_t("nf_anatomical_site"),   _val(d.anatomical_site_normalized),              _sigPill("anatomical_site")]);
    rows.push([_t("nf_indications"),       _list(d.indications_normalized),                 _sigPill("indications")]);
    rows.push([_t("nf_product_name"),      _val(d.product_name_raw),                        _sigPill("product_name")]);
    rows.push([_t("nf_manufacturer"),      _val(d.manufacturer_raw),                        _sigPill("manufacturer")]);
    rows.push([_t("nf_key_features"),      _list(d.key_features_normalized),                _sigPill("key_features")]);
    if (d.confidence != null) {
      rows.push([_t("nf_confidence"),      `<span class="nf-conf">${(d.confidence * 100).toFixed(0)}%</span>`, `<span class="nf-sig-none">—</span>`]);
    }
  }

  if (norm.drug) {
    const dr = norm.drug;
    rows.push([_t("nf_ingredient"),   _val(dr.active_ingredient_normalized),          _sigPill("drug_ingredient")]);
    rows.push([_t("nf_drug_class"),   _val(dr.drug_class_normalized),                 _sigPill("drug_class")]);
    rows.push([_t("nf_route"),        _val(dr.route_normalized),                      _sigPill("drug_route")]);
    rows.push([_t("nf_formulation"),  _list(dr.formulation_features_normalized),      _sigPill("drug_formulation_features")]);
    rows.push([_t("nf_product_name"), _val(dr.product_name_raw),                      _sigPill("drug_product_name")]);
    if (dr.confidence != null) {
      rows.push([_t("nf_confidence"), `<span class="nf-conf">${(dr.confidence * 100).toFixed(0)}%</span>`, `<span class="nf-sig-none">—</span>`]);
    }
  }

  if (rows.length === 0) {
    card.classList.add("hidden");
    return;
  }

  card.classList.remove("hidden");
  const bodyRows = rows
    .filter(([, v]) => !v.includes(">—<") && !v.includes("><em>—</em><"))
    .map(([field, val, sig]) => `<tr><td class="nf-field">${field}</td><td class="nf-value">${val}</td><td class="nf-sig-cell">${sig}</td></tr>`)
    .join("");

  const allRows = rows.map(([field, val, sig]) =>
    `<tr><td class="nf-field">${field}</td><td class="nf-value">${val}</td><td class="nf-sig-cell">${sig}</td></tr>`
  ).join("");

  content.innerHTML = `
    <table class="nf-table">
      <thead><tr>
        <th>${_t("nf_field")}</th>
        <th>${_t("nf_normalized")}</th>
        <th title="${_t("col_P_title")}">${_t("nf_signal_score")} (P)</th>
      </tr></thead>
      <tbody>${allRows}</tbody>
    </table>`;
}

function closeDetail() {
  _detailOpenPmid = null;
  document.querySelectorAll("#results-tbody tr.detail-row").forEach(tr => tr.remove());
  document.querySelectorAll("#results-tbody tr:not(.detail-row)").forEach(tr =>
    tr.classList.remove("selected"));
}

// ── Copy JSON ──────────────────────────────────────────────────────────────
function copyJson(which, btn) {
  const root =
    btn && typeof btn.closest === "function"
      ? btn.closest(".detail-inline")
      : document.querySelector("#results-tbody tr.detail-row .detail-inline");
  const id = which === "extraction" ? "json-extraction" : "json-normalized";
  const el = root?.querySelector("#" + id) || document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {
    const header = el.previousElementSibling;
    const copyBtn = header?.querySelector?.(".copy-btn");
    if (copyBtn) {
      copyBtn.textContent = _t("btn_copied");
      copyBtn.classList.add("copied");
      setTimeout(() => {
        copyBtn.textContent = _t("btn_copy");
        copyBtn.classList.remove("copied");
      }, 1500);
    }
  });
}

// ── Quick example loader ────────────────────────────────────────────────────
function loadExample() {
  fillPreset("faricimab_namd");
  document.getElementById("btn-search")?.focus();
}

// ── Health check ───────────────────────────────────────────────────────────
function _updateHealthChips(data) {
  const chip = document.getElementById("chip-health");
  chip.textContent = _t("health_prefix") + data.status;
  chip.className   = "chip " + (data.status === "ok" ? "ok" : "err");
  document.getElementById("chip-mode").textContent   = _t("mode_prefix") + data.app_mode;
  document.getElementById("chip-llm").textContent    = "LLM: " + data.llm_model;
  document.getElementById("chip-pubmed").textContent =
    "PubMed: " + (data.pubmed_live ? _t("pubmed_live") : _t("pubmed_mocked"));
}

async function fetchHealth() {
  const chip = document.getElementById("chip-health");
  try {
    const resp = await fetch("/health");
    if (!resp.ok) throw new Error(resp.statusText);
    _healthData = await resp.json();
    _updateHealthChips(_healthData);
  } catch {
    chip.textContent = _t("health_prefix") + "error";
    chip.className   = "chip err";
  }
}

// ── Utilities ──────────────────────────────────────────────────────────────
function _showError(msg) {
  const el = document.getElementById("search-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

function _hideError() {
  document.getElementById("search-error").classList.add("hidden");
}

function _escHtml(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

/** Escape for use inside HTML double-quoted attributes (e.g. title=""). */
function _attrEscape(str) {
  return _escHtml(str).replace(/"/g, "&quot;");
}

/** One-line audit string for Evidence Quality breakdown from the API. */
function _evidenceBreakdownTitle(bd) {
  if (!bd || typeof bd !== "object") return "";
  const base = Number(bd.base_score);
  const sm = Number(bd.size_modifier) || 0;
  const fm = Number(bd.follow_up_modifier) || 0;
  const cm = Number(bd.comparator_modifier) || 0;
  const pre = Math.max(0, Math.min(1, base + sm + fm + cm));
  const parts = [
    `study=${bd.study_type || "?"}`,
    `base ${base.toFixed(2)}`,
    `size ${sm >= 0 ? "+" : ""}${sm.toFixed(2)}`,
    `follow ${fm >= 0 ? "+" : ""}${fm.toFixed(2)}`,
    `comp ${cm >= 0 ? "+" : ""}${cm.toFixed(2)}`,
    `sum(pre-cap)=${pre.toFixed(3)}`,
  ];
  if (bd.sample_size != null) parts.push(`n=${bd.sample_size}`);
  if (bd.evidence_domain) parts.push(`domain=${bd.evidence_domain}`);
  if (bd.cap_applied && bd.domain_cap != null) parts.push(`cap→${bd.domain_cap}`);
  return parts.join(" | ");
}

function _formatMetricValue(m) {
  if (m.value_type === "numeric" || m.value_type === "percentage") {
    return m.numeric_value != null ? `<strong>${m.numeric_value}</strong> ` : "—";
  }
  if (m.value_type === "range" && m.value_min != null && m.value_max != null) {
    return `<strong>${m.value_min}–${m.value_max}</strong> `;
  }
  if (m.value_type === "binary") {
    return `<strong>${_escHtml(m.text_value || "—")}</strong> `;
  }
  if (m.text_value) {
    return `<span class="metric-text-val">${_escHtml(m.text_value.substring(0, 80))}</span> `;
  }
  return "—";
}

// ── Correlated Evidence (presets + rendering) ──────────────────────────────

const EVIDENCE_PRESETS = {
  faricimab_namd: {
    seed: "PMID:39350227",
    product_type: "drug",
    product_name: "VABYSMO (faricimab-svoa)",
    ingredient: "faricimab-svoa",
    route: "intravitreal",
    indication: "nAMD, DME",
    endpoints: "BCVA, OCT thickness, dosing interval durability",
  },
  ozurdex_dme: {
    seed: "PMID:24907062",
    product_type: "drug",
    product_name: "Ozurdex (dexamethasone intravitreal implant)",
    ingredient: "dexamethasone",
    route: "intravitreal",
    indication: "DME",
    endpoints: "BCVA, central retinal thickness, injection frequency",
  },
  panoptix_iol: {
    seed: "PMID:37641668",
    product_type: "device",
    product_name: "AcrySof IQ PanOptix Trifocal IOL",
    ingredient: "",
    route: "",
    indication: "cataract",
    endpoints: "BCVA, UDVA, defocus curve, contrast sensitivity",
  },
  idxdr_denovo: {
    seed: "DEN180001 review",
    product_type: "device",
    product_name: "IDx-DR",
    ingredient: "",
    route: "",
    indication: "diabetic_retinopathy",
    endpoints: "sensitivity, specificity, imageability rate",
  },
  kardia_510k: {
    seed: "K211668",
    product_type: "device",
    product_name: "KardiaMobile 6L",
    ingredient: "",
    route: "",
    indication: "atrial_fibrillation_detection",
    endpoints: "AF detection sensitivity, AF detection specificity",
  },
};

function fillEvidencePreset(presetKey) {
  const p = EVIDENCE_PRESETS[presetKey];
  if (!p) return;
  document.getElementById('ev-seed').value         = p.seed;
  document.getElementById('ev-product-name').value = p.product_name;
  document.getElementById('ev-ingredient').value   = p.ingredient;
  document.getElementById('ev-route').value        = p.route;
  document.getElementById('ev-indication').value   = p.indication;
  document.getElementById('ev-endpoints').value    = p.endpoints;
  document.getElementById('ev-product-type').value = p.product_type;
  const det = document.getElementById('ev-profile-details');
  if (det) det.open = true;
}


function renderEvidenceResults(data) {
  // Update source chips with counts
  const counts = (data.metadata || {}).source_counts || {};
  const chips = document.querySelectorAll('#ev-source-row .source-chip');
  chips.forEach(chip => {
    const src = chip.dataset.source;
    const n = counts[src] || 0;
    chip.textContent = chip.dataset.label + (n ? ` (${n})` : '');
    chip.classList.toggle('has-results', n > 0);
  });
  document.getElementById('ev-source-row').classList.remove('hidden');

  // Build table rows
  const tbody = document.getElementById('ev-tbody');
  tbody.innerHTML = '';
  _evDetailOpen = null;
  const results = data.results || [];
  document.getElementById('ev-results-count').textContent = `(${results.length})`;

  results.forEach((r, idx) => {
    const cand = r.candidate;
    const url = cand.url
      ? `<a href="${_escHtml(cand.url)}" target="_blank" rel="noopener">${_escHtml(cand.identifier)}</a>`
      : _escHtml(cand.identifier);
    const rawTitle = cand.title || '';
    const title = _escHtml(rawTitle.slice(0, 80)) + (rawTitle.length > 80 ? '…' : '');
    const srcClass = (cand.source_type || '').replace(/[^a-z0-9_]/g, '_');
    const row = document.createElement('tr');
    row.className = 'ev-result-row';
    row.dataset.idx = idx;
    row.innerHTML = `
      <td>${idx + 1}</td>
      <td><span class="source-badge ${srcClass}">${_sourceLabel(cand.source_type)}</span></td>
      <td><span class="tier-badge ${r.tier}">${r.tier}</span></td>
      <td class="ev-id-cell">${url}</td>
      <td class="ev-title-cell">${title}</td>
      <td class="score ${_scoreClass(r.correlation_score)}">${r.correlation_score.toFixed(2)}</td>
      <td class="score ${_scoreClass(r.evidence_strength_score)}">${r.evidence_strength_score.toFixed(2)}</td>
      <td class="score ${_scoreClass(r.explanation_value_score)}">${r.explanation_value_score.toFixed(2)}</td>
      <td class="ev-rel-cell">${_escHtml(r.relation_label || '')}</td>
    `;
    row.onclick = () => expandEvidenceRow(idx, r);
    tbody.appendChild(row);
  });

  document.getElementById('ev-results').classList.remove('hidden');
}

function _sourceLabel(source_type) {
  const MAP = {
    pubmed_paper:       'PubMed',
    pmc_article:        'PMC',
    fda_510k:           'openFDA 510(k)',
    fda_pma:            'FDA PMA',
    fda_denovo:         'FDA De Novo',
    fda_ssed:           'FDA SSED',
    fda_review:         'FDA Review',
    fda_label:          'FDA Label',
    dailymed_label:     'DailyMed',
    clinicaltrials:     'CT.gov',
    accessgudid_device: 'GUDID',
    maude_event:        'MAUDE',
    fda_recall:         'FDA Recall',
    fda_denovo_pdf:     'De Novo PDF',
    fda_510k_pdf:       '510(k) PDF',
  };
  return MAP[source_type] || source_type;
}

function _scoreClass(v) {
  if (v >= 0.7) return 'score-high';
  if (v >= 0.4) return 'score-mid';
  return 'score-low';
}

function expandEvidenceRow(idx, result) {
  closeEvidenceDetail();
  const rows = document.querySelectorAll('#ev-tbody tr.ev-result-row');
  const targetRow = Array.from(rows).find(r => +r.dataset.idx === idx);
  if (!targetRow) return;

  const features = result.matched_features || {};
  const featureHtml = Object.entries(features).map(([k, v]) => `
    <div class="ev-feature-bar">
      <span style="width:130px;font-size:0.75rem">${_escHtml(k)}</span>
      <div class="ev-feature-track"><div class="ev-feature-fill" style="width:${Math.round(v * 100)}%"></div></div>
      <span>${v.toFixed(2)}</span>
    </div>`).join('');

  const detailRow = document.createElement('tr');
  detailRow.className = 'ev-detail-row';
  detailRow.innerHTML = `
    <td colspan="9">
      <div class="ev-detail-expand">
        <div class="ev-detail-inner">
          <div class="ev-detail-card">
            <strong>Rationale</strong>
            <p style="font-size:0.82rem;margin-top:0.4rem">${_escHtml(result.rationale || '—')}</p>
          </div>
          <div class="ev-detail-card">
            <strong>Feature scores</strong>
            <div style="margin-top:0.4rem">${featureHtml || '<em>none</em>'}</div>
          </div>
        </div>
      </div>
    </td>`;
  targetRow.after(detailRow);
  requestAnimationFrame(() => detailRow.querySelector('.ev-detail-expand').classList.add('open'));
  _evDetailOpen = idx;
}

function closeEvidenceDetail() {
  document.querySelectorAll('#ev-tbody tr.ev-detail-row').forEach(r => r.remove());
  _evDetailOpen = null;
}

// ── Natural-language finding parser ─────────────────────────────────────────

async function parseNaturalLanguage() {
  const text = document.getElementById("f-nl-input")?.value?.trim();
  if (!text) return;

  const btn    = document.getElementById("btn-nl-parse");
  const status = document.getElementById("nl-status");
  btn.disabled = true;
  if (status) { status.textContent = _t("nl_parsing"); status.classList.remove("hidden"); }

  const controller = new AbortController();
  const timeoutId  = setTimeout(() => controller.abort(), 45_000);

  try {
    const resp = await fetch("/api/v1/interpret/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    renderNlParsePreview(data);
    const filled = _fillFromParsed(data);
    if (status) {
      status.textContent = filled > 0
        ? _t("nl_done_n", filled)
        : _t("nl_nothing");
    }
    setTimeout(() => { if (status) status.classList.add("hidden"); }, filled > 0 ? 2500 : 5000);
  } catch (err) {
    clearTimeout(timeoutId);
    clearNlParsePreview();
    const msg = err.name === "AbortError" ? _t("nl_timeout") : _t("nl_error") + ": " + err.message;
    if (status) { status.textContent = msg; }
    setTimeout(() => { if (status) status.classList.add("hidden"); }, 5000);
  } finally {
    btn.disabled = false;
  }
}

/**
 * Fill the main search sidebar from a FindingParseResponse.
 * Maps all parsed fields into the main device/drug/query/metric form controls.
 */
/**
 * Fill the main search sidebar from a FindingParseResponse.
 * Returns the number of distinct fields/groups that were actually populated.
 */
function _fillFromParsed(data) {
  let filled = 0;

  function _fill(id, val) {
    if (!val) return;
    _setField(id, val);
    filled++;
  }

  // ── Top trio: Query / Seed / Keywords ──────────────────────────────────
  _fill("f-query",  data.query);
  _fill("ev-seed",  data.seed_identifier);
  if (data.keywords && data.keywords.length) {
    _setField("f-keywords", data.keywords.join(", "));
    filled++;
  }

  // ── Target type select ─────────────────────────────────────────────────
  if (data.target_type) {
    const sel = document.getElementById("f-target-type");
    if (sel) { sel.value = data.target_type; filled++; }
  }

  // ── Device fields ──────────────────────────────────────────────────────
  _fill("f-product-name",    data.product_name);
  _fill("f-manufacturer",    data.manufacturer);
  _fill("f-device-category", data.device_category);
  _fill("f-intended-use",    data.intended_use);
  if (data.indications && data.indications.length) {
    _setField("f-indications", data.indications.join(", "));
    filled++;
  }

  // ── Drug fields ────────────────────────────────────────────────────────
  _fill("f-active-ingredient", data.active_ingredient);
  _fill("f-drug-class",        data.drug_class);
  _fill("f-route",             data.route);

  // ── Metrics of interest — add as chips with values when extractable ──────
  if (data.metrics_of_interest && data.metrics_of_interest.length) {
    // Regex: optional qualifier (~, >, >=, ≥, ≤, <, ≈), number, optional unit.
    // Captures: [1] = number, [2] = unit (mmHg, %, mg/dL, dB, D, letters, etc.)
    const _METRIC_VAL_RE = /[~≈≥≤><]?\s*(\d+(?:\.\d+)?)\s*(mm\s?[Hh]g|mmhg|%|mg\/[a-zA-Z]+|[mMuU][gG]|dB|letters?|logMAR|D\b)?/i;

    data.metrics_of_interest.forEach(raw => {
      const phrase = typeof raw === "string" ? raw : (raw.name || "");
      if (!phrase) return;

      const m = _METRIC_VAL_RE.exec(phrase);
      if (m && m[1]) {
        // Split phrase into name (text before number) and value (number + unit)
        const numStart = m.index;
        const namePart = phrase.substring(0, numStart).replace(/[~≈≥≤><\s]+$/, "").trim();
        const unit     = m[2] ? " " + m[2].replace(/\s+/, "") : "";
        const value    = m[1] + unit;
        _addMetric({ name: namePart || phrase, value });
      } else {
        _addMetric(phrase);
      }
    });

    // Part B: if the primary metric chip has no value yet, fill it from
    // structured observed_value + metric_unit returned by the LLM.
    if (data.observed_value != null && data.metric_name) {
      const unit    = data.metric_unit ? " " + data.metric_unit : "";
      const valStr  = String(data.observed_value) + unit;
      const nameLow = (data.metric_name || "").toLowerCase();
      const target  = _metricsOfInterest.find(chip => {
        const chipLow = chip.name.toLowerCase();
        return chipLow === nameLow || chipLow.includes(nameLow) || nameLow.includes(chipLow);
      });
      if (target && !target.value) {
        target.value = valStr;
        _renderMetricChips();
      }
    }

    const metricsDetails = document.getElementById("metrics-details");
    if (metricsDetails) metricsDetails.open = true;
    filled++;
  }

  // Only scroll if something was actually filled
  if (filled > 0) {
    document.getElementById("f-query")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  return filled;
}

/** Human-readable label for Step-1 preview dl keys (matches API snake_case). */
function _nlPreviewLabel(key) {
  const i18nKey = "nl_prev_" + key;
  if (_T[i18nKey]) return _t(i18nKey);
  return key.replace(/_/g, " ");
}

/** Format a preview value (string, number, bool, array, object). */
function _nlPreviewValue(val) {
  if (val === null || val === undefined) return _t("nl_preview_empty");
  if (typeof val === "boolean") return val ? "true" : "false";
  if (Array.isArray(val)) return val.length ? val.map(v => _escHtml(String(v))).join(", ") : _t("nl_preview_empty");
  if (typeof val === "object") return _escHtml(JSON.stringify(val, null, 2));
  return _escHtml(String(val));
}

/** Show Step 1 breakdown: paper specs, clinical finding, search intent. */
function renderNlParsePreview(data) {
  const root = document.getElementById("nl-parse-preview");
  const dlSpecs = document.getElementById("nl-preview-specs");
  const dlFinding = document.getElementById("nl-preview-finding");
  const olIntent = document.getElementById("nl-preview-intent");
  if (!root || !dlSpecs || !dlFinding || !olIntent) return;

  const specs = data.step1_product_context;
  const finding = data.step1_clinical_finding;
  const goals = data.step1_search_goals;

  const hasSpecs = specs && typeof specs === "object" && Object.keys(specs).length > 0;
  const hasFinding = finding && typeof finding === "object" && Object.keys(finding).length > 0;
  const hasGoals = goals && goals.length > 0;

  if (!hasSpecs && !hasFinding && !hasGoals) {
    root.classList.add("hidden");
    return;
  }

  const specOrder = [
    "name_source", "name", "type", "manufacturer", "category",
    "intended_use", "indications", "procedure",
    "active_ingredient", "drug_class", "route",
  ];
  dlSpecs.innerHTML = "";
  if (hasSpecs) {
    const keys = [...new Set([...specOrder.filter(k => k in specs), ...Object.keys(specs)])];
    keys.forEach(k => {
      const dt = document.createElement("dt");
      dt.textContent = _nlPreviewLabel(k);
      const dd = document.createElement("dd");
      dd.innerHTML = _nlPreviewValue(specs[k]);
      dlSpecs.appendChild(dt);
      dlSpecs.appendChild(dd);
    });
  } else {
    const dd = document.createElement("dd");
    dd.className = "nl-parse-empty";
    dd.textContent = _t("nl_preview_empty");
    dlSpecs.appendChild(dd);
  }

  const findOrder = ["metric", "unit", "timepoint", "observed", "control", "significant"];
  dlFinding.innerHTML = "";
  if (hasFinding) {
    const keys = [...new Set([...findOrder.filter(k => k in finding), ...Object.keys(finding)])];
    keys.forEach(k => {
      const dt = document.createElement("dt");
      dt.textContent = _nlPreviewLabel(k);
      const dd = document.createElement("dd");
      dd.innerHTML = _nlPreviewValue(finding[k]);
      dlFinding.appendChild(dt);
      dlFinding.appendChild(dd);
    });
  } else {
    const dd = document.createElement("dd");
    dd.className = "nl-parse-empty";
    dd.textContent = _t("nl_preview_empty");
    dlFinding.appendChild(dd);
  }

  olIntent.innerHTML = "";
  if (hasGoals) {
    goals.forEach(g => {
      const li = document.createElement("li");
      li.innerHTML = _nlPreviewValue(g);
      olIntent.appendChild(li);
    });
  } else {
    const li = document.createElement("li");
    li.className = "nl-parse-empty";
    li.textContent = _t("nl_preview_empty");
    olIntent.appendChild(li);
  }

  root.classList.remove("hidden");
}

function clearNlParsePreview() {
  document.getElementById("nl-parse-preview")?.classList.add("hidden");
  const dlSpecs = document.getElementById("nl-preview-specs");
  const dlFinding = document.getElementById("nl-preview-finding");
  const olIntent = document.getElementById("nl-preview-intent");
  if (dlSpecs) dlSpecs.innerHTML = "";
  if (dlFinding) dlFinding.innerHTML = "";
  if (olIntent) olIntent.innerHTML = "";
}

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  fetchHealth();
  loadGoldCasesIntoSelect();

  document.getElementById("f-query")?.addEventListener("keydown", e => {
    if (e.key === "Enter") runUnifiedSearch();
  });
  document.getElementById("ev-seed")?.addEventListener("keydown", e => {
    if (e.key === "Enter") runUnifiedSearch();
  });
  document.getElementById("f-metric-input")?.addEventListener("keydown", e => {
    if (e.key === "Enter") addMetricFromInput();
  });
  document.getElementById("f-nl-input")?.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); parseNaturalLanguage(); }
  });

  ["w-R","w-P","w-M","w-E"].forEach(id => {
    document.getElementById(id)?.addEventListener("input", () => {
      const sum = ["w-R","w-P","w-M","w-E"]
        .reduce((a,k) => a + parseFloat(document.getElementById(k)?.value||0), 0);
      document.getElementById("weight-sum-warning")
        .classList.toggle("hidden", Math.abs(sum - 1.0) <= 0.01);
    });
  });
});
