const pages = [
  { id: 'executive', name: 'Executive Summary', render: executive },
  { id: 'oee', name: 'OEE Decomposition', render: oee },
  { id: 'spc', name: 'SPC Monitor', render: spc },
  { id: 'pareto', name: 'Pareto & RCA', render: paretoPage },
  { id: 'orders', name: 'Work Orders', render: orders },
  { id: 'capacity', name: 'Capacity & Manpower', render: capacity },
  { id: 'quality', name: 'Alerts & Data Quality', render: quality },
];

const formatPercent = (value) => `${value.toFixed(2)}%`;
const heading = (title, description, right = 'Validated project snapshot') => `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div><div class="eyebrow">${right}</div></div>`;
const kpi = (label, value, sub = '', feature = false, valueClass = '') => `<article class="kpi-card${feature ? ' feature' : ''}"><div class="label">${label}</div><div class="value ${valueClass}">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</article>`;
const mini = (label, value, empty = false) => `<article class="mini-kpi"><div class="label">${label}</div><div class="value${empty ? ' empty' : ''}">${value}</div></article>`;
const panel = (title, body, foot = '', extra = '') => `<section class="panel ${extra}"><div class="panel-title"><h2>${title}</h2></div>${body}${foot ? `<div class="visual-foot">${foot}</div>` : ''}</section>`;
const missing = (title, detail) => `<div class="missing-panel"><strong>${title}</strong><span>${detail}</span></div>`;
const bars = (items, max = 80, selected = '') => `<div class="bar-chart">${items.map(([name, value]) => `<div class="bar-row"><span class="bar-label">${name}</span><div class="bar-track"><span class="bar-fill ${name === selected ? 'low' : 'highlight'}" style="width:${Math.min(value / max * 100, 100)}%"></span></div><span class="bar-value">${formatPercent(value)}</span></div>`).join('')}</div><div class="axis-hint"><span>0%</span><span>${max / 2}%</span><span>${max}%</span></div>`;
const visual = (type, x, y, other = '') => `<strong>${type}</strong> · X: ${x} · Value: ${y}${other ? ` · ${other}` : ''}`;

function executive() {
  const findings = [
    '<strong>L2</strong> has lower Performance, associated with elevated night-shift minor stops.',
    '<strong>L3</strong> has lower Quality, associated with progressive tool-wear deterioration.',
    '<strong>Shift C</strong> has the lowest plant-level OEE.',
    'The top three downtime causes represent <strong>87.75%</strong> of unplanned downtime.',
    'The top three scrap causes represent <strong>74.38%</strong> of scrap cost.',
  ];
  return heading('Executive Summary', 'Plant performance across production lines and shifts', '<strong>Plant-wide</strong> · Validated snapshot') +
    `<div class="kpi-grid">${kpi('Overall Equipment Effectiveness', '74.41%', 'Availability × Performance × Quality', true)}${kpi('Availability', '91.29%')}${kpi('Performance', '84.50%')}${kpi('Quality', '96.46%')}</div>` +
    `<div class="mini-grid">${mini('Total Units', '1,074,073')}${mini('Good Units', '1,036,026')}${mini('Scrap Units', '38,047')}${mini('Unplanned Downtime', '2,859.10 h')}${mini('Scrap Cost', '$555,891')}</div>` +
    `<div class="dashboard-grid executive-charts">` +
      panel('OEE by Production Line', bars([['L1', 76.59], ['L2', 70.92], ['L3', 73.20], ['L4', 76.93]], 80, 'L2'), visual('Bar chart', 'Production Line', 'OEE %')) +
      panel('OEE by Shift', bars([['Shift A', 76.00], ['Shift B', 75.37], ['Shift C', 71.89]], 80, 'Shift C'), visual('Bar chart', 'Shift', 'OEE %')) +
      panel('OEE Trend', `<div class="trend-placeholder"><div class="trend-empty"><b>Daily trend data not supplied</b><span>Design placeholder for a date-level OEE measure in Power BI</span></div></div>`, visual('Line chart placeholder', 'Date', 'OEE %')) +
    `</div>` +
    `<div class="dashboard-grid executive-bottom">` +
      panel('Loss Overview', `<div class="loss-list"><div class="loss-item"><i class="loss-square"></i><span class="loss-name">Availability loss</span><span class="loss-pending">Value not supplied</span></div><div class="loss-item"><i class="loss-square"></i><span class="loss-name">Performance loss</span><span class="loss-pending">Value not supplied</span></div><div class="loss-item"><i class="loss-square"></i><span class="loss-name">Quality loss</span><span class="loss-pending">Value not supplied</span></div></div>`, visual('Category summary', 'Loss category', 'Loss measure')) +
      panel('Key Operational Findings', `<ol class="finding-list">${findings.map((item, i) => `<li><span class="finding-number">0${i + 1}</span><span>${item}</span></li>`).join('')}</ol>`, 'Associations and concentration findings from validated project outputs.') +
    `</div>`;
}

