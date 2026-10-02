"""Endowment Manager Evaluation: skill or luck?

Run with:  python analysis.py
Downloads fund prices (yfinance) and Fama-French factors, then writes results to output/.
"""
import io
import zipfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

DATA = Path("data")
OUT = Path("output")
DATA.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

ACTIVE = ["FCNTX", "AGTHX", "TRBCX"]
INDEX = "VFIAX"
FUNDS = ACTIVE + [INDEX]
SIXTY_FORTY = ["VTSMX", "VBMFX"]
START = "2015-01"
FF_URL = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
          "F-F_Research_Data_Factors_CSV.zip")


# ---------- Block 1: data ----------
def load_prices():
    """Monthly adjusted closes (dividends reinvested) for all tickers."""
    px = yf.download(FUNDS + SIXTY_FORTY, start="2014-06-01", interval="1mo",
                     auto_adjust=True, progress=False)["Close"]
    px.index = px.index.to_period("M")
    px.to_csv(DATA / "prices_raw.csv")
    return px


def load_factors():
    """Monthly Fama-French 3 factors, in percent."""
    raw = requests.get(FF_URL, timeout=60).content
    z = zipfile.ZipFile(io.BytesIO(raw))
    text = z.read(z.namelist()[0]).decode("latin1")
    (DATA / "ff_factors_raw.csv").write_text(text)
    rows = []
    for line in text.splitlines():
        if "Annual" in line:          # monthly section ends here
            break
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 5 and len(parts[0]) == 6 and parts[0].isdigit():
            rows.append(parts)
    ff = pd.DataFrame(rows, columns=["month", "Mkt-RF", "SMB", "HML", "RF"])
    ff.index = pd.PeriodIndex(ff.pop("month"), freq="M")
    return ff.astype(float)


prices = load_prices()
returns = prices.pct_change() * 100          # monthly % returns
factors = load_factors()

# one table: one row per month, fund returns + factors (only months with factor data)
panel = returns.join(factors, how="inner").loc[START:].dropna()
print(f"Monthly table: {panel.index[0]} to {panel.index[-1]}, {len(panel)} months")
print(panel.head(3).round(2).to_string())

# sanity chart: growth of $10,000
growth = 10_000 * (1 + panel[FUNDS] / 100).cumprod()
fig, ax = plt.subplots(figsize=(8, 4.5))
for t in FUNDS:
    ax.plot(growth.index.to_timestamp(), growth[t], label=t,
            lw=2.2 if t == INDEX else 1.4, color="black" if t == INDEX else None)
ax.set_title(f"Growth of $10,000, {panel.index[0]} to {panel.index[-1]}")
ax.set_ylabel("Value ($)")
ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
ax.legend(frameon=False)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "growth_10k.png", dpi=150)
print("\n$10,000 grew to:")
print(growth.iloc[-1].round(0).to_string())


# ---------- Block 2: simple comparison table ----------
# Net expense ratios in % per year, from each fund's own website (checked Oct 2, 2026):
# FCNTX fidelity.com (as of 2/28/2026), AGTHX capitalgroup.com (Class A),
# TRBCX troweprice.com, VFIAX investor.vanguard.com (as of 4/28/2026).
FEES = {"FCNTX": 0.74, "AGTHX": 0.59, "TRBCX": 0.70, "VFIAX": 0.04}

years = len(panel) / 12
summary = pd.DataFrame(index=FUNDS)
for t in FUNDS:
    r = panel[t] / 100
    excess = r - panel["RF"] / 100
    wealth = (1 + r).cumprod()
    summary.loc[t, "Avg yearly return"] = wealth.iloc[-1] ** (1 / years) - 1
    summary.loc[t, "Yearly volatility"] = r.std() * 12 ** 0.5
    summary.loc[t, "Worst drop"] = (wealth / wealth.cummax() - 1).min()
    summary.loc[t, "Sharpe ratio"] = excess.mean() * 12 / (excess.std() * 12 ** 0.5)
    summary.loc[t, "Yearly fee"] = FEES[t] / 100 if FEES[t] is not None else None
