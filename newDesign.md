PROJECT: SignalForge — Evidence-First Stock Research Dashboard

OBJECTIVE
Implement the redesigned SignalForge stock research dashboard using the
provided screenshots as the visual and functional reference.

This is an implementation task, not a design-only task.

Inspect the existing repository first. Understand the current framework,
components, routes, data models, APIs, database schema, authentication,
and stock-analysis calculations before modifying anything.

Preserve working functionality and existing integrations wherever possible.
Extend the current architecture instead of replacing it unnecessarily.

==================================================
1. DESIGN SYSTEM AND GLOBAL LAYOUT
==================================================

Use the supplied screenshots as the primary design reference.

Design characteristics:
- Dark financial research dashboard.
- Near-black page background.
- Dark navy/charcoal cards and panels.
- Subtle borders and separators.
- Green for positive signals.
- Red for negative signals and risks.
- Amber/orange for warnings and emphasis.
- Blue for primary actions and selected navigation.
- Purple for selected analytical indicators.
- Compact, information-dense financial layouts.
- Clear typography and consistent spacing.
- Responsive layouts for desktop, tablet, and mobile.

IMPORTANT:
Remove all manually added red outlines, red borders, and red highlight
rectangles from the screenshots' KPI section.

The red rectangle is an annotation in the reference image, not part of
the application design.

Use the same subtle card borders, spacing, corner radius, and background
treatment as the surrounding dashboard.

Do not add permanent colored borders around the KPI grid.

Use the existing design system if one already exists. Otherwise,
centralize colors, spacing, typography, radii, and component styles
in reusable theme variables.

==================================================
2. GLOBAL HEADER AND NAVIGATION
==================================================

Implement or preserve the global header containing:

- SignalForge brand.
- Tagline: "Evidence-first research, not predictions."
- Stock search supporting symbols and company names.
- Market status.
- NIFTY and SENSEX market indicators.
- Watchlist access.
- User profile controls.
- Dark/light theme control if supported by the existing application.

Implement or preserve the primary application navigation:

- Home
- Stock Screener
- Watchlist
- Sectors
- Market Insights
- Portfolio
- AI Research
- Settings
- Help

Keep the navigation consistent across all applicable pages.

Do not duplicate navigation implementations across tabs.

==================================================
3. STOCK IDENTITY HEADER
==================================================

At the top of a stock detail page, display:

- Company logo, when available.
- Company name.
- Stock symbol.
- Exchange.
- Sector or industry.
- Current stock price.
- Absolute price change.
- Percentage price change.
- Market timestamp.
- Market regime.
- Watchlist action.
- Share action.
- Additional stock actions, if already supported.

All stock-specific information must update when a different stock is selected.

Do not hardcode South Indian Bank as the only supported company.

==================================================
4. OVERVIEW TAB — KPI GRID
==================================================

This is the highest-priority implementation requirement.

Place the KPI grid directly below the stock identity header and above
the tab navigation and technical charts.

Use a responsive four-column grid on wide desktop screens.

On smaller screens, reduce the number of columns without horizontal
overflow.

The grid must contain eight independent cards in this order:

ROW 1

CARD 1: STAGE 2 / MOMENTUM

Display:
- Stage 2 status.
- Momentum status.
- PASS, FAIL, or UNAVAILABLE.
- Number of criteria met, when available.
- Details action.

Use the existing Stage 2 and momentum calculation logic.

Do not fabricate a passing result when the necessary data is missing.

CARD 2: ANALYST RATING & TARGET

Display:
- Consensus analyst rating, when available.
- Consensus target price.
- Upside or downside relative to the current price.
- Number of analysts contributing to the consensus.
- Details action.

Possible states:
- BUY
- HOLD
- SELL
- NO COVERAGE
- UNAVAILABLE

Calculate upside/downside using:

((Target Price - Current Price) / Current Price) * 100

Use the existing analyst data provider and distinguish missing analyst
coverage from a genuine HOLD rating.

CARD 3: VCP — VOLATILITY CONTRACTION PATTERN