function scenario() {
  return `<section class="scenario"><div class="scenario-head"><h2>30% combined loss reduction</h2><span class="tag">MODELED SCENARIO · NOT REALIZED SAVINGS</span></div><div class="scenario-metrics"><div><small>Baseline OEE</small><strong>74.41%</strong></div><div><small>Projected OEE</small><strong>78.96%</strong></div><div><small>Projected uplift</small><strong>+4.55 pp</strong></div><div><small>Projected extra good units</small><strong>63,864 / year</strong></div><div><small>Projected annual recoverable value</small><strong>$1,688,452</strong></div></div><div class="scenario-note">Projection depends on the stated 30% combined loss-reduction assumption.</div></section>`;
}

function oee() {
  return heading('OEE Decomposition', 'A clear view of the three factors behind 74.41% OEE') +
    `<div class="stat-strip"><div class="formula-card"><small>Availability</small><strong>91.29%</strong></div><span class="operator">×</span><div class="formula-card"><small>Performance</small><strong>84.50%</strong></div><span class="operator">×</span><div class="formula-card"><small>Quality</small><strong>96.46%</strong></div><span class="operator">=</span><div class="formula-card result"><small>OEE</small><strong>74.41%</strong></div></div>` +
    `<div class="dashboard-grid split-2 section-margin">` +
      panel('OEE by Production Line', bars([['L1', 76.59], ['L2', 70.92], ['L3', 73.20], ['L4', 76.93]], 80, 'L2'), visual('Bar chart', 'Production Line', 'OEE %')) +
      panel('OEE by Shift', bars([['Shift A', 76.00], ['Shift B', 75.37], ['Shift C', 71.89]], 80, 'Shift C'), visual('Bar chart', 'Shift', 'OEE %')) +
    `</div><div class="dashboard-grid split-2 section-margin">` +
      panel('Availability / Performance / Quality', `<div class="bar-chart"><div class="bar-row"><span class="bar-label">Availability</span><div class="bar-track"><span class="bar-fill highlight" style="width:91.29%"></span></div><span class="bar-value">91.29%</span></div><div class="bar-row"><span class="bar-label">Performance</span><div class="bar-track"><span class="bar-fill highlight" style="width:84.5%"></span></div><span class="bar-value">84.50%</span></div><div class="bar-row"><span class="bar-label">Quality</span><div class="bar-track"><span class="bar-fill highlight" style="width:96.46%"></span></div><span class="bar-value">96.46%</span></div></div><div class="axis-hint"><span>0%</span><span>50%</span><span>100%</span></div>`, visual('Bar chart', 'OEE factor', 'Percentage')) +
      panel('Line-Level Exceptions', `<div class="metric-pair"><div><span>L2 Performance</span><strong>80.17%</strong></div><div><span>L3 Quality</span><strong>93.78%</strong></div></div><p class="small-note">Use these validated exceptions to direct further line and shift analysis.</p>`, visual('Cards', 'Production Line / factor', 'Validated percentage')) +
    `</div><div class="dashboard-grid split-2 section-margin">` +
      panel('Loss-Hour Decomposition', missing('Measure values not supplied', 'Reserve this panel for an availability, performance and quality loss-hour waterfall.'), visual('Waterfall chart placeholder', 'Loss stage', 'Loss hours')) +
      panel('Six Big Losses', `<table class="matrix"><tr><th>Supported category</th><th>Mapped source</th></tr><tr><td>Minor stops</td><td>Unplanned downtime</td></tr><tr><td>Changeovers</td><td>Unplanned downtime</td></tr><tr><td>Breakdowns</td><td>Unplanned downtime</td></tr><tr><td>Scrap defects</td><td>Quality losses</td></tr></table><p class="small-note">Complete six-loss mapping needs the remaining source-level classifications.</p>`, visual('Matrix', 'Loss class', 'Downtime / scrap measure')) +
    `</div>${scenario()}`;
}