summary.index.name = "Fund"

print("\nBlock 2 comparison table:")
show = summary.copy()
for c in ["Avg yearly return", "Yearly volatility", "Worst drop"]:
    show[c] = show[c].map(lambda x: "" if pd.isna(x) else f"{x:.1%}")
show["Yearly fee"] = show["Yearly fee"].map(lambda x: "" if pd.isna(x) else f"{x:.2%}")
show["Sharpe ratio"] = show["Sharpe ratio"].round(2)
print(show.to_string())
summary.to_csv(OUT / "summary_table.csv", float_format="%.4f")


# ---------- Block 3: skill or just the market? (Fama-French 3-factor regression) ----------
# fund return - RF = alpha + b1*(Mkt-RF) + b2*SMB + b3*HML + error   (monthly, in %)
X = sm.add_constant(panel[["Mkt-RF", "SMB", "HML"]])
for t in ACTIVE:
    fit = sm.OLS(panel[t] - panel["RF"], X).fit()
    lo, hi = fit.conf_int().loc["const"] * 12 / 100        # monthly % -> yearly decimal
    summary.loc[t, "Alpha per year"] = fit.params["const"] * 12 / 100
    summary.loc[t, "Alpha CI low"] = lo
    summary.loc[t, "Alpha CI high"] = hi
    summary.loc[t, "Alpha p-value"] = fit.pvalues["const"]
    summary.loc[t, "Market beta"] = fit.params["Mkt-RF"]
    summary.loc[t, "SMB beta"] = fit.params["SMB"]
    summary.loc[t, "HML beta"] = fit.params["HML"]
    summary.loc[t, "R-squared"] = fit.rsquared
    summary.loc[t, "Verdict"] = ("clearly positive" if lo > 0 else
                                 "clearly negative" if hi < 0 else "can't tell")

print("\nBlock 3 skill-or-luck regression (alpha is after fees, per year):")
reg = summary.loc[ACTIVE, ["Alpha per year", "Alpha CI low", "Alpha CI high", "Alpha p-value",
                           "Market beta", "SMB beta", "HML beta", "R-squared", "Verdict"]].copy()
for c in ["Alpha per year", "Alpha CI low", "Alpha CI high"]:
    reg[c] = reg[c].map(lambda x: f"{x:+.1%}")
for c in ["Alpha p-value", "Market beta", "SMB beta", "HML beta", "R-squared"]:
    reg[c] = reg[c].astype(float).round(2)
print(reg.to_string())
summary.to_csv(OUT / "summary_table.csv", float_format="%.4f")


# ---------- Block 4: Cornell vs. a simple 60/40 portfolio and its peers ----------
cornell = pd.read_csv(DATA / "cornell_returns.csv", index_col="fiscal_year")
annualized = pd.read_csv(DATA / "cornell_annualized.csv")

# sanity check: FY2016-FY2025 should compound to Cornell's reported 10-year 8.6%/yr
ten = (1 + cornell.loc[2016:2025, "cornell"] / 100).prod() ** (1 / 10) - 1
print(f"\nSanity check: Cornell FY2016-25 compounds to {ten:.2%}/yr (Cornell reports 8.6%)")

# 60% total stock market + 40% total bond market, rebalanced monthly
m6040 = (0.6 * returns["VTSMX"] + 0.4 * returns["VBMFX"]) / 100
fy = m6040.index.year + (m6040.index.month >= 7)        # July 2014 -> FY2015
fy_6040 = (1 + m6040).groupby(fy).prod() - 1
months = m6040.groupby(fy).count()

