import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [sourcePath, outputPath, stateDirectory] = process.argv.slice(2);
if (!sourcePath || !outputPath) throw new Error("Usage: build_catalog.mjs rows.json catalog.xlsx [internal-directory]");
const internalRoot = path.resolve(stateDirectory || path.join(path.dirname(fileURLToPath(import.meta.url)), "local-state"));
const outputRoot = path.resolve(path.dirname(outputPath));
const relative = path.relative(outputRoot, internalRoot);
if (!relative || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative))) {
  throw new Error("Internal files must be outside the user's output directory");
}
await fs.mkdir(internalRoot, {recursive:true});
const candidates = JSON.parse(await fs.readFile(sourcePath, "utf8"));
const exists = await fs.stat(outputPath).then(() => true, () => false);
const workbook = exists ? await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath)) : Workbook.create();
const sheet = exists ? workbook.worksheets.getItem("文献目录") : workbook.worksheets.add("文献目录");
const indexPath = path.join(internalRoot, ".paper_catalog_index.json");
const legacyIndex = path.join(outputRoot, ".paper_catalog_index.json");
const savedIndex = await fs.readFile(indexPath, "utf8").then(JSON.parse, () => fs.readFile(legacyIndex, "utf8").then(JSON.parse, () => ({})));
const headers = ["发表日期", "论文英文题名", "论文中文译名", "期刊/来源", "收录类型", "JCR分区", "中科院分区", "影响因子", "IF数据年份", "方向与交叉分类", "相关性", "收录/推送日期", "用户阅读状态", "备注", "本地全文路径"];
const safeText = value => {
  if (typeof value === "number") return value;
  const text = String(value ?? "");
  return text.startsWith("=") ? `\'${text}` : text;
};
const titleKey = title => String(title ?? "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
const keyFor = (doi, title) => String(doi ?? "").trim().toLowerCase().replace(/^https?:\/\/(?:dx\.)?doi\.org\//, "") || titleKey(title);
const columnName = index => {
  let text = "";
  for (let n = index + 1; n; n = Math.floor((n - 1) / 26)) text = String.fromCharCode(65 + (n - 1) % 26) + text;
  return text;
};
const missingMetric = value => !value || /待审|待核|未核|未取|未确认|尚无|要求登录|未提供|未知/.test(String(value));
const categoryNames = {"01":"地面分类与滤波", "02":"DTM生成与联合重建", "03":"缺失地形恢复与空洞填补", "04":"DEM超分辨率与稠密化", "05":"曲面建模、插值与隐式表示", "06":"多源数据与摄影测量重建", "07":"拓扑结构与地形特征", "08":"评价、综述与数据集", "09":"跨领域与通用点云补全"};
const cleanClass = text => String(text ?? "")
  .replace(/(^|[,，、;；]\s*)(\d{2})(?:_[^,，、;；]+)?(?=$|[,，、;；])/g,
    (match, separator, code) => separator + (categoryNames[code] || match.replace(/^\d{2}_?/, "")))
  .replace(/_/g, "与");
const dateValue = value => {
  if (typeof value === "number") return value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value ?? ""))) {
    const day = new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(day.getTime()) || day.toISOString().slice(0, 10) !== value) throw new Error("Invalid date");
    return (day.getTime() - Date.UTC(1899, 11, 30)) / 86400000;
  }
  return safeText(value);
};
const rowFor = p => [dateValue(p.date), safeText(p.title), safeText(p.title_zh), safeText(p.journal), safeText(p.indexing), safeText(p.jcr), safeText(p.cas), p.if_value ?? "", p.if_year ?? "", cleanClass([p.direction, p.categories].filter(Boolean).join("；")), safeText(p.relevance), dateValue(p.collected), safeText(p.reading_status), safeText(p.notes), safeText(p.pdf)];