function spc() {
  return heading('SPC Monitor', 'Phase II detection performance and alert burden', '<strong>1,097 lots</strong> · 46 failures') +
    `<div class="callout danger section-margin"><strong>Limit of the current alert rules.</strong> High recall was achieved at the cost of a very high false-positive burden. The project’s 60% precision target was not achieved.</div>` +
    `<div class="kpi-grid">${kpi('Phase II Lots', '1,097')}${kpi('Failures', '46')}${kpi('Combined False Alarms', '≈95.35', 'Per 100 lots')}${kpi('Modeled Early Detection', '≈17.98 h', 'Median before next-day 08:00 manual review')}</div>` +
    `<div class="dashboard-grid split-2 section-margin">` +
      panel('Method Comparison', `<table class="comparison"><thead><tr><th>Method</th><th>Recall</th><th>Precision</th></tr></thead><tbody><tr><td>Western Electric</td><td>100.00%</td><td><strong>4.23%</strong></td></tr><tr><td>WE + EWMA</td><td>100.00%</td><td><strong>4.21%</strong></td></tr></tbody></table>`, visual('Table', 'Method', 'Recall %, Precision %')) +
      panel('Precision vs Recall', `<div class="prec-chart"><div class="prec-row"><span>WE recall</span><div class="bar-track"><span class="bar-fill highlight" style="width:100%"></span></div><span>100%</span></div><div class="prec-row"><span>WE precision</span><div class="bar-track"><span class="bar-fill" style="width:4.23%"></span></div><span>4.23%</span></div><div class="prec-row"><span>WE + EWMA recall</span><div class="bar-track"><span class="bar-fill highlight" style="width:100%"></span></div><span>100%</span></div><div class="prec-row"><span>WE + EWMA precision</span><div class="bar-track"><span class="bar-fill" style="width:4.21%"></span></div><span>4.21%</span></div></div>`, visual('Clustered bar chart', 'Method / metric', 'Percentage')) +
    `</div><div class="dashboard-grid split-2">` +
      panel('Alert Volume', `<div class="metric-pair"><div><span>Combined false alarms</span><strong class="red">≈95.35</strong><span>per 100 lots</span></div><div><span>Precision target</span><strong>60%</strong><span>not achieved</span></div></div><div class="bar-chart"><div class="bar-row"><span class="bar-label">False alarms</span><div class="bar-track"><span class="bar-fill low" style="width:95.35%"></span></div><span class="bar-value">95.35</span></div></div>`, visual('Bar chart', 'Combined alert method', 'False alarms / 100 lots')) +
      panel('Detection Timing', `<div class="metric-pair"><div><span>Median modeled lead time</span><strong>≈17.98 h</strong></div><div><span>Manual review anchor</span><strong>08:00</strong><span>next day</span></div></div><p class="small-note">This lead time is modeled against the next manual review, not an observed intervention outcome.</p>`, visual('Card', 'Review time', 'Modeled lead time')) +
    `</div>`;
}

