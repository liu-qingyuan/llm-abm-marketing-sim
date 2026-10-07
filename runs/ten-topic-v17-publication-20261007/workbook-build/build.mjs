import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const dir = path.dirname(new URL(import.meta.url).pathname);
const tables = JSON.parse(await fs.readFile(path.join(dir, 'workbook-tables.json'), 'utf8'));
const workbook = Workbook.create();
const source = {};
for (const [name, rows] of Object.entries(tables)) {
  const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
  const values = [columns, ...rows.map(row => columns.map(key => row[key] ?? null))];
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const region = sheet.getRangeByIndexes(0, 0, values.length, columns.length);
  region.values = values;
  region.format.font = { name: 'Arial', size: 10 };
  region.format.columnWidth = 18;
  region.format.rowHeight = 20;
  sheet.getRangeByIndexes(0, 0, 1, columns.length).format = {
    fill: '#1E3A5F', font: { name: 'Arial', bold: true, color: '#FFFFFF' },
    rowHeight: 40, wrapText: true,
  };
  sheet.freezePanes.freezeRows(1);
  if (name === 'Methods') {
    sheet.getRange('A:A').format.columnWidth = 30;
    sheet.getRange('B:B').format.columnWidth = 100;
    sheet.getRangeByIndexes(1, 1, rows.length, 1).format.wrapText = true;
    sheet.getRangeByIndexes(1, 0, rows.length, columns.length).format.rowHeight = 34;
  } else {
    columns.forEach((key, col) => {
      if (key.includes('rate') || key.includes('probability') || key.includes('confidence'))
        sheet.getRangeByIndexes(1, col, rows.length, 1).setNumberFormat('0.000%');
      else if (typeof rows.find(r => r[key] !== null && r[key] !== undefined)?.[key] === 'number') {
        const numbers = rows.map(row => row[key]).filter(value => typeof value === 'number');
        sheet.getRangeByIndexes(1, col, rows.length, 1).setNumberFormat(numbers.every(Number.isInteger) ? '#,##0' : '#,##0.000');
      }
    });
  }
  source[name] = { columns, values, rows: values.length, cols: columns.length };
}
await fs.writeFile(path.join(dir, 'workbook-source-cells.json'), JSON.stringify(source));
await fs.writeFile(path.join(dir, 'workbook-inspect.json'), JSON.stringify(await workbook.inspect({ kind: 'sheet', include: 'id,name', maxChars: 6000 })));
const preview = await workbook.render({ sheetName: 'Whole results', range: 'A1:H10', scale: 1, format: 'png' });
await fs.writeFile(path.join(dir, 'whole-preview.png'), new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(dir, 'ten-topic-research.xlsx'));
console.log('WORKBOOK exported sheets=' + Object.keys(tables).length);