const before = (sheet.getUsedRange()?.values || []).map(row => row.map(value => value ?? ""));
const oldHeaders = before[0] || [];
const table = exists ? sheet.tables.items.find(t => t.name === "PaperCatalog") : null;
if (exists && !table) throw new Error("No PaperCatalog table; refusing to overwrite unrelated workbook");
const field = (row, ...names) => {
  const i = names.map(name => oldHeaders.indexOf(name)).find(i => i >= 0);
  return i === undefined ? "" : row[i];
};
const removed = new Set(["DOI", "论文来源链接"]);
const extras = oldHeaders.filter(h => h && !headers.includes(h) && !removed.has(h) && h !== "收录日期");
const finalHeaders = [...headers.slice(0, -1), ...extras, headers.at(-1)];
const records = [];
const keys = new Map();
for (const old of before.slice(1)) {
  const title = field(old, "论文英文题名");
  if (!title) continue;
  const doi = field(old, "DOI") || savedIndex[titleKey(title)];
  const item = rowFor({
    date: field(old, "发表日期"), title, title_zh: field(old, "论文中文译名"),
    journal: field(old, "期刊/来源"), indexing: field(old, "收录类型"),
    jcr: field(old, "JCR分区"), cas: field(old, "中科院分区"),
    if_value: field(old, "影响因子"), if_year: field(old, "IF数据年份"),
    categories: field(old, "方向与交叉分类"), relevance: field(old, "相关性"),
    collected: field(old, "收录/推送日期", "收录日期"),
    reading_status: field(old, "用户阅读状态"), notes: field(old, "备注"), pdf: field(old, "本地全文路径"),
  });
  const key = keyFor(doi, title);
  keys.set(key, records.length);
  keys.set("title:" + titleKey(title), records.length);
  if (doi) savedIndex[titleKey(title)] = key;
  records.push([...item.slice(0, -1), ...extras.map(h => field(old, h)), item.at(-1)]);
}
let appended = 0;
for (const paper of candidates) {
  const key = keyFor(paper.doi, paper.title);
  if (!key) continue;
  const rowIndex = keys.get(key) ?? keys.get("title:" + titleKey(paper.title));
  const values = rowFor(paper);
  if (rowIndex !== undefined) {
    const row = records[rowIndex];
    // Refresh machine-maintained metrics; never overwrite human reading state or notes.
    for (const i of [0, 2]) {
      if (values[i] !== "" && values[i] !== undefined && values[i] !== null) row[i] = values[i];
    }
    for (const [i, field] of [[4,"indexing"],[5,"jcr"],[6,"cas"],[7,"if_value"],[8,"if_year"]]) {
      if (values[i] !== "" && values[i] !== undefined && values[i] !== null &&
          (paper.metrics_verified?.includes(field) || missingMetric(row[i]))) row[i] = values[i];
    }
    for (const i of [9, 10, 11, 12, 13]) if (!row[i] && values[i]) row[i] = values[i];
    if (values[9] && /[,，、;；]\s*$/.test(String(row[9]))) row[9] = values[9];
    if (!row.at(-1) && values.at(-1)) row[row.length - 1] = values.at(-1);
  } else {
    keys.set(key, records.length);
    keys.set("title:" + titleKey(paper.title), records.length);
    records.push([...values.slice(0, -1), ...extras.map(() => ""), values.at(-1)]);
    appended++;
  }
  if (paper.doi) savedIndex[titleKey(paper.title)] = key;
}
const after = [finalHeaders, ...records];
const changed = savedIndex.__format_version !== 3 || JSON.stringify(before) !== JSON.stringify(after);
if (changed) {
  if (exists) {
    const folder = path.join(internalRoot, "backups");
    await fs.mkdir(folder, {recursive:true});
    await fs.copyFile(outputPath, path.join(folder, `${path.basename(outputPath, ".xlsx")}_${new Date().toISOString().replace(/[:.]/g, "-")}.xlsx`));
  }
  table?.delete();
  sheet.getUsedRange()?.clear({applyTo:"contents"});
  sheet.getRange("A1").write(after);
  const last = columnName(finalHeaders.length - 1);
  sheet.showGridLines = false;
  sheet.getRange(`A1:${last}${after.length}`).format = {
    font:{name:"Microsoft YaHei",size:10}, wrapText:true, verticalAlignment:"center",
    rowHeight:105, borders:{preset:"all",style:"thin",color:"#D9D9D9"},
  };
  sheet.getRange(`A1:${last}1`).format = {
    fill:"#244858", font:{name:"Microsoft YaHei",size:11,bold:true,color:"#FFFFFF"}, rowHeight:32,
  };
  const widths = [16,66,45,42,18,38,30,13,15,55,14,17,19,48];
  finalHeaders.forEach((h,i) => {sheet.getRangeByIndexes(0,i,1,1).format.columnWidth = h === "本地全文路径" ? 65 : (widths[i] ?? 30);});
  if (records.length) {
    sheet.getRange(`A2:A${after.length}`).setNumberFormat("yyyy-mm-dd");
    sheet.getRange(`L2:L${after.length}`).setNumberFormat("yyyy-mm-dd");
    sheet.getRange(`H2:H${after.length}`).setNumberFormat("0.0");
    sheet.getRange(`I2:I${after.length}`).setNumberFormat("0");
    records.forEach((row,index) => {
      for (const column of [0,11]) {
        if (/^\d{4}$/.test(String(row[column] ?? ""))) sheet.getRangeByIndexes(index + 1,column,1,1).setNumberFormat("0");
      }
    });
  }
  sheet.freezePanes.freezeRows(1);
  sheet.tables.add(`A1:${last}${after.length}`, true, "PaperCatalog");
  workbook.recalculate();
  const file = await SpreadsheetFile.exportXlsx(workbook);
  await fs.mkdir(path.dirname(outputPath), {recursive:true});
  const temp = `${outputPath}.tmp.xlsx`;
  const stage = path.join(internalRoot, "catalog-stage.xlsx");
  await file.save(stage);
  await fs.copyFile(stage, temp);
  await fs.rename(temp,outputPath);
}
savedIndex.__format_version = 3;
const indexTemp = `${indexPath}.tmp`;
await fs.writeFile(indexTemp, JSON.stringify(savedIndex,null,2), "utf8");
await fs.rename(indexTemp, indexPath);
if (process.env.PREVIEW_FILE) {
  const preview = await workbook.render({sheetName:"文献目录",range:process.env.PREVIEW_RANGE || "A1:I6",scale:1.3,format:"png"});
  await fs.writeFile(process.env.PREVIEW_FILE,new Uint8Array(await preview.arrayBuffer()));
}
const check = await workbook.inspect({kind:"region",sheetId:"文献目录",range:"A1:I3",maxChars:1800});
console.log(`Catalog: ${records.length} records, ${appended} appended, changed=${changed}; ${check.ndjson.slice(0,600)}`);
