// Build presentation/sciplay_results.pptx from presentation/deck_data.json.
// Run: uv run python presentation/export_deck_data.py && node presentation/build_deck.js
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const APPLY_THEME = process.env.APPLY_THEME_JS;
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data.json"), "utf8"));
const K = D.kpis;

const THEME = {
  name: "SciPlay Results",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1A1423", lt1: "FFFFFF", dk2: "2B1B4B", lt2: "F4F1F8",
    accent1: "6B3FA0", accent2: "F2B134", accent3: "1BAF7A", accent4: "E8664A",
    accent5: "3A86C8", accent6: "B9A6D6", hlink: "6B3FA0", folHlink: "8A6BB8",
  },
};
const HEX = THEME.colors;
const MUTED = "6E6680";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "SciPlay home assignment – results";
pres.author = "Yotam Hadar";
const C = pres.SchemeColor;
const W = 13.333;

// ----------------------------------------------------------------- layouts
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.2, w: 11.5, h: 1.5, fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.9, w: 11.5, h: 1.2, fontSize: 20, color: C.accent6, valign: "top", align: "left", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.9, fontSize: 30, bold: true, color: C.text2, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "SciPlay home assignment · Yotam Hadar", options: { x: 0.6, y: 7.0, w: 6, h: 0.3, fontSize: 10, color: MUTED, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: MUTED, align: "right" },
});
pres.defineSlideMaster({
  title: "CLOSING_DARK",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.9, fontSize: 30, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
});

// ----------------------------------------------------------------- helpers
const card = (slide, x, y, w, h, name, fill = C.background2) =>
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: name });

const numberCircle = (slide, x, y, n, fill, name) => {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.55, h: 0.55, fill: { color: fill }, line: { color: fill }, objectName: name });
  slide.addText(String(n), { x, y, w: 0.55, h: 0.55, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: name + " number" });
};

const stat = (slide, x, y, w, value, label, name, valueColor = C.accent1, labelColor = C.text1) => {
  slide.addText(value, { x, y, w, h: 0.95, fontSize: 54, bold: true, fontFace: THEME.headFontFace, color: valueColor, margin: 0, valign: "bottom", isTextBox: true, objectName: name + " value" });
  slide.addText(label, { x, y: y + 1.0, w, h: 0.75, fontSize: 15, color: labelColor, margin: 0, valign: "top", isTextBox: true, objectName: name + " label" });
};

const chartText = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", legendFontFace: "+mn-lt", titleFontFace: "+mn-lt",
  catAxisLabelColor: MUTED, valAxisLabelColor: MUTED, catAxisLabelFontSize: 11, valAxisLabelFontSize: 11, dataLabelFontSize: 11, dataLabelColor: MUTED, legendFontSize: 11, legendColor: MUTED };

const pct = (v) => `${Math.round(v * 100)}%`;

// ================================================================= slides
pres.addSection({ title: "Introduction" });

// 1 · Title
let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
s.addText("Where is player revenue at risk?", { placeholder: "title" });
s.addText([
  { text: "SciPlay · Data Science and AI Builder home assignment", options: { breakLine: true } },
  { text: "Yotam Hadar · November 2026", options: { fontSize: 16 } },
], { placeholder: "body" });
s.addNotes("Goal of the assignment: estimate each player's expected revenue through day 365 and flag, every day, the players who are underperforming, so the right team can act. This deck is updated as each part is completed; today it covers Part 1, data understanding.");