Display:
- YES, NO, or UNAVAILABLE.
- Pattern identification status.
- Relevant evidence or criteria.
- Details action.

Use the existing VCP implementation if available.

If it does not exist, inspect the project's technical-analysis
architecture and implement a documented, testable VCP detector using
available historical OHLCV data.

Do not label VCP as YES solely because a stock is rising.

If sufficient historical data is unavailable, display UNAVAILABLE.

CARD 4: DISTANCE FROM 52-WEEK HIGH

Display:
- Distance from the 52-week high as a percentage.
- Current price.
- 52-week high.
- 52-week low.
- A visual price-range indicator.
- Details action.

Calculate:

Distance from 52-week high (%) =
((Current Price - 52-Week High) / 52-Week High) * 100

Display 0.0% when the current price equals the 52-week high.

Do not treat missing 52-week data as zero.

ROW 2

CARD 5: EARNINGS & GROWTH

Display the following rows:

- Revenue growth YoY.
- Revenue all-time-high status.
- PAT growth YoY.
- PAT all-time-high status.
- Net profit margin.
- EPS growth YoY.
- EPS all-time-high status.
- Details action.

Use the latest available reported financial periods.

All-time-high flags must be derived from the available historical dataset.
Indicate the historical coverage used for the comparison.

If the dataset is incomplete, label the flag as unavailable or
qualify the comparison period.

Do not claim an all-time high when only a small or incomplete historical
sample exists.

ROW 2, CONTINUED

CARD 6: QUALITY METRICS

Display:

- ROCE.
- ROE.
- Free cash flow.
- Debt-to-equity ratio.
- Details action.

Use the latest available reporting period and clearly identify the
reporting date or fiscal period.

Handle banks and financial institutions appropriately.

For banking companies, conventional industrial-company metrics such as
debt-to-equity may not be directly comparable. Display the metric only
when meaningful and label it accordingly.

Do not silently substitute unrelated ratios.

CARD 7: FII / DII HOLDING

Display:

- FII ownership percentage.
- FII change from the previous reporting period.
- DII ownership percentage.
- DII change from the previous reporting period.
- Public ownership percentage.
- Public ownership change.
- Reporting quarter.
- Details action.

Use reported shareholding data.

Display changes as percentage-point changes or relative percentage
changes consistently and label the chosen calculation.

The ownership categories must not be combined incorrectly.

Do not assume unavailable promoter ownership is zero.

CARD 8: VALUATION

Display:

- PEG ratio.
- Trailing P/E.
- Industry P/E.
- Details action.

Show the reporting or calculation date.

Distinguish:
- A real zero value.
- An unavailable value.
- A negative or nonmeaningful ratio.
- A ratio that cannot be calculated.

Do not replace missing ratios with zero.

Use the existing valuation data source and calculation logic.

==================================================
5. DATA AVAILABILITY AND MISSING VALUES
==================================================

Every KPI card and individual metric must support explicit data states.

Required states:

1. AVAILABLE
   Show the metric and its value.

2. UNAVAILABLE
   The required data is missing or cannot be calculated.

3. NO COVERAGE
   The relevant source explicitly confirms that coverage does not exist.

4. STALE
   Data exists but is older than the configured freshness threshold.

5. ERROR
   The data request failed.

Do not treat these states as interchangeable.

For binary indicators such as VCP and Stage 2:

- YES / PASS: the criteria are satisfied using valid data.
- NO / FAIL: valid data exists and the criteria are not satisfied.
- UNAVAILABLE: the calculation cannot be completed.
- STALE: the underlying data is too old to support a current conclusion.

For analyst coverage:

- Display NO COVERAGE only when the provider confirms no coverage.
- Display UNAVAILABLE when the request fails or coverage status cannot
  be established.

For numerical metrics:

- Display the value and its units when available.
- Display N/A or UNAVAILABLE when unavailable.
- Show the reason where practical.

Never silently convert null values into zero.

Never fabricate historical prices, financial statements, analyst targets,
ownership data, or technical indicators.