cvs = pd.DataFrame({
    "Cornell": cornell["cornell"] / 100,
    "60/40": fy_6040.reindex(cornell.index),
})
cvs["Difference"] = cvs["Cornell"] - cvs["60/40"]
cvs["Peer median"] = cornell["peer_median"] / 100
cvs.index.name = "Fiscal year"
assert (months.reindex(cvs.index) == 12).all(), "every fiscal year needs 12 months"

n = len(cvs)
sd_diff = cvs["Difference"].std()
gap_needed = 2 * sd_diff / n ** 0.5
cornell_stats = {
    "Average Cornell": cvs["Cornell"].mean(),
    "Average 60/40": cvs["60/40"].mean(),
    "Average difference": cvs["Difference"].mean(),
    "SD of difference": sd_diff,
    "Years": n,
    "Gap needed to be sure (2 x SD / sqrt(years))": gap_needed,
    "Average Cornell, FY2020-25": cvs.loc[2020:, "Cornell"].mean(),
    "Average peer median, FY2020-25": cvs.loc[2020:, "Peer median"].mean(),
    "Average difference excl. FY2021": cvs["Difference"].drop(2021).mean(),
}
print("\nBlock 4 Cornell vs 60/40 by fiscal year:")
print(cvs.map(lambda x: "" if pd.isna(x) else f"{x:+.1%}").to_string())
print()
for k, v in cornell_stats.items():
    print(f"  {k}: {v}" if k == "Years" else f"  {k}: {v:+.2%}")

fig, ax = plt.subplots(figsize=(8, 4.5))
x = range(n)
ax.bar([i - 0.2 for i in x], cvs["Cornell"] * 100, 0.4, label="Cornell (after fees)", color="#B31B1B")
ax.bar([i + 0.2 for i in x], cvs["60/40"] * 100, 0.4, label="60/40 index portfolio", color="#7f7f7f")
ax.set_xticks(list(x), [f"FY{str(y)[2:]}" for y in cvs.index])
ax.axhline(0, color="black", lw=0.8)
ax.set_ylabel("Fiscal-year return (%)")
ax.set_title("Cornell endowment vs. a simple 60/40 portfolio, FY2015-FY2025")
ax.legend(frameon=False)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "cornell_vs_6040.png", dpi=150)


# ---------- Block 5: Excel summary workbook ----------
from datetime import date
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

NAMES = {"FCNTX": "Fidelity Contrafund", "AGTHX": "American Funds Growth Fund of America (A)",
         "TRBCX": "T. Rowe Price Blue Chip Growth", "VFIAX": "Vanguard 500 Index (Admiral)"}
FONT = "Arial"
PLAIN = Font(name=FONT)
BOLD = Font(name=FONT, bold=True)
INPUT = Font(name=FONT, color="0000FF")          # blue = typed-in source data
HEAD_FILL = PatternFill("solid", fgColor="D9D9D9")
PCT, PCT2 = "0.0%", "0.00%"
period = f"{panel.index[0].strftime('%b %Y')} to {panel.index[-1].strftime('%b %Y')}"
n_sig = int((summary.loc[ACTIVE, "Verdict"] != "can't tell").sum())
best = summary.loc[ACTIVE, "Alpha per year"].astype(float).idxmax()

bottom_line = [
    f"After fees, {n_sig} of the 3 active funds showed statistically significant alpha over "
    f"{period} ({len(panel)} months, 95% level). {NAMES[best]} had the highest estimate, "
    f"{summary.loc[best, 'Alpha per year']:+.1%}/yr (95% CI {summary.loc[best, 'Alpha CI low']:+.1%} "
    f"to {summary.loc[best, 'Alpha CI high']:+.1%}).",
    f"Cornell's FY2015-FY2025 returns averaged {cornell_stats['Average Cornell']:.1%} vs. "
    f"{cornell_stats['Average 60/40']:.1%} for a simple 60/40 index portfolio. The "
    f"{cornell_stats['Average difference']:+.1%} gap is far below the ~{gap_needed:.1%}/yr "
    f"needed to tell skill from luck with {n} years of data.",
    "Conclusion: about 10 years of returns cannot prove skill for either the funds or the endowment; "
    "fees and style (factor) exposure explain most of what looks like outperformance.",
]