// 2 · Roadmap
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Introduction" });
s.addText("Four parts, one goal: find revenue at risk early", { placeholder: "title" });
const parts = [
  ["Data understanding", "Grain, coverage, missing data and the quality issues that change decisions", "Done", C.accent3],
  ["LTV 365", "Expected gross revenue through day 365 for every player, with confidence", "Next", C.accent2],
  ["Daily action lists", "Friction, revenue decline and engagement decline, ranked by value at risk", "Planned", C.accent6],
  ["Delivery & dashboard", "Push the lists to their owners; Streamlit app for exploration", "Planned", C.accent6],
];
parts.forEach(([head, desc, status, col], i) => {
  const x = 0.6 + i * 3.1, y = 2.0;
  card(s, x, y, 2.85, 3.9, `Part ${i + 1} card`);
  numberCircle(s, x + 0.3, y + 0.35, i + 1, i === 0 ? C.accent1 : C.text2, `Part ${i + 1} circle`);
  s.addText(head, { x: x + 0.3, y: y + 1.1, w: 2.3, h: 0.8, fontSize: 20, bold: true, fontFace: THEME.headFontFace, color: C.text2, margin: 0, valign: "top", isTextBox: true, objectName: `Part ${i + 1} heading` });
  s.addText(desc, { x: x + 0.3, y: y + 1.95, w: 2.3, h: 1.15, fontSize: 15, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: `Part ${i + 1} description` });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.3, y: y + 3.2, w: 1.2, h: 0.4, rectRadius: 0.2, fill: { color: col }, line: { color: col }, objectName: `Part ${i + 1} status pill` });
  s.addText(status, { x: x + 0.3, y: y + 3.2, w: 1.2, h: 0.4, fontSize: 12, bold: true, color: i === 0 ? C.background1 : C.text2, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: `Part ${i + 1} status` });
});
s.addNotes("The hiring brief is revenue driven, so every output is expressed in dollars: predicted LTV, revenue to date, and the gap between them, which is the value at risk.");

pres.addSection({ title: "Part 1 · Data understanding" });
const P1 = "Part 1 · Data understanding";

// 3 · Executive summary
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: P1 });
s.addText("Lists are feasible today; LTV365 must be extrapolated", { placeholder: "title" });
const stats = [
  [K.players.toLocaleString(), "players in a stratified sample: exactly 100 installs per month, May–Nov"],
  [String(K.max_age), "days since install for the oldest player; nobody is close to day 365"],
  [String(K.payers), `players ever paid (${pct(K.payers / K.players)}); every revenue estimate rests on them`],
];
stats.forEach(([v, l], i) => stat(s, 0.6 + i * 4.15, 1.6, 3.7, v, l, `Summary stat ${i + 1}`));
card(s, 0.6, 4.3, 12.1, 2.2, "So what box");
s.addText("So what", { x: 0.95, y: 4.5, w: 3, h: 0.4, fontSize: 18, bold: true, fontFace: THEME.headFontFace, color: C.accent1, margin: 0, isTextBox: true, objectName: "So what heading" });
s.addText([
  { text: "There is no real 365-day outcome to train on: LTV365 = revenue so far + modelled revenue still to come, validated on a window we can observe.", options: { bullet: true, breakLine: true } },
  { text: "Rows exist only on days a player plays, so scoring needs a daily as-of table or inactive players drop out of the lists.", options: { bullet: true, breakLine: true } },
  { text: "Three data issues would distort LTV and backtests if ignored; each has a fix in the pipeline.", options: { bullet: true } },
], { x: 0.95, y: 4.95, w: 11.4, h: 1.45, fontSize: 15, color: C.text1, margin: 0, paraSpaceAfter: 6, valign: "top", isTextBox: true, objectName: "So what bullets" });
s.addNotes(`700 players, ${K.days} days of data, ${K.rows.toLocaleString()} rows and ${K.columns} columns. The headline: the data can tell us who is slipping today, but it cannot show a full first year for anyone.`);

// 4 · Grain and coverage
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: P1 });
s.addText("One row = one player, on one platform, on a day they played", { placeholder: "title" });
s.addText([
  { text: `${K.rows.toLocaleString()} rows × ${K.columns} columns: a daily summary per player, not raw events`, options: { bullet: true, breakLine: true } },
  { text: `${K.days} continuous days, 9 May – 4 Nov 2026, no gaps`, options: { bullet: true, breakLine: true } },
  { text: "A missing row means the player did not play that day, not missing data", options: { bullet: true, breakLine: true } },
  { text: `${K.multi_platform_player_days} player-days have two platform rows; they are combined into one`, options: { bullet: true, breakLine: true } },
  { text: "November's 100 installs all fall in Nov 1–4, so the last days are distorted", options: { bullet: true } },
], { x: 0.6, y: 1.6, w: 4.3, h: 4.9, fontSize: 15, color: C.text1, margin: 0, paraSpaceAfter: 10, valign: "top", isTextBox: true, objectName: "Grain bullets" });
const cohorts = Object.keys(D.weekly_active.series);
const cohortLabel = (c) => new Date(c + "-01").toLocaleString("en-US", { month: "short" });
s.addChart(pres.charts.AREA, cohorts.map((c) => ({ name: cohortLabel(c), labels: D.weekly_active.weeks, values: D.weekly_active.series[c] })), {
  x: 5.2, y: 1.45, w: 7.5, h: 5.2, barGrouping: "stacked",
  chartColors: ["6B3FA0", "F2B134", "1BAF7A", "E8664A", "3A86C8", "B9A6D6", "2B1B4B"],
  showTitle: true, title: "Average daily active players per week, by install month", titleFontSize: 13, titleColor: HEX.dk2,
  showLegend: true, legendPos: "b", catAxisLabelFrequency: 4, valGridLine: { color: "E6E2EC", size: 0.5 }, catGridLine: { style: "none" },
  valAxisMinVal: 0, ...chartText, objectName: "Active players by cohort chart",
});
s.addNotes("Daily active players grow over time only because the sample adds a new 100-install cohort every month while older cohorts keep playing. This is the sample design, not growth, so totals here are sample totals, not population totals.");