==================================================
6. OVERVIEW TAB — TECHNICAL ANALYSIS
==================================================

Below the KPI grid, preserve and improve the existing overview content.

Include:

A. Price and volume chart
- Candlesticks.
- Volume bars.
- EMA 20.
- SMA 50.
- SMA 200.
- Selectable time ranges.
- Current-price marker.
- Crosshair and tooltips where supported.

B. RSI
- RSI 14.
- Clearly marked overbought and oversold reference levels.
- Current RSI value.

C. MACD
- MACD line.
- Signal line.
- Histogram.
- Current values.

D. Signal Summary
- Momentum interpretation.
- Overbought/oversold state.
- 52-week range context.
- Important technical observations.

E. Key Levels
- Relevant support and resistance levels.
- 52-week high and low.
- Relevant moving averages.

F. Research Drivers
- Positive drivers.
- Negative drivers.
- Risks.
- Supporting evidence.

G. Research Snapshot
- Technical score.
- Momentum score.
- Fundamental score.
- Valuation score.
- Market regime score.
- Risk-quality score.
- Overall research score.

Use the existing scoring engine and data sources.

Do not create a second, conflicting scoring system merely to populate
the new interface.

==================================================
7. REMAINING STOCK DETAIL TABS
==================================================

Implement the following tabs as complete, functional views.

TAB A: TECHNICALS

Include:
- Expanded price chart.
- Multiple technical indicators.
- Moving averages.
- RSI.
- MACD.
- ADX.
- ATR.
- Bollinger Bands.
- Relative volume.
- Breakout and breakdown observations.
- Multi-timeframe trend alignment.
- Stage 2 analysis.
- VCP analysis when supported.
- Support and resistance.
- Technical evidence and signal explanations.

Every signal must be traceable to the underlying data and rule.

TAB B: FINANCIALS & P&L

Include:
- Long-term revenue trend.
- Profit and loss trends.
- Revenue growth.
- EBITDA, where meaningful and available.
- PAT.
- EPS.
- Operating margins.
- Net profit margins.
- Free cash flow.
- Total debt.
- ROE.
- ROA.
- ROCE.
- Quarterly trends.
- Annual trends.
- Financial ratios.
- Historical comparison tables.
- Financial data source and reporting periods.

Clearly distinguish reported values from derived metrics.

Do not display meaningless industrial-company ratios for banks without
an explicit explanation.

TAB C: SHAREHOLDING

Include:
- Promoter ownership.
- FII ownership.
- DII ownership.
- Public ownership.
- Quarterly ownership history.
- Quarter-over-quarter changes.
- Ownership distribution chart.
- Shareholder count, when available.
- Institutional accumulation or distribution observations.
- Reporting period and data source.

Provide both a readable table and a chart view.

Ensure the layout supports horizontal scrolling for large tables without
breaking the page.

TAB D: HEALTH & DIAGNOSTICS

Include:
- Piotroski F-score.
- Altman Z-score when appropriate for the company type.
- Earnings quality.
- Operating cash flow.
- Free cash flow.
- Cash conversion metrics when meaningful.
- ROE decomposition.
- Leverage indicators.
- Financial-statement consistency checks.
- Forensic warnings and accounting-risk observations.

Show the underlying criteria and evidence for each score.

Distinguish:
- A failed criterion.
- A criterion that cannot be evaluated.
- A criterion that is not applicable.

Do not treat missing information as a failed criterion.

Use suitable methodologies for banks and other financial institutions.

TAB E: MULTIBAGGER CHECKLIST

Use a six-pillar checklist:

1. Opportunity.
2. Large Aspiration.
3. Earnings.
4. Quality.
5. Value Analysis.
6. Shareholding Pattern.

For every pillar, show:
- MET, NOT MET, or UNAVAILABLE.
- Supporting quantitative evidence.
- Source.
- Relevant reporting period.
- Explanation.

Show the total number of criteria satisfied.

Calculate the overall completion percentage using only the defined
evaluation rules.

Do not count unavailable criteria as satisfied.

