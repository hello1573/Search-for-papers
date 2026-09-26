import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [sourcePath, outputPath] = process.argv.slice(2);
if (!sourcePath || !outputPath) throw new Error("Usage: build_catalog.mjs rows.json catalog.xlsx");
const candidates = JSON.parse(await fs.readFile(sourcePath, "utf8"));
const exists = await fs.stat(outputPath).then(() => true, () => false);
const workbook = exists
  ? await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath))
  : Workbook.create();
const sheet = exists
  ? workbook.worksheets.getItem("文献目录")
  : workbook.worksheets.add("文献目录");

const headers = ["发表日期", "论文英文题名", "期刊/来源", "JCR分区", "中科院分区", "方向与交叉分类", "DOI", "相关性", "本地全文路径", "论文来源链接", "收录/推送日期"];
const safeText = (value) => {
  const text = String(value ?? "");
  return text.startsWith("=") ? `\'${text}` : text;
};
const rowFor = (paper) => [
  paper.date, paper.title, paper.journal, paper.jcr, paper.cas,
  [paper.direction, paper.categories].filter(Boolean).join("；"),
  paper.doi, paper.relevance, paper.pdf, paper.url, paper.collected,
].map(safeText);
const keyFor = (doi, title) => {
  const id = String(doi ?? "").trim().toLowerCase().replace(/^https?:\/\/(?:dx\.)?doi\.org\//, "");
  return id || String(title ?? "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
};

let table;
let migrated = false;
if (!exists) {
  sheet.showGridLines = false;
  sheet.getRange("A1:K1").values = [headers];
  sheet.getRange("A1:K1").format = {
    fill: "#244858",
    font: { name: "Microsoft YaHei", size: 11, bold: true, color: "#FFFFFF" },
    rowHeight: 32,
    verticalAlignment: "center",
  };
  const widths = [16, 66, 42, 18, 19, 55, 38, 15, 65, 55, 17];
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width;
  });
  sheet.freezePanes.freezeRows(1);
  table = sheet.tables.add("A1:K1", true, "PaperCatalog");
} else {
  table = sheet.tables.items.find((item) => item.name === "PaperCatalog");
  if (!table) throw new Error("Existing catalog has no PaperCatalog table; refusing to overwrite user data");
  if (sheet.getRange("A1").values[0][0] === "收录日期" && !sheet.getRange("K1").values[0][0]) {
    const oldRows = sheet.getUsedRange().values;
    const byKey = new Map(candidates.map((paper) => [keyFor(paper.doi, paper.title), paper]));
    table.delete();
    sheet.getRange("A1").values = [["发表日期"]];
    sheet.getRange("K1").values = [["收录/推送日期"]];
    sheet.getRange("K1").format.columnWidth = 17;
    for (let index = 1; index < oldRows.length; index++) {
      const paper = byKey.get(keyFor(oldRows[index][6], oldRows[index][1]));
      sheet.getRange(`A${index + 1}`).values = [[safeText(paper?.date ?? "")]];
      sheet.getRange(`K${index + 1}`).values = [[safeText(paper?.collected ?? oldRows[index][0])]];
    }
    table = sheet.tables.add(`A1:K${oldRows.length}`, true, "PaperCatalog");
    migrated = true;
  }
}

const existing = sheet.getUsedRange().values || [];
const seen = new Map(existing.slice(1).map((row, index) => [keyFor(row[6], row[1]), index + 2]).filter(([key]) => key));
const toAppend = [];
let updated = 0;
for (const paper of candidates) {
  const key = keyFor(paper.doi, paper.title);
  if (!key) continue;
  if (seen.has(key)) {
    const rowNumber = seen.get(key);
    if (paper.pdf && !existing[rowNumber - 1]?.[8]) {
      sheet.getRange(`I${rowNumber}`).values = [[safeText(paper.pdf)]];
      existing[rowNumber - 1][8] = paper.pdf;
      updated++;
    }
    continue;
  }
  seen.set(key, existing.length + toAppend.length + 1);
  toAppend.push(rowFor(paper));
}
if (toAppend.length) {
  table.rows.add(null, toAppend);
  const start = existing.length + 1;
  sheet.getRange(`A${start}:K${start + toAppend.length - 1}`).format = {
    font: { name: "Microsoft YaHei", size: 10 },
    rowHeight: 41,
    verticalAlignment: "center",
    wrapText: true,
  };
}
if (!exists || migrated || toAppend.length || updated) {
  await workbook.recalculate();
  const file = await SpreadsheetFile.exportXlsx(workbook);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const temp = `${outputPath}.tmp.xlsx`;
  await file.save(temp);
  await fs.rename(temp, outputPath);
  await fs.unlink(`${temp}.inspect.ndjson`).catch(() => {});
}
if (process.env.PREVIEW_FILE) {
  const preview = await workbook.render({ sheetName: "文献目录", range: "A1:F12", scale: 1.5, format: "png" });
  await fs.writeFile(process.env.PREVIEW_FILE, new Uint8Array(await preview.arrayBuffer()));
}
const check = await workbook.inspect({ kind: "region", sheetId: "文献目录", range: "A1:K3", maxChars: 1500 });
console.log(`Catalog: ${existing.length - 1} existing, ${toAppend.length} appended, ${updated} PDF paths updated; ${check.ndjson.slice(0, 450)}`);