// 5 · Players are sparse
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: P1 });
s.addText("Most players leave after their first day, and payers are rare", { placeholder: "title" });
s.addChart(pres.charts.BAR, [{ name: "Players", labels: D.rows_per_player.labels, values: D.rows_per_player.players }], {
  x: 0.6, y: 1.45, w: 7.4, h: 5.2, barDir: "col", chartColors: ["6B3FA0"], barGapWidthPct: 60,
  showTitle: true, title: "Players by number of active days observed", titleFontSize: 13, titleColor: HEX.dk2,
  showValue: true, dataLabelPosition: "outEnd", showLegend: false,
  valGridLine: { color: "E6E2EC", size: 0.5 }, catGridLine: { style: "none" }, valAxisHidden: true,
  showCatAxisTitle: true, catAxisTitle: "Active days", catAxisTitleColor: MUTED, catAxisTitleFontSize: 11, catAxisTitleFontFace: "+mn-lt",
  ...chartText, objectName: "Rows per player chart",
});
const heatFirst = D.heatmap.values.map((r) => r[1]).filter((v) => v !== null);
const d1 = heatFirst.reduce((a, b) => a + b, 0) / heatFirst.length;
[
  [pct(K.one_row_players / K.players), "of players were seen on a single day only"],
  [`~${pct(d1)}`, "come back the day after install"],
  [pct(K.payers / K.players), `ever paid: ${K.payers} players carry all the revenue`],
].forEach(([v, l], i) => stat(s, 8.6, 1.5 + i * 1.75, 4.1, v, l, `Player stat ${i + 1}`));
s.addNotes(`Median player has ${K.median_rows} active days. With ${K.payers} payers, any spend model will be uncertain; the LTV output therefore carries a confidence level, and the model is kept simple.`);

// 6 · Retention heatmap table
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: P1 });
s.addText("Cohorts retain alike, so one pooled curve can drive LTV", { placeholder: "title" });
const shade = (v) => (v === null ? "EEEDF0" : v >= 0.5 ? "2B1B4B" : v >= 0.3 ? "6B3FA0" : v >= 0.2 ? "9A7BC4" : v >= 0.15 ? "C3B1DE" : "E3D9F0");
const ink = (v) => (v === null ? MUTED : v >= 0.2 ? "FFFFFF" : HEX.dk1);
const monthName = (c) => new Date(c + "-01").toLocaleString("en-US", { month: "short", year: "numeric" });
const head = [{ text: "Install month", options: { bold: true, color: HEX.dk2, fill: { color: "FFFFFF" }, align: "left" } },
  ...D.heatmap.buckets.map((b) => ({ text: b, options: { bold: true, color: HEX.dk2, fill: { color: "FFFFFF" }, align: "center" } }))];
const rows = D.heatmap.cohorts.map((c, i) => [
  { text: monthName(c), options: { color: HEX.dk1, fill: { color: "FFFFFF" }, align: "left" } },
  ...D.heatmap.values[i].map((v) => ({ text: v === null ? "n/a" : pct(v), options: { color: ink(v), fill: { color: shade(v) }, align: "center" } })),
]);
s.addTable([head, ...rows], {
  x: 0.6, y: 1.55, w: 12.1, colW: [1.6, ...Array(10).fill(1.05)], rowH: 0.5, fontSize: 13, fontFace: THEME.bodyFontFace,
  border: { type: "solid", pt: 2, color: "FFFFFF" }, valign: "middle", objectName: "Cohort activity table",
});
s.addText("Share of each install cohort active in each age bucket (days since install). A player counts only after living through the whole bucket; n/a = not observable yet.", {
  x: 0.6, y: 5.75, w: 12.1, h: 0.5, fontSize: 12, color: MUTED, margin: 0, isTextBox: true, objectName: "Heatmap caption" });
