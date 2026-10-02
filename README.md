# Endowment Manager Evaluation: Skill or Luck?

**Question:** Do actively managed US equity funds beat the market after fees, and how should an endowment's record be judged against a simple 60/40 portfolio?

**Key result:** After fees, **0 of 3** active funds showed statistically significant alpha (Fama-French 3-factor regression, Jan 2015 – Aug 2026). Cornell's endowment averaged 8.7%/yr vs. 8.5% for a 60/40 over FY2015–FY2025, a gap far below the ~4.8 pts/yr needed to tell skill from luck in 11 years.

| Fund | Return/yr | Fee | Alpha/yr | 95% CI | Verdict |
|---|---|---|---|---|---|
| FCNTX Fidelity Contrafund | 15.9% | 0.74% | +1.7% | −0.8% to +4.2% | can't tell |
| AGTHX Growth Fund of America | 14.2% | 0.59% | +0.3% | −1.8% to +2.3% | can't tell |
| TRBCX T. Rowe Blue Chip Growth | 14.4% | 0.70% | −0.3% | −3.1% to +2.5% | can't tell |
| VFIAX Vanguard 500 Index | 13.9% | 0.04% | – | – | benchmark |

**Read more:** [1-page memo](memo.md) ([PDF](memo.pdf)) · [Excel summary](output/summary.xlsx) · [code](analysis.py)

**Run it:** `pip install pandas matplotlib statsmodels yfinance openpyxl requests`, then `python analysis.py` (downloads the data and rebuilds everything in `output/`).