function paretoChart(items, unit, max, note, totalOverride) {
  const total = totalOverride || items.reduce((sum, item) => sum + item[1], 0);
  let running = 0;
  const plotLeft = 52, plotTop = 22, plotWidth = 490, plotHeight = 150;
  const step = plotWidth / items.length;
  const points = items.map((item, i) => { running += item[1]; return `${plotLeft + step * (i + .5)},${plotTop + plotHeight * (1 - running / total)}`; }).join(' ');
  const bars = items.map(([name, amount], i) => {
    const height = amount / max * plotHeight;
    const x = plotLeft + step * i + step * .2;
    const y = plotTop + plotHeight - height;
    const label = name.length > 13 ? name.slice(0, 12) + '…' : name;
    return `<rect x="${x}" y="${y}" width="${step * .6}" height="${height}" rx="2" fill="#4f78b7"/><text x="${x + step * .3}" y="${y - 5}" text-anchor="middle" fill="#355276" font-size="9">${unit === '$' ? '$' + Math.round(amount / 1000) + 'k' : Math.round(amount / 1000) + 'k'}</text><text x="${plotLeft + step * (i + .5)}" y="194" text-anchor="middle" fill="#65748a" font-size="8.5">${label}</text>`;
  }).join('');
  return `<div class="pareto-key"><span><i class="bar-key"></i>${unit === '$' ? 'Scrap cost' : 'Downtime minutes'}</span><span><i class="line-key"></i>Cumulative share</span></div><div class="pareto-wrap"><svg class="pareto-svg" viewBox="0 0 600 225" role="img" aria-label="Pareto chart of ${unit === '$' ? 'scrap cost' : 'downtime'} by cause"><line x1="${plotLeft}" y1="${plotTop + plotHeight}" x2="${plotLeft + plotWidth}" y2="${plotTop + plotHeight}" stroke="#b9c5d3"/><line x1="${plotLeft}" y1="${plotTop}" x2="${plotLeft}" y2="${plotTop + plotHeight}" stroke="#b9c5d3"/><line x1="${plotLeft + plotWidth}" y1="${plotTop}" x2="${plotLeft + plotWidth}" y2="${plotTop + plotHeight}" stroke="#d7dee7"/><text x="${plotLeft - 9}" y="${plotTop + 4}" text-anchor="end" fill="#8794a5" font-size="9">${unit === '$' ? '$' : ''}${Math.round(max / 1000)}k</text><text x="${plotLeft - 9}" y="${plotTop + plotHeight + 4}" text-anchor="end" fill="#8794a5" font-size="9">0</text><text x="${plotLeft + plotWidth + 9}" y="${plotTop + 4}" fill="#8794a5" font-size="9">100%</text><text x="${plotLeft + plotWidth + 9}" y="${plotTop + plotHeight + 4}" fill="#8794a5" font-size="9">0%</text>${bars}<polyline points="${points}" fill="none" stroke="#df9c45" stroke-width="2.5"/>${points.split(' ').map(p => {const [x, y] = p.split(',');return `<circle cx="${x}" cy="${y}" r="3.3" fill="#df9c45" stroke="#fff" stroke-width="1.5"/>`;}).join('')}<text x="${plotLeft + plotWidth / 2}" y="220" text-anchor="middle" fill="#8794a5" font-size="9">Cause</text></svg></div><p class="small-note">${note}</p>`;
}

function paretoPage() {
  const scrap = [['Dimensional',173077],['Surface defect',137940],['Contamination',102430],['Tool wear',97275],['Other',28601],['Supplier material',16568]];
  const downtime = [['Minor stop',80717.14],['Changeover',52781.48],['Breakdown',17040.77]];
  return heading('Pareto & RCA', 'Concentrated losses and evidence-based operational patterns') +
    `<div class="mini-grid">${mini('Scrap Cost', '$555,891')}${mini('Top 3 Scrap Causes', '74.38%')}${mini('Top 3 Scrap Cost', '$413,447')}${mini('Top 3 Downtime Causes', '87.75%')}${mini('Unplanned Downtime', '2,859.10 h')}</div>` +
    `<div class="dashboard-grid wide-left section-margin">` +
      panel('Scrap-Cost Pareto', paretoChart(scrap, '$', 180000, 'Top three causes: Dimensional, Surface defect and Contamination. Values and shares shown in the table below.'), visual('Line and clustered column chart', 'Scrap cause', 'Cost ($)', 'Line: cumulative %')) +
      panel('Scrap Cause Detail', `<table class="comparison"><thead><tr><th>Cause</th><th>Cost</th><th>Share</th></tr></thead><tbody><tr><td>Dimensional</td><td>$173,077</td><td>31.14%</td></tr><tr><td>Surface defect</td><td>$137,940</td><td>24.81%</td></tr><tr><td>Contamination</td><td>$102,430</td><td>18.43%</td></tr><tr><td>Tool wear</td><td>$97,275</td><td>17.50%</td></tr><tr><td>Other</td><td>$28,601</td><td>5.15%</td></tr><tr><td>Supplier material</td><td>$16,568</td><td>2.98%</td></tr></tbody></table>`, visual('Table', 'Scrap cause', 'Cost ($), share %')) +
    `</div><div class="dashboard-grid wide-left section-margin">` +
      panel('Downtime Pareto', paretoChart(downtime, 'min', 85000, 'Only the three supplied causes are plotted; the cumulative line ends at their 87.75% share of all unplanned downtime.', 2859.10 * 60), visual('Line and clustered column chart', 'Downtime cause', 'Minutes', 'Line: cumulative %')) +
      panel('Downtime Cause Detail', `<table class="comparison"><thead><tr><th>Cause</th><th>Minutes</th><th>Share</th></tr></thead><tbody><tr><td>Minor stop</td><td>80,717.14</td><td>47.05%</td></tr><tr><td>Changeover</td><td>52,781.48</td><td>30.77%</td></tr><tr><td>Breakdown</td><td>17,040.77</td><td>9.93%</td></tr></tbody></table>`, visual('Table', 'Downtime cause', 'Minutes, share %')) +
    `</div>` +
    panel('Root Cause Analysis Findings', `<ul class="rca-list"><li><b>L2 night shift</b>Elevated minor-stop activity is associated with lower Performance.</li><li><b>L3 tool wear</b>A progressive tool-wear deterioration pattern is associated with lower Quality.</li><li><b>P2 supplier material</b>A supplier-material excursion was identified.</li><li><b>S3 Processing</b>An operational bottleneck pattern was identified.</li></ul>`, 'These findings indicate associations and patterns; they do not establish proven causation.');
}