s.addNotes("About 30% return on day 1 and 13-16% are still active between days 91 and 120. The cohorts look alike, which supports pooling them into one decay curve for the LTV extrapolation, instead of fitting each small cohort separately.");

// 7 · Data quality issues
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: P1 });
s.addText("Three data issues that would change business decisions", { placeholder: "title" });
const issues = [
  [pct(D.d365.share_equal_lifetime_revenue), "D365_SPEND equals lifetime revenue so far", "It is not a 365-day outcome. Training on it predicts that young players are worth only what they spent so far, so acquisition and CRM budgets would be set too low."],
  [pct(D.offset.matches_next_row_change), "of purchases show up in the next day's lifetime total", "Lifetime revenue is a start-of-day value. Adding daily revenue to it double counts; using it alone misses today's purchases."],
  ["91 days", "rows keep being rewritten after their date", "Milestone fields are filled in later, so a row can hold future information. Backtests on this file would look better than production."],
];
issues.forEach(([v, head, impact], i) => {
  const x = 0.6 + i * 4.1;
  card(s, x, 1.55, 3.85, 4.0, `Issue ${i + 1} card`);
  s.addText(v, { x: x + 0.3, y: 1.75, w: 3.25, h: 0.95, fontSize: 48, bold: true, fontFace: THEME.headFontFace, color: C.accent1, margin: 0, valign: "bottom", isTextBox: true, objectName: `Issue ${i + 1} value` });
  s.addText(head, { x: x + 0.3, y: 2.8, w: 3.25, h: 0.85, fontSize: 16, bold: true, color: C.text2, margin: 0, valign: "top", isTextBox: true, objectName: `Issue ${i + 1} heading` });
  s.addText(impact, { x: x + 0.3, y: 3.7, w: 3.25, h: 1.7, fontSize: 14, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: `Issue ${i + 1} impact` });
});
s.addText(`Also: ${K.dead_columns} of ${K.columns} columns are empty or constant · cheater and legal-settlement flags are never set · the sample is fixed at 100 installs per month`, {
  x: 0.6, y: 5.85, w: 12.1, h: 0.45, fontSize: 12, color: MUTED, margin: 0, isTextBox: true, objectName: "Other issues" });
s.addNotes(`Q1: D365_SPEND equals LIFETIME_REVENUE on every filled row, is empty for non-payers, and changes across snapshots for ${D.d365.players_value_changes_across_snapshots} of ${D.d365.players_filled} payers. Q2: daily revenue matches the change into the same row only ${pct(D.offset.matches_same_row_change)} of the time. Q3: 95% of June-July rows were last updated exactly 91 days after their date; May rows froze at the first batch on 3 Sep.`);

// 8 · Implications
s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: P1 });
s.addText("What this means for the next parts", { placeholder: "title" });
const next = [
  ["LTV 365", "Revenue so far + modelled remaining revenue; validated on the next 30 days, which the data can observe"],
  ["As-of table", "Carry each player's last day forward so inactive players are still scored"],
  ["Leakage registry", "Exclude D365_SPEND, NEXT_LOGIN_DATE and back-filled milestone fields from features"],
  ["Action lists", "Compare players with their own history and with their cohort; dollars at risk set the priority"],
];
next.forEach(([head, body], i) => {
  const y = 1.6 + i * 1.3;
  numberCircle(s, 0.6, y + 0.05, i + 1, C.accent1, `Next ${i + 1} circle`);
  s.addText(head, { x: 1.4, y, w: 3.2, h: 0.65, fontSize: 20, bold: true, fontFace: THEME.headFontFace, color: C.accent2, margin: 0, valign: "middle", isTextBox: true, objectName: `Next ${i + 1} heading` });
  s.addText(body, { x: 4.7, y, w: 8.0, h: 0.65, fontSize: 16, color: C.background1, margin: 0, valign: "middle", isTextBox: true, objectName: `Next ${i + 1} body` });
});
s.addNotes("Each data finding maps to a design decision in the pipeline. Next step: the LTV model.");

(async () => {
  const out = path.join(__dirname, "sciplay_results.pptx");
  await pres.writeFile({ fileName: out });
  if (APPLY_THEME) {
    const { applyTheme } = require(APPLY_THEME);
    await applyTheme(out, THEME);
  }
  console.log("wrote " + out);
})();