def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font, cell.fill = BOLD, HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def set_widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


wb = Workbook()

# Sheet 1: Summary
ws = wb.active
ws.title = "Summary"
ws["A1"] = "Endowment Manager Evaluation: Skill or Luck?"
ws["A1"].font = Font(name=FONT, bold=True, size=14)
ws["A2"] = f"Prepared {date.today():%B %d, %Y}. Fund data {period}; Cornell data FY2015-FY2025."
ws["A2"].font = PLAIN
ws["A4"] = "Bottom line"
ws["A4"].font = BOLD
for i, s in enumerate(bottom_line):
    cell = ws.cell(row=5 + i, column=1, value=s)
    cell.font = PLAIN
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[5 + i].height = 34
ws["A9"] = "Other sheets: fund comparison, Cornell vs. 60/40, and data sources and limitations (Notes)."
ws["A9"].font = Font(name=FONT, italic=True)
set_widths(ws, [110])
ws.freeze_panes = "A2"

# Sheet 2: Fund comparison
ws = wb.create_sheet("Fund comparison")
cols = [("Fund", "Fund", None), ("Name", None, None),
        ("Avg yearly return", "Avg yearly return", PCT), ("Yearly volatility", "Yearly volatility", PCT),
        ("Worst drop", "Worst drop", PCT), ("Sharpe ratio", "Sharpe ratio", "0.00"),
        ("Yearly fee", "Yearly fee", PCT2), ("Alpha per year", "Alpha per year", PCT),
        ("Alpha 95% CI low", "Alpha CI low", PCT), ("Alpha 95% CI high", "Alpha CI high", PCT),
        ("Alpha p-value", "Alpha p-value", "0.00"), ("Market beta", "Market beta", "0.00"),
        ("R-squared", "R-squared", "0.00"), ("Verdict", "Verdict", None)]
for c, (h, _, _) in enumerate(cols, 1):
    ws.cell(row=1, column=c, value=h)
style_header(ws, 1, len(cols))
for r, t in enumerate(FUNDS, 2):
    for c, (h, key, fmt) in enumerate(cols, 1):
        if h == "Fund":
            v = t
        elif h == "Name":
            v = NAMES[t]
        elif t == INDEX and h == "Verdict":
            v = "benchmark (index fund)"
        else:
            v = summary.loc[t, key]
            v = None if pd.isna(v) else v
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = float(v)
        cell = ws.cell(row=r, column=c, value=v)
        cell.font = INPUT if h == "Yearly fee" else PLAIN
        if fmt:
            cell.number_format = fmt
note_row = len(FUNDS) + 3
for i, s in enumerate([
    f"Returns are monthly, {period}, after fund fees (adjusted prices include reinvested dividends).",
    "Alpha: Fama-French 3-factor regression of (fund return - RF) on Mkt-RF, SMB, HML; monthly alpha x 12.",
    "Verdict: 'clearly positive/negative' only if the whole 95% confidence interval is above/below zero.",
    "Blue = typed in by hand from each fund's website (net expense ratio, checked Oct 2, 2026).",
]):
    ws.cell(row=note_row + i, column=1, value=s).font = Font(name=FONT, italic=True)
set_widths(ws, [9, 38, 12, 12, 11, 9, 9, 11, 12, 12, 10, 10, 10, 22])
ws.row_dimensions[1].height = 32
ws.freeze_panes = "A2"

# Sheet 3: Cornell vs 60-40 (difference and statistics are live Excel formulas)
ws = wb.create_sheet("Cornell vs 60-40")
heads = ["Fiscal year", "Cornell", "60/40", "Difference", "Peer median", "Source (Cornell, peer)"]
for c, h in enumerate(heads, 1):
    ws.cell(row=1, column=c, value=h)