function orders() {
  return heading('Work Orders', 'Execution and schedule monitoring layout', 'No work-order values supplied in the brief') +
    `<div class="local-filter-note"><span>Page filters</span><strong>Date: all dates</strong><strong>Line: all lines</strong><strong>Status: all statuses</strong></div>` +
    `<div class="kpi-grid">${kpi('Work Orders', '—', 'Connect existing work-order measure', false, 'empty')}${kpi('Completed', '—', 'Connect status measure', false, 'empty')}${kpi('Open', '—', 'Connect status measure', false, 'empty')}${kpi('On-Time %', '—', 'Connect schedule measure', false, 'empty')}</div>` +
    `<div class="dashboard-grid split-3 section-margin">` +
      panel('Work-Order Status', missing('Status breakdown pending', 'Use existing work-order statuses only.'), visual('Bar chart placeholder', 'Work-order status', 'Count')) +
      panel('Work Orders by Line', missing('Line detail pending', 'Connect production-line relationships in the Power BI model.'), visual('Bar chart placeholder', 'Production Line', 'Work-order count')) +
      panel('Work-Order Trend', missing('Date-level data pending', 'Show daily or weekly work-order count after date data is connected.'), visual('Line chart placeholder', 'Date', 'Work-order count')) +
    `</div>` +
    panel('Work-Order Detail', `<div class="table-wrap"><table class="data-table"><thead><tr><th>Work Order</th><th>Production Line</th><th>Product</th><th>Planned Date</th><th>Actual Date</th><th>Status</th><th>Planned Units</th><th>Actual Units</th></tr></thead></table><div class="empty-table">No work-order rows were supplied for this visual reference.</div></div>`, visual('Table placeholder', 'Work order', 'Status, dates, line, product, units'));
}

function capacity() {
  return heading('Capacity & Manpower', 'Throughput, staffing and process constraints', 'Values shown only where supplied') +
    `<div class="kpi-grid">${kpi('Total Throughput', '1,074,073', 'Total units in the validated snapshot')}${kpi('Capacity Utilization', '—', 'Measure not supplied', false, 'empty')}${kpi('Planned Manpower', '—', 'Measure not supplied', false, 'empty')}${kpi('Manpower Gap', '—', 'Measure not supplied', false, 'empty')}</div>` +
    `<div class="dashboard-grid split-2 section-margin">` +
      panel('Throughput by Line', missing('Line-level throughput pending', 'Connect total units by production line.'), visual('Clustered bar chart placeholder', 'Production Line', 'Total Units')) +
      panel('Planned vs Actual Manpower', missing('Staffing measures pending', 'Use planned and actual manpower from the source model.'), visual('Grouped bar chart placeholder', 'Shift', 'Planned / Actual Manpower')) +
    `</div><div class="dashboard-grid split-2">` +
      panel('Line × Shift Capacity Matrix', `<table class="matrix"><thead><tr><th>Production Line</th><th>Shift A</th><th>Shift B</th><th>Shift C</th></tr></thead><tbody><tr><td>L1</td><td>—</td><td>—</td><td>—</td></tr><tr><td>L2</td><td>—</td><td>—</td><td>—</td></tr><tr><td>L3</td><td>—</td><td>—</td><td>—</td></tr><tr><td>L4</td><td>—</td><td>—</td><td>—</td></tr></tbody></table>`, visual('Matrix placeholder', 'Production Line / Shift', 'Capacity Utilization %')) +
      panel('Bottleneck Evidence', `<div class="bottleneck"><strong>S3 Processing</strong> was identified as an operational bottleneck.</div><p class="small-note">Add source-backed station cycle time and queue measures in Power BI to quantify the constraint.</p>`, visual('Bar chart / table reference', 'Workstation', 'Cycle time / wait time')) +
    `</div>`;
}