Do not confuse checklist completion with the probability of a stock
becoming a multibagger.

TAB F: AI ANALYST

Include:
- Stock-specific question and answer interface.
- Suggested research questions.
- Financial ratio comparisons.
- Fundamental and technical analysis questions.
- Valuation comparisons.
- Stage 2 and VCP explanations.
- Financial-health questions.
- Cross-stock comparisons when supported.
- Source-backed responses.
- Relevant reporting periods.
- Database snapshot or source-inspection functionality if already
  implemented.

The AI must use the actual connected data and existing backend tools.

It must not invent company financials or present unsupported statements
as facts.

Show when data is unavailable or stale.

Preserve existing AI provider and database integrations.

TAB G: QUALITY CHECKLIST / FULL REPORT

If the existing application already has a quality checklist or full
report, preserve it and make it consistent with the redesigned interface.

If these views are not implemented, add them only where the existing
architecture and project scope support them.

The full report should consolidate:
- Company overview.
- Research score.
- KPI summary.
- Technical analysis.
- Financials.
- Shareholding.
- Financial health.
- Valuation.
- Risks.
- Bull and bear cases.
- Data sources and timestamps.

==================================================
8. VISUAL CONSISTENCY ACROSS TABS
==================================================

Every tab must share:

- The same stock identity header.
- The same research summary cards.
- Consistent tab navigation.
- The same design tokens.
- Consistent loading, empty, error, and stale-data states.
- Consistent date formatting.
- Consistent financial units.
- Consistent tooltips and evidence displays.

The selected tab must be clearly visible.

Switching tabs must not unnecessarily reload unrelated data.

Keep tab-specific content inside the relevant panel.

Do not display all tab contents simultaneously.

Preserve browser navigation and deep-linking behavior if already supported.

==================================================
9. COMPONENT ARCHITECTURE
==================================================

Create reusable components where appropriate.

Suggested components:

- StockHeader
- ResearchSummaryCards
- StockKPIGrid
- KPIStatusCard
- MetricRow
- DataAvailabilityBadge
- DataFreshnessLabel
- EvidenceTooltip
- PriceRangeIndicator
- PriceVolumeChart
- RSIChart
- MACDChart
- SignalSummary
- KeyLevelsPanel
- ResearchDriversPanel
- ResearchSnapshot
- FinancialMetricsTable
- OwnershipTrendTable
- OwnershipDistributionChart
- FinancialHealthCard
- MultibaggerCriterionCard
- AIAnalystPanel
- DataSourceLabel
- LoadingState
- EmptyState
- ErrorState

Use the repository's existing naming conventions and component patterns
rather than creating unnecessary duplicate components.

Keep calculations and business rules outside presentation components.

Use shared selectors, hooks, services, or equivalent architecture
appropriate to the existing framework.

==================================================
10. DATA AND BACKEND INTEGRATION
==================================================

Before implementing, map each visible metric to its actual data source.

For every metric, document:
- Source.
- API endpoint or database table.
- Field name.
- Calculation formula.
- Reporting period.
- Data freshness.
- Missing-data behavior.

Reuse existing API integrations and database queries.

Do not add mock data to production code.

Do not replace existing data with hardcoded screenshot values.

If a required metric has no current source:
1. Identify the missing source.
2. Determine whether it can be derived from existing data.
3. Implement the calculation only if the underlying data is sufficient.
4. Otherwise display UNAVAILABLE.
5. Document the remaining integration requirement.

Avoid N+1 requests when retrieving KPI data.

Use caching and appropriate loading boundaries if supported by the
existing architecture.

Ensure that changing the selected stock updates every stock-dependent
component consistently.

==================================================
11. TESTING AND VALIDATION
==================================================

Add or update tests for:

- KPI calculations.
- Missing values.
- Stale data.
- API failures.
- Analyst coverage states.
- Stage 2 evaluation.
- VCP evaluation.
- 52-week high calculations.
- Financial growth calculations.
- ATH comparisons.
- Ownership changes.
- Valuation metrics.
- Tab navigation.
- Stock switching.
- Responsive layouts.