style_header(ws, 1, len(heads))
first = 2
for r, (yr, row) in enumerate(cvs.iterrows(), first):
    ws.cell(row=r, column=1, value=f"FY{yr}").font = PLAIN
    ws.cell(row=r, column=2, value=float(row["Cornell"])).font = INPUT
    ws.cell(row=r, column=3, value=float(row["60/40"])).font = PLAIN
    ws.cell(row=r, column=4, value=f"=B{r}-C{r}").font = PLAIN
    if pd.notna(row["Peer median"]):
        ws.cell(row=r, column=5, value=float(row["Peer median"])).font = INPUT
    ws.cell(row=r, column=6, value=cornell.loc[yr, "source"]).font = PLAIN
    for c in range(2, 6):
        ws.cell(row=r, column=c).number_format = PCT
last = first + n - 1
fy2021_row = first + list(cvs.index).index(2021)

s = last + 2
stats = [
    ("Average", f"=AVERAGE(B{first}:B{last})", f"=AVERAGE(C{first}:C{last})",
     f"=AVERAGE(D{first}:D{last})", PCT),
    ("SD of difference", None, None, f"=STDEV(D{first}:D{last})", PCT),
    ("Number of years", None, None, f"=COUNT(D{first}:D{last})", "0"),
    ("Gap needed to be sure (2 x SD / sqrt(years))", None, None, f"=2*D{s + 1}/SQRT(D{s + 2})", PCT),
    ("Average difference excluding FY2021", None, None,
     f"=(SUM(D{first}:D{last})-D{fy2021_row})/(D{s + 2}-1)", PCT),
]
for i, (label, b, c_, d, fmt) in enumerate(stats):
    r = s + i
    ws.cell(row=r, column=1, value=label).font = BOLD
    for col, v in ((2, b), (3, c_), (4, d)):
        if v:
            cell = ws.cell(row=r, column=col, value=v)
            cell.font, cell.number_format = BOLD, fmt
ws.cell(row=s + len(stats), column=1,
        value="Reading: the average yearly gap must exceed the 'gap needed' figure before it is "
              "clearly more than luck.").font = Font(name=FONT, italic=True)

a = s + len(stats) + 2
ws.cell(row=a, column=1,
        value="Annualized returns to June 30, 2025 (Cornell June 2025 Quarterly Report)").font = BOLD
ah = ["Period", "Cornell", "Cornell target portfolio", "Peer median"]
for c, h in enumerate(ah, 1):
    ws.cell(row=a + 1, column=c, value=h)
style_header(ws, a + 1, len(ah))
for i, row in annualized.iterrows():
    r = a + 2 + i
    ws.cell(row=r, column=1, value=row["period"]).font = PLAIN
    for c, k in ((2, "cornell"), (3, "cornell_target_portfolio"), (4, "peer_median")):
        cell = ws.cell(row=r, column=c, value=float(row[k]) / 100)
        cell.font, cell.number_format = INPUT, PCT
ws.cell(row=a + 7, column=1,
        value="Blue = typed in from Cornell's published reports (see Notes).").font = Font(name=FONT, italic=True)

chart = BarChart()
chart.type = "col"
chart.title = "Cornell vs. 60/40 by fiscal year"
chart.y_axis.title = "Return"
chart.y_axis.numFmt = "0%"
chart.y_axis.delete = False
chart.x_axis.delete = False
chart.add_data(Reference(ws, min_col=2, max_col=3, min_row=1, max_row=last), titles_from_data=True)
chart.set_categories(Reference(ws, min_col=1, min_row=first, max_row=last))
chart.width, chart.height = 18, 9
ws.add_chart(chart, "H2")
set_widths(ws, [44, 11, 12, 12, 12, 46])
ws.freeze_panes = "A2"