function quality() {
  return heading('Alerts & Data Quality', 'Validation coverage and analytical trust', '<strong>Validation snapshot</strong> · 259 tests passed') +
    `<div class="status-kpi">${kpi('Data-Quality Checks', '65 / 65', 'PASS', true, 'pass')}${kpi('Data-Quality Violations', '0')}${kpi('Rejected Database Rows', '0')}${kpi('Unresolved Foreign Keys', '0')}</div>` +
    `<div class="dashboard-grid split-2 section-margin">` +
      panel('Cross-System Reconciliation', `<div class="metric-pair"><div><span>Reconciliation checks</span><strong>75 / 75</strong><span>PASS</span></div><div><span>Power BI / SQL difference</span><strong>≈1.49e-14%</strong><span>Below 0.1% tolerance</span></div></div><p class="small-note">Power BI headline measures reconcile with PostgreSQL within the stated tolerance.</p>`, visual('Cards / table', 'System / measure', 'Difference %, check status')) +
      panel('Automated Test Status', `<div class="metric-pair"><div><span>Automated tests</span><strong>259</strong><span>passed</span></div><div><span>Data-quality checks</span><strong>65 / 65</strong><span>passed</span></div></div>`, visual('Cards', 'Validation suite', 'Pass count')) +
    `</div><div class="dashboard-grid split-2 section-margin">` +
      panel('Source-System Status', `<div class="source-row"><span>MES simulation</span><span>Live status not supplied</span></div><div class="source-row"><span>SECOM</span><span>Live status not supplied</span></div><div class="source-row"><span>MetroPT-3</span><span>Live status not supplied</span></div><div class="source-row"><span>PostgreSQL</span><span>Live status not supplied</span></div>`, visual('Table', 'Source system', 'Refresh / load status')) +
      panel('Alert Method Breakdown', `<table class="comparison"><thead><tr><th>Method</th><th>Recall</th><th>Precision</th></tr></thead><tbody><tr><td>Western Electric</td><td>100.00%</td><td>4.23%</td></tr><tr><td>WE + EWMA</td><td>100.00%</td><td>4.21%</td></tr></tbody></table><p class="small-note">Combined false alarms: approximately 95.35 per 100 lots.</p>`, visual('Table', 'Alert method', 'Recall %, Precision %')) +
    `</div>` +
    panel('Validation Register', `<div class="table-wrap"><table class="data-table"><thead><tr><th>Check Group</th><th>Result</th><th>Evidence</th></tr></thead><tbody><tr><td>Data-quality rules</td><td class="pass">PASS</td><td>65 / 65 checks; 0 violations</td></tr><tr><td>Database load</td><td class="pass">PASS</td><td>0 rejected rows; 0 unresolved foreign keys</td></tr><tr><td>Cross-system reconciliation</td><td class="pass">PASS</td><td>75 / 75 checks</td></tr><tr><td>Power BI / SQL KPI comparison</td><td class="pass">PASS</td><td>≈1.49e-14% difference; tolerance ≤0.1%</td></tr><tr><td>Automated tests</td><td class="pass">PASS</td><td>259 passed</td></tr></tbody></table></div>`, visual('Table', 'Validation group', 'Status, evidence'));
}

function render() {
  const id = location.hash.replace('#', '');
  const selected = pages.find(page => page.id === id) || pages[0];
  document.getElementById('page-nav').innerHTML = pages.map(page => `<button class="nav-tab${selected.id === page.id ? ' active' : ''}" type="button" data-page="${page.id}" aria-current="${selected.id === page.id ? 'page' : 'false'}">${page.name}</button>`).join('');
  document.getElementById('dashboard-content').innerHTML = selected.render();
  document.title = `${selected.name} | Production Yield & OEE`;
  document.querySelectorAll('.nav-tab').forEach(tab => tab.addEventListener('click', () => {
    location.hash = tab.dataset.page;
    if (location.hash.replace('#', '') === selected.id) render();
  }));
}

window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); });
render();