Verify:
- No red annotation borders remain.
- No KPI values are hardcoded from the screenshot.
- All tabs load correctly.
- Missing data is not represented as zero.
- The interface does not break when one API fails.
- No horizontal overflow occurs at common viewport sizes.
- Existing working functionality remains intact.

Run the project's existing lint, type-check, build, and test commands.

Fix regressions introduced by the implementation.

==================================================
12. IMPLEMENTATION WORKFLOW
==================================================

PHASE 1 — REPOSITORY AUDIT

Inspect:
- Project structure.
- Framework and dependencies.
- Routes and navigation.
- Existing dashboard components.
- Data providers.
- Database schema.
- Technical indicators.
- Financial calculations.
- Tests.
- Existing styling conventions.

Produce a concise implementation plan and identify any missing data
sources before changing the architecture.

PHASE 2 — OVERVIEW REDESIGN

Implement the stock header and eight-card KPI grid.

Remove the red annotation borders.

Preserve the existing charts and research summary.

Verify all eight KPI cards use live application data.

PHASE 3 — REMAINING TABS

Implement or refine:
- Technicals.
- Financials & P&L.
- Shareholding.
- Health & Diagnostics.
- Multibagger Checklist.
- AI Analyst.
- Quality Checklist and Full Report, where applicable.

PHASE 4 — DATA QUALITY

Implement explicit missing, stale, unavailable, and error states.

Validate calculation logic and reporting periods.

PHASE 5 — TESTING

Run tests, type checks, linting, and production build.

Verify all stock detail tabs and responsive states.

PHASE 6 — DELIVERY

Summarize:
- Files changed.
- Components created or modified.
- Data sources reused.
- New calculations implemented.
- Tabs completed.
- Tests and build results.
- Missing data sources.
- Remaining limitations.

Do not claim an item is complete if it is only a visual placeholder.

==================================================
FINAL ACCEPTANCE CRITERIA
==================================================

The implementation is complete when:

1. The dashboard matches the supplied visual references.
2. The red annotation borders are removed.
3. The eight KPI cards appear at the top of Overview.
4. Every metric reflects the selected stock's actual data.
5. Available, unavailable, stale, and error states are distinguishable.
6. The technical charts remain functional.
7. All existing stock detail tabs work.
8. The remaining tabs are implemented consistently with their references.
9. Missing metrics are not fabricated.
10. Existing integrations and calculations are preserved.
11. Responsive layouts work without major overflow.
12. The project builds and its relevant tests pass.

Begin by auditing the repository. Then implement the changes in phases.


| Screenshot | Purpose |
|---|---|
| Overview with eight KPI cards | Primary layout and KPI requirements |
| Shareholding | Ownership cards, quarterly table, and ownership trends |
| Health & Diagnostics | Financial health, earnings quality, and ROE decomposition |
| Financials & P&L | Historical financial trends and financial metrics |
| Multibagger Checklist | Six-pillar evaluation framework |
| AI Analyst | AI interface, suggested queries, and source connectivity |
| Original SignalForge overview | Existing functionality and technical charts |


IMPORTANT EXECUTION RULES

1. Modify the existing repository directly.
2. Do not create a separate demo application.
3. Do not replace real data with sample or hardcoded values.
4. Do not delete existing functionality merely to simplify the redesign.
5. Reuse existing APIs, database connections, calculations, and charting
   libraries wherever appropriate.
6. Do not expose secrets or credentials.
7. Do not stop after creating a plan or static UI mockup.
8. Implement, test, and validate the actual changes.
9. Do not report tests as passing unless they were executed successfully.
10. If a data provider or API is missing, identify the exact dependency
    instead of inventing the result.
11. Keep changes scoped to the requested dashboard and its dependencies.
12. Report any unavoidable breaking changes before introducing them.

Start by inspecting the current implementation and identifying the
existing files responsible for the stock header, overview, KPI cards,
charts, and tab navigation.

If there is any new KPI or data found try to calculate it from screene.in raw HTML snapshots and show it on dashboard