# Sheet 4: Notes
ws = wb.create_sheet("Notes")
notes = [
    ("Data sources", None),
    ("Fund prices (monthly, dividend-adjusted)", "Yahoo Finance via the yfinance Python package"),
    ("Fama-French 3 factors (monthly)", FF_URL),
    ("Expense ratios", "Each fund's own website (fidelity.com, capitalgroup.com, troweprice.com, "
                       "investor.vanguard.com), checked Oct 2, 2026"),
    ("Cornell investment reports", "https://investmentoffice.cornell.edu"),
    ("Cornell returns and peer median", "FY2020-25 and annualized figures: Cornell June 2025 Quarterly Report. "
                                        "FY2015-19: Cornell Chronicle; FY2017: Chief Investment Officer / "
                                        "Pensions & Investments. Peer median = BNY Endowments & Foundations median."),
    ("60/40 portfolio", "60% VTSMX (Vanguard Total Stock Market) + 40% VBMFX (Vanguard Total Bond Market), "
                        "rebalanced monthly, July-June fiscal years"),
    ("Code", "analysis.py in this repository rebuilds every number and this workbook"),
    (None, None),
    ("Limitations", None),
    ("Survivorship bias", "The 3 funds were picked because they still exist and are well known; funds that "
                          "did badly and closed are missing, which flatters active managers."),
    ("Small sample", "Only 3 active funds and about 11.7 years of monthly data; most alphas cannot be told "
                     "apart from zero."),
    ("Factor model", "US-stock-only 3-factor model (market, size, value); no momentum, quality or "
                     "international factors."),
    ("Cornell comparison", "Cornell's returns are after its managers' fees; it holds private investments "
                           "valued infrequently, which smooths returns; 11 years is short and FY2021 "
                           "(+41.9%) dominates."),
    ("Peer median", "Only collected here for FY2020-FY2025."),
]
for r, (k, v) in enumerate(notes, 1):
    if k:
        cell = ws.cell(row=r, column=1, value=k)
        cell.font = BOLD if v is None else PLAIN
        cell.alignment = Alignment(vertical="top")
        if v is None:
            cell.fill = HEAD_FILL
    if v:
        cell = ws.cell(row=r, column=2, value=v)
        cell.font = PLAIN
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if v.startswith("http"):
            cell.hyperlink = v
            cell.font = Font(name=FONT, color="0563C1", underline="single")
set_widths(ws, [36, 110])
ws.freeze_panes = "A2"

wb.save(OUT / "summary.xlsx")
print("\nSaved output/summary.xlsx")


# ---------- Block 6: memo chart (alpha with 95% confidence intervals) ----------
al = summary.loc[ACTIVE, ["Alpha per year", "Alpha CI low", "Alpha CI high"]].astype(float) * 100
fig, ax = plt.subplots(figsize=(7, 3.6))
y = range(len(ACTIVE))
ax.errorbar(al["Alpha per year"], y,
            xerr=[al["Alpha per year"] - al["Alpha CI low"], al["Alpha CI high"] - al["Alpha per year"]],
            fmt="o", color="#B31B1B", ecolor="#555555", capsize=6, ms=8, lw=1.6)
for i, t in enumerate(ACTIVE):
    ax.annotate(f"{al.loc[t, 'Alpha per year']:+.1f}%", (al.loc[t, "Alpha per year"], i),
                textcoords="offset points", xytext=(0, 9), ha="center", fontsize=9)
ax.axvline(0, color="black", lw=1, ls="--")
ax.set_yticks(list(y), ACTIVE, fontsize=10)
ax.set_ylim(-0.6, len(ACTIVE) - 0.4)
ax.invert_yaxis()
ax.set_xlabel("Alpha per year after fees (%), with 95% confidence interval")
ax.set_title(f"Skill or luck? Every 95% interval crosses zero\n({period}, after fees)", fontsize=11)
ax.grid(axis="x", alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "chart.png", dpi=150)
print("Saved output/chart.png")
