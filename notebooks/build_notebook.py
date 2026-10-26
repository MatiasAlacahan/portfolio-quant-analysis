"""Generate notebooks/analysis.ipynb (run from the project root, then execute it with
`jupyter nbconvert --to notebook --execute --inplace notebooks/analysis.ipynb`)."""
from pathlib import Path

import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

cells = [
    md("# Quantitative analysis of two portfolios (USD)\n"
       "*Análisis cuantitativo de dos portafolios de un inversor argentino.*\n\n"
       "This notebook walks through the pipeline step by step. The full interactive report is "
       "`reports/portfolio_report.html` (run `python main.py`).\n\n"
       "1. Data & proxies · 2. Bond total return · 3. Metrics · 4. Backtest · "
       "5. Robustness · 6. Stress scenarios · 7. Outlook from today's prices"),
    code("import sys, warnings\n"
         "from pathlib import Path\n"
         "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
         "sys.path.insert(0, str(ROOT))\n"
         "warnings.filterwarnings('ignore')\n"
         "import pandas as pd\n"
         "from IPython.display import Image, display\n"
         "pd.set_option('display.float_format', '{:,.4f}'.format)\n"
         "import main\n"
         "from src import config, cashflows"),
    md("## 1. Data and proxies\n"
       "US-listed assets come from yfinance. Argentine bonds from data912, the CCL rate and the FCI "
       "from ArgentinaDatos, CER/TAMAR from the BCRA API. Assets without public history use a "
       "documented proxy (see `data/README.md`)."),
    code("built = main.stage_data(refresh=False)\nbuilt['coverage'][['asset','source_type','first_real_date','real_data_share','note']]"),
    md("## 2. Bond total return\n"
       "Argentine bond prices drop on the ex-date by the coupon + amortization. "
       "The table checks that the price drop matches the scheduled cash flow."),
    code("built['bond_checks']['AL30D']"),
    code("e = built['extras']\n"
         "def cagr(s): s = s.dropna(); return (s.iloc[-1]/s.iloc[0])**(365.25/(s.index[-1]-s.index[0]).days)-1\n"
         "pd.DataFrame({'price only': [cagr(e['AL30D_PRICE']), cagr(e['AL35D_PRICE'])],\n"
         "              'total return': [cagr(e['AL30D_TR']), cagr(e['AL35D_TR'])]}, index=['AL30D','AL35D'])"),
    md("## 3. Portfolio metrics and 4. Backtest"),
    code("analysis = main.stage_analysis(built)"),
    code("display(Image(str(config.REPORTS / 'figures' / 'growth.png')))\n"
         "display(Image(str(config.REPORTS / 'figures' / 'backtest.png')))"),
    md("## 5. Robustness (from Oct-2024) and 7. Outlook"),
    code("extra = main.stage_robustness(built, analysis, refresh=False)"),
    md("## 6. Stress scenarios"),
    code("stress = main.stage_scenarios(analysis)"),
    md("## Key takeaways\n"
       "- Over 5 years the strategy beat SPY, but with more drawdown in Argentine stress episodes.\n"
       "- From Oct-2024 the advantage almost disappears.\n"
       "- The historical numbers carry hindsight bias (asset selection, country-risk compression from "
       "~1,700 bps). From today's prices the expected return of the 60/40 is close to SPY's.\n\n"
       "See the HTML report for the full discussion."),
]

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
out = Path(__file__).parent / "analysis.ipynb"
nbf.write(nb, out)
print(f"wrote {out}")
