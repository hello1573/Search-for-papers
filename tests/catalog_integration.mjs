import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {FileBlob, SpreadsheetFile, Workbook} from '@oai/artifact-tool';

const root = await fs.mkdtemp(path.join(os.tmpdir(), 'paper-catalog-test-'));
const output = path.join(root, 'catalog.xlsx');
const input = path.join(root, 'rows.json');
const book = Workbook.create();
const sheet = book.worksheets.add('文献目录');
sheet.getRange('A1').write([
  ['发表日期','论文英文题名','期刊/来源','JCR分区','中科院分区','方向与交叉分类','DOI','相关性','本地全文路径','论文来源链接','收录日期','用户阅读状态','备注','人工标签'],
  ['2024-01-02','Terrain study','Journal','Q1 verified','待核验','03_空洞填补','https://doi.org/10.1/demo','高','E:\\paper.pdf','https://example.org','2026-09-26','已读','保留这条人工备注','我的分类'],
]);
sheet.tables.add('A1:N2', true, 'PaperCatalog');
book.recalculate();
await (await SpreadsheetFile.exportXlsx(book)).save(output);
await fs.writeFile(input, JSON.stringify([
  {date:'2024-01-02',title:'Terrain study',title_zh:'地形研究',journal:'Journal',doi:'10.1/demo',
   indexing:'SCIE',jcr:'尚无可验证分区来源',cas:'地球科学大类2区（2025版）',if_value:4.3,if_year:2025,
   metrics_verified:['indexing','cas','if_value','if_year'],reading_status:'未读',notes:'机器备注',categories:'03_空洞填补'},
  {date:'2025',title:'Another DEM paper',doi:'10.1/new',journal:'Journal',pdf:'E:\\new.pdf',categories:'01、07'},
]));
const run = () => execFileSync(process.execPath, [path.resolve('build_catalog.mjs'),input,output], {encoding:'utf8'});
run();
const first = await fs.readFile(output);
const secondLog = run();
assert.match(secondLog, /changed=false/);
assert.deepEqual(await fs.readFile(output), first);
const saved = await SpreadsheetFile.importXlsx(await FileBlob.load(output));
const rows = saved.worksheets.getItem('文献目录').getUsedRange().values;
const headers = rows[0];
assert.equal(headers.at(-1), '本地全文路径');
assert.ok(!headers.includes('DOI') && !headers.includes('论文来源链接'));
assert.equal(rows.length, 3);
const get = name => rows[1][headers.indexOf(name)];
assert.equal(get('用户阅读状态'), '已读');
assert.equal(get('备注'), '保留这条人工备注');
assert.equal(get('人工标签'), '我的分类');
assert.equal(get('JCR分区'), 'Q1 verified');
assert.equal(get('中科院分区'), '地球科学大类2区（2025版）');
assert.ok(!get('方向与交叉分类').includes('03_'));
assert.equal(get('方向与交叉分类'), '缺失地形恢复与空洞填补');
assert.equal(rows[2][headers.indexOf('方向与交叉分类')], '地面分类与滤波、拓扑结构与地形特征');
console.log('Catalog migration, DOI/title deduplication, manual fields and byte-identical rerun passed.');
