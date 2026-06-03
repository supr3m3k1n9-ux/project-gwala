const stateUrl = "/api/system-state";
const tradingWorkspaceUrl = "/api/trading-workspace";
const setupReadinessUrl = "/api/setup-readiness";
const replayChartUrl = "/api/replay-chart";
const nearMissAnalyticsUrl = "/api/near-miss-analytics";
const investmentNarrativeUrl = "/api/investment-narrative";
const backtestTradesUrl = "/api/backtest-trades";
const backtestPortfolioUrl = "/api/backtest-portfolio";
const openPaperTradesUrl = "/api/open-paper-trades";
const refreshStatusActionUrl = "/api/actions/refresh-status";
const refreshWebullDataActionUrl = "/api/actions/refresh-webull-data";
const premarketCheckActionUrl = "/api/actions/premarket-check";
const paperSessionPreviewActionUrl = "/api/actions/paper-session-preview";
const paperSessionConfirmEntryActionUrl = "/api/actions/paper-session-confirm-entry";
const paperSessionConfirmExitsActionUrl = "/api/actions/paper-session-confirm-exits";
const updatePaperTradeActionUrl = "/api/actions/update-paper-trade";
const replayJournalStorageKey = "project_gwala_replay_practice_v1";
const autoRefreshMs = 60_000;
const reports = [
  ["dashboard", "Dashboard"],
  ["scanner", "Scanner"],
  ["observations", "Observations"],
  ["near_misses", "Near Misses"],
  ["observation_review", "Observation Review"],
  ["reconciliation", "Reconciliation"],
  ["integrity", "Data Integrity"],
  ["refresh_audit", "Refresh Audit"],
  ["setup_health", "Setup Health"],
  ["paper_session", "Paper Session"],
  ["paper_execution", "Paper Execution"],
  ["candidate_alerts", "Candidate Alerts"],
  ["forward_sample_queue", "Forward Sample Queue"],
  ["almost_ready_breakout", "Almost-Ready Breakout"],
  ["post_scan_digest", "Post-Scan Digest"],
  ["forward_evidence", "Forward Evidence"],
  ["candidate_aging", "Candidate Aging"],
  ["no_trade_analysis", "No-Trade Analysis"],
  ["shadow_samples", "Shadow Samples"],
  ["open_paper_monitor", "Open Paper Monitor"],
  ["exit_audit", "Exit Audit"],
  ["readiness", "Readiness"],
  ["checkpoint", "Checkpoint"],
  ["refresh_status", "Refresh Status"],
  ["morning_watchdog", "Morning Watchdog"],
  ["automation_timeline", "Automation Timeline"],
  ["premarket", "Pre-Market Verification"],
  ["setup_replay", "Setup Replay"],
  ["strategy_vault", "Strategy Vault"],
  ["vwap_mean_reversion", "VWAP Mean Reversion"],
  ["vwap_mean_reversion_walk_forward", "VWAP Mean Reversion Walk-Forward"],
  ["vwap_mean_reversion_shadow_samples", "VWAP Mean Reversion Shadow Samples"],
  ["vwap_mean_reversion_forward_observations", "VWAP Mean Reversion Forward Observations"],
  ["vwap_mean_reversion_paper_watch_gate", "VWAP Mean Reversion Paper-Watch Gate"],
  ["opening_range_failure", "Opening Range Failure"],
  ["strategy_evidence_accumulator", "Strategy Evidence Accumulator"],
  ["strategy_improvement_plan", "Strategy Improvement Plan"],
  ["feature_wiring_audit", "Feature Wiring Audit"],
  ["research_confidence", "Research Confidence"],
  ["promotion_review", "Promotion Review"],
  ["controlled_variant_review", "Controlled Variants"],
  ["walk_forward_review", "Walk Forward"],
  ["regime_review", "Regime Review"],
  ["strategy_overlap_audit", "Strategy Audit"],
  ["opening_range_relaxation", "Opening Range Test"],
  ["deep_research_confidence", "Deep Research"],
  ["deep_promotion_review", "Deep Promotion"],
  ["deep_controlled_variant_review", "Deep Controlled"],
  ["deep_walk_forward_review", "Deep Walk Forward"],
  ["deep_regime_review", "Deep Regime"],
  ["system_state", "System State"],
];
const reportGroups = [
  {
    label: "Daily Workflow",
    reports: [
      "dashboard",
      "scanner",
      "observations",
      "near_misses",
      "observation_review",
      "reconciliation",
      "integrity",
      "refresh_audit",
      "refresh_status",
      "morning_watchdog",
      "automation_timeline",
      "premarket",
      "setup_health",
    ],
  },
  {
    label: "Paper Review",
    reports: ["paper_session", "paper_execution", "candidate_alerts", "forward_sample_queue", "almost_ready_breakout", "post_scan_digest", "forward_evidence", "candidate_aging", "no_trade_analysis", "shadow_samples", "open_paper_monitor", "exit_audit", "readiness", "checkpoint", "setup_replay"],
  },
  {
    label: "Research",
    reports: ["strategy_vault", "strategy_evidence_accumulator", "vwap_mean_reversion", "vwap_mean_reversion_walk_forward", "vwap_mean_reversion_shadow_samples", "vwap_mean_reversion_forward_observations", "vwap_mean_reversion_paper_watch_gate", "opening_range_failure", "strategy_improvement_plan", "feature_wiring_audit", "research_confidence", "promotion_review", "controlled_variant_review", "walk_forward_review", "regime_review", "strategy_overlap_audit", "opening_range_relaxation"],
  },
  {
    label: "Deep Research",
    reports: [
      "deep_research_confidence",
      "deep_promotion_review",
      "deep_controlled_variant_review",
      "deep_walk_forward_review",
      "deep_regime_review",
    ],
  },
  {
    label: "System",
    reports: ["system_state"],
  },
];
const glossary = {
  "scanner-freshness": "Whether the scanner output comes from today's latest saved candles. Stale scanner data should not be used for current paper review.",
  "data-pipe": "The path that brings Webull candle data into local CSV files and reports.",
  "market-clock": "Checks whether the regular stock-market session is open, closed, or waiting for the next session.",
  "paper-gate": "A local safety gate that blocks paper logging until a fresh candidate has been reviewed. It never sends broker orders.",
  "candidate-review": "A setup that appeared on the latest relevant candle and is available for manual review.",
  "sample-queue": "Read-only queue for collecting forward paper samples cleanly. It ranks ready, blocked, and almost-ready scanner rows.",
  "refresh-status": "A small JSON/report that says whether the latest scanner and candle files are fresh enough for review.",
  "refresh-audit": "A log proving when each symbol's Webull candles were last refreshed and whether they match the current session.",
  "pre-market-gate": "Checks that should pass before trusting market-hours scanner output.",
  "pre-market-probe": "A data-access check before the session. It confirms the app can reach the expected data source.",
  "current-candidates": "Setups found on the latest relevant candle, available for manual review only.",
  "eligible-position-sizes": "Candidates that have enough entry/stop information to calculate a paper share size.",
  "forward-observations": "Signals saved when they appeared in real time so their later outcomes can be studied.",
  "watch-only-observations": "Blocked or non-actionable observations saved for learning what the filters excluded.",
  "scanner-csv": "The saved spreadsheet-like scanner output used by the dashboard.",
  "position-sizing-csv": "The saved file with calculated paper share sizes and risk status.",
  "setup-health-csv": "The saved setup-health file that flags strategy variants needing attention.",
  "paper-log": "The local record of reviewed paper trades. It is not a brokerage statement.",
  backtests: "Latest historical watchlist tests. These show research stats only, not live-trading approval.",
  checks: "How many setup checklist rules are passing right now versus how many are required.",
  quality: "A simple grade/score for setup strength based on the strategy's filters.",
  "rel-vol": "Relative volume. A value above 1.0 means volume is higher than its comparison baseline.",
  "room-r": "Room to target measured in R. 1R equals the planned risk from entry to stop.",
  entry: "The planned price where the setup would be entered.",
  stop: "The invalidation price. If hit, the planned loss is usually -1R.",
  target: "The planned profit area used to compare reward against risk.",
  shares: "Suggested paper share size based on account risk settings and stop distance.",
  "risk-share": "Dollars at risk per share: entry price minus stop price for longs, or stop minus entry for shorts.",
  "est-risk": "Estimated paper dollars at risk if the suggested share size is used.",
  "exp-r": "Expectancy in R. Average outcome per trade measured in units of planned risk.",
  pf: "Profit factor. Gross wins divided by gross losses; higher than 1 means wins outweighed losses in that sample.",
  trades: "Number of completed historical or paper samples behind that statistic.",
  "scale-tier": "Manual risk guidance for paper review. It never places trades or changes size automatically.",
  "evidence-priority": "Ranks a candidate for manual paper review using historical promotion, setup-health, and candidate-aging evidence.",
  "risk-guard": "Forward-paper risk brake. It caps scale-up until enough completed paper trades prove the setup behavior.",
  "premium-cap": "Maximum option premium to tie up in one idea, measured as a percent of account value.",
  "timeframe-signal": "A timeframe used by the actual strategy rules. Here, 30m is for entries and 5m is for exits.",
  "timeframe-review": "A chart-only timeframe for context. It does not change scanner eligibility.",
};

const $ = (id) => document.getElementById(id);
let allReplayCards = [];
let replayCards = [];
let replayIndex = 0;
let replayOutcomeRevealed = false;
let replayChartRequestId = 0;
let replayJournal = {};
let replayManagementStep = null;
let replayLatestChart = null;
let replayPracticeFinished = false;
let replayFilterState = {
  symbol: "",
  setup: "",
  grade: "",
  result: "",
  exit_reason: "",
  reviewed_only: false,
  unreviewed_only: false,
};
let currentState = null;
let terminalSymbol = "SPY";
let terminalTimeframe = "M5";
let terminalInitialized = false;
let terminalRequestId = 0;
let narrativeRequestId = 0;
let stateRefreshInFlight = false;
let latestBacktestRows = [];
let selectedBacktestIndex = null;
let openPaperRows = [];
let latestPaperProgress = null;
let latestPortfolioRows = [];
let latestPortfolioAccount = {};
let latestPortfolioTotalRows = 0;
let alertsEnabled = false;
let alertStateInitialized = false;
let lastReadyCandidateKeys = new Set();
let lastOpenPaperKeys = new Set();
let terminalFocus = null;
const preEntryReviewedKeys = new Set();
let activePreEntryKey = "";

function text(value, fallback = "None") {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function titleCase(value) {
  return text(value).replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = text(value);
}

function safeRender(name, callback) {
  try {
    callback();
  } catch (error) {
    console.error(`${name} render failed`, error);
    updateAutoRefreshStatus(`${name} panel failed: ${error.message}`);
  }
}

function safeClassName(value) {
  return text(value, "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
}

function setStatusPill(element, status) {
  element.className = "status " + safeClassName(status);
  element.textContent = titleCase(status);
}

function updateAutoRefreshStatus(message) {
  const target = $("auto-refresh-status");
  if (target) target.textContent = message;
}

function helpBubble(key) {
  const detail = glossary[key];
  return detail ? ` <span class="help-bubble" data-help="${escapeHtml(detail)}">?</span>` : "";
}

function helpKey(value) {
  return text(value, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function hydrateHelpBubbles(root = document) {
  for (const bubble of root.querySelectorAll(".help-bubble")) {
    bubble.setAttribute("tabindex", "0");
    bubble.setAttribute("role", "note");
    bubble.setAttribute("aria-label", bubble.dataset.help || "Help");
  }
}

function appStatusLevel(status) {
  if (["pass", "passed", "previous_pass", "fresh_for_today", "ready_to_refresh", "ready"].includes(status)) {
    return "healthy";
  }
  if (["fail", "failed", "blocked_missing_csv", "missing", "blocked"].includes(status)) {
    return "caution";
  }
  return "watch";
}

function minutesLabel(value) {
  if (value === undefined || value === null || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number.toFixed(number >= 10 ? 0 : 1)} min`;
}

function candleFreshnessState(state) {
  const summary = state.refresh_status?.candle_freshness || {};
  const status = summary.status || "unknown";
  const maxM5 = summary.max_m5_age_minutes;
  const maxM30 = summary.max_m30_age_minutes;
  const staleSymbols = [
    ...(summary.stale_m5_symbols || []),
    ...(summary.stale_m30_symbols || []),
  ];
  const uniqueStale = [...new Set(staleSymbols)];
  const unknownSymbols = summary.unknown_symbols || [];
  let tone = "watch";
  let label = "Unknown";
  let detail = `5m: ${minutesLabel(maxM5)} / 30m: ${minutesLabel(maxM30)}.`;

  if (status === "fresh") {
    tone = "healthy";
    label = "Fresh";
    detail = `5m max age ${minutesLabel(maxM5)}; 30m max age ${minutesLabel(maxM30)}.`;
  } else if (status === "stale") {
    tone = "caution";
    label = "Stale";
    detail = `Refresh before review. Stale symbols: ${uniqueStale.join(", ") || "unknown"}.`;
  } else if (status === "outside_market_hours") {
    tone = "watch";
    label = "Closed";
    detail = `Market closed. Last saved 5m age ${minutesLabel(maxM5)}; 30m age ${minutesLabel(maxM30)}.`;
  } else if (unknownSymbols.length) {
    tone = "caution";
    label = "Check";
    detail = `Missing or unreadable candle timestamps for ${unknownSymbols.join(", ")}.`;
  }

  return {
    status,
    tone,
    label,
    detail,
    isStale: status === "stale" || status === "unknown",
  };
}

function chartFreshnessState(chart, state) {
  const marketOpen = Boolean(state?.refresh_status?.market?.market_is_open || state?.market?.market_is_open);
  const thresholds = { M1: 5, M5: 10, M15: 25, M30: 40, M60: 75 };
  const threshold = thresholds[chart.timeframe];
  const lag = Number(chart.data_lag_minutes);

  if (!threshold || !Number.isFinite(lag)) {
    return {
      tone: "watch",
      message: "Daily or unavailable chart freshness is for context only. Use 5m/30m for paper timing checks.",
    };
  }
  if (!marketOpen) {
    return {
      tone: "watch",
      message: `Market is not open. Latest ${chart.timeframe} candle is ${minutesLabel(lag)} old.`,
    };
  }
  if (lag > threshold) {
    return {
      tone: "caution",
      message: `Stale ${chart.timeframe} candles: ${minutesLabel(lag)} old. Refresh Webull data before paper review.`,
    };
  }
  return {
    tone: "healthy",
    message: `${chart.timeframe} candles are fresh enough for review: ${minutesLabel(lag)} old, limit ${threshold} min.`,
  };
}

function readinessSummary(state) {
  const refresh = state.refresh_status || {};
  const premarket = state.premarket_verification || {};
  const market = refresh.market || state.market || {};
  const scanner = refresh.scanner || state.scanner || {};
  const freshness = state.data_freshness || {};
  const candidateCount = Number(state.current_candidates?.count || state.scanner?.current_candidate_count || 0);
  const eligibleSizeCount = Number(state.position_sizing?.eligible_size_count || 0);
  const dataPipeReady = premarket.status === "passed" && ["pass", "previous_pass"].includes(premarket.probe_status);
  const integrityReady = premarket.integrity_status === "pass" || state.forward_validation?.integrity_issue_count === 0;
  const marketOpen = Boolean(market.market_is_open || state.market?.market_is_open);
  const dataFresh = freshness.data_status === "fresh_for_today";
  const candleState = candleFreshnessState(state);
  const riskGuard = state.risk_guard || {};
  const hasPaperCandidate = candidateCount > 0 && eligibleSizeCount > 0;
  const blockedReason = refresh.paper_import_reason || "Blocked until a fresh reviewed current-candle candidate exists.";
  let status = "watch";
  let label = "Waiting";
  let message = "The data pipe is ready. Wait for regular market-hours candles, then refresh Webull data.";

  if (!dataPipeReady || !integrityReady) {
    status = "caution";
    label = "Blocked";
    message = "Fix the pre-market/data checks before trusting scanner output.";
  } else if (marketOpen && dataFresh && hasPaperCandidate) {
    status = "healthy";
    label = "Review";
    message = "A current-session candidate has size information. Use the checklist before any local paper log.";
  } else if (marketOpen && dataFresh) {
    status = "watch";
    label = "Scanning";
    message = "Today's data is fresh, but no size-ok current-candle candidate is ready yet.";
  } else if (!marketOpen) {
    status = "watch";
    label = "Waiting";
    message = "Local safeguards pass. The only blocker is waiting for regular market-hours candles.";
  }

  const nextAction = refresh.next_action || freshness.action || "Run the local readiness reports, then refresh this app.";
  const command = refresh.refresh_command || "python run_daily_workflow.py --refresh-data";
  const actionText = marketOpen && !dataFresh ? command : nextAction;

  return {
    status,
    label,
    message,
    actionText,
    cards: [
      {
        title: "Data Pipe",
        value: dataPipeReady && integrityReady ? "Ready" : "Check",
        detail: `Probe: ${titleCase(premarket.probe_status || "not_run")} / Integrity: ${integrityReady ? "Pass" : "Review"}`,
        level: dataPipeReady && integrityReady ? "healthy" : "caution",
      },
      {
        title: "Market Clock",
        value: titleCase(market.market_status || state.market?.market_status || "unknown"),
        detail: market.market_status_reason || `Next session: ${state.market?.next_market_session || "--"}`,
        level: marketOpen ? "healthy" : "watch",
      },
      {
        title: "Scanner Freshness",
        value: titleCase(freshness.data_status || "unknown"),
        detail: `Latest scanner: ${freshness.latest_scanner_session || "unknown"}`,
        level: appStatusLevel(freshness.data_status),
      },
      {
        title: "Candle Age",
        value: candleState.label,
        detail: candleState.detail,
        level: candleState.tone,
      },
      {
        title: "Paper Gate",
        value: refresh.paper_import_blocked === false ? "Review First" : "Blocked",
        detail: blockedReason,
        level: refresh.paper_import_blocked === false ? "watch" : "caution",
      },
      {
        title: "Candidate Review",
        value: `${candidateCount} candidate${candidateCount === 1 ? "" : "s"}`,
        detail: `${eligibleSizeCount} eligible paper size${eligibleSizeCount === 1 ? "" : "s"}`,
        level: hasPaperCandidate ? "healthy" : "watch",
      },
      {
        title: "Risk Guard",
        value: `${Number(riskGuard.max_forward_risk_pct || 0.5).toFixed(2)}% max`,
        detail: riskGuard.message || "Forward paper risk remains conservative until validation gates pass.",
        level: riskGuard.scale_allowed ? "watch" : "caution",
      },
    ],
  };
}

function commandCenterDecision(state) {
  const refresh = state.refresh_status || {};
  const premarket = state.premarket_verification || {};
  const freshness = state.data_freshness || {};
  const market = refresh.market || state.market || {};
  const candidateState = state.current_candidates || {};
  const scanDigest = state.post_scan_digest || {};
  const safety = state.safety || {};
  const marketOpen = Boolean(market.market_is_open || state.market?.market_is_open);
  const dataFresh = freshness.data_status === "fresh_for_today";
  const candleState = candleFreshnessState(state);
  const reviewable = Number(candidateState.ready_for_review_count || 0);
  const current = Number(candidateState.count || 0);
  const liveFlagsOff = safety.live_trading_enabled === false && safety.broker_order_execution_enabled === false;
  const premarketBlocked = ["failed", "fail"].includes(premarket.status) || ["failed", "fail"].includes(premarket.probe_status);

  if (!liveFlagsOff) {
    return {
      tone: "caution",
      title: "Stop and check safety flags.",
      detail: "One of the execution safety flags is not in the expected disabled state. Do not use this app for paper review until that is fixed.",
      button: "Open Guardrails",
      target: "#system",
    };
  }

  if (premarketBlocked) {
    return {
      tone: "caution",
      title: "Fix the pre-market/data gate before trusting scanner output.",
      detail: "The pre-market gate or data probe is failing. Run the local pre-market check and review the pre-market report.",
      button: "Run Pre-Market Check",
      action: "premarket",
    };
  }

  if (marketOpen && !dataFresh) {
    return {
      tone: "watch",
      title: "Market is open, but the scanner data is stale.",
      detail: "Refresh Webull data before reviewing candidates. This rebuilds reports and stays research-only.",
      button: "Refresh Webull Data",
      action: "refresh-webull",
    };
  }

  if (marketOpen && candleState.isStale) {
    return {
      tone: "caution",
      title: "Market is open, but candle timestamps need a refresh.",
      detail: `${candleState.detail} Refresh Webull data before reviewing paper candidates.`,
      button: "Refresh Webull Data",
      action: "refresh-webull",
    };
  }

  if (reviewable > 0) {
    return {
      tone: "healthy",
      title: `${reviewable} candidate${reviewable === 1 ? "" : "s"} ready for manual review.`,
      detail: "Start with the candidate card, then confirm chart context, checklist, stop, target, and paper size before any local paper log.",
      button: "Review Candidates",
      target: "#candidates",
    };
  }

  if (marketOpen && dataFresh) {
    return {
      tone: "watch",
      title: "Data is fresh. Keep scanning and wait for a clean setup.",
      detail: current > 0
        ? `${current} current setup row${current === 1 ? "" : "s"} exist, but none are fully reviewable yet. Check blockers before doing anything.`
        : "No current-candle candidate is ready. Let the 5-minute workflow keep updating.",
      button: "Open Trading Workspace",
      target: "#trading-workspace",
    };
  }

  return {
    tone: "watch",
    title: "Prep mode. No market-hours action is needed right now.",
    detail: "Use this time for replay practice, report review, and checking App Health before the next regular session.",
    button: "Practice Replay",
    target: "#practice-replay",
  };
}

function setCommandCard(cardId, statusId, detailId, tone, status, detail) {
  const card = $(cardId);
  card.className = tone;
  setText(statusId, status);
  setText(detailId, detail);
}

function alertAudio(kind) {
  return kind === "exit" ? $("exit-alert-audio") : $("entry-alert-audio");
}

async function playAlertSound(kind) {
  if (!alertsEnabled) return;
  const toggle = kind === "exit" ? $("exit-alert-toggle") : $("entry-alert-toggle");
  if (!toggle?.checked) return;
  const audio = alertAudio(kind);
  if (!audio) return;
  try {
    audio.currentTime = 0;
    await audio.play();
  } catch {
    updateNotificationPanel("muted", "Sound blocked", "Click Enable alerts once, then leave this dashboard tab open.");
  }
}

function updateNotificationPanel(tone, title, detail) {
  const panel = $("notification-panel");
  panel.className = `notification-panel ${tone}`;
  $("notification-title").textContent = title;
  $("notification-detail").textContent = detail;
}

function readyCandidateKey(card) {
  return [card.symbol, card.setup, card.signal_time_et, card.entry, card.stop, card.target].join("|");
}

function openPaperKey(row) {
  return [row.row, row.symbol, row.setup, row.entry_time_et].join("|");
}

function monitorCandidateAlerts(state) {
  const cards = state.current_candidates?.cards || [];
  const readyCards = cards.filter((card) => card.ready_for_review);
  const readyKeys = new Set(readyCards.map(readyCandidateKey));
  const newReady = readyCards.filter((card) => !lastReadyCandidateKeys.has(readyCandidateKey(card)));
  lastReadyCandidateKeys = readyKeys;
  if (!alertStateInitialized || !newReady.length) return;

  const first = newReady[0];
  updateNotificationPanel(
    "entry",
    `${newReady.length} paper-ready candidate${newReady.length === 1 ? "" : "s"}`,
    `${first.symbol} ${first.setup} is ready for manual review. No broker order was placed.`,
  );
  playAlertSound("entry");
}

function monitorExitAlerts(rows = []) {
  const openKeys = new Set(rows.map(openPaperKey));
  if (alertStateInitialized) {
    const closedCount = [...lastOpenPaperKeys].filter((key) => !openKeys.has(key)).length;
    if (closedCount > 0) {
      updateNotificationPanel(
        "exit",
        `${closedCount} paper trade${closedCount === 1 ? "" : "s"} closed`,
        "Open paper row count changed after outcome logging or monitoring. Review Paper Progress.",
      );
      playAlertSound("exit");
    }
  }
  lastOpenPaperKeys = openKeys;
}

function renderCommandCenter(state) {
  const decision = commandCenterDecision(state);
  const files = state.app_health?.source_file_states || {};
  const automation = files.autonomous_status_md || {};
  const watchdog = state.morning_watchdog || {};
  const scanDigest = state.post_scan_digest || {};
  const candidateState = state.current_candidates || {};
  const safety = state.safety || {};
  const marketOpen = Boolean(state.refresh_status?.market?.market_is_open || state.market?.market_is_open);
  const watchdogStatus = watchdog.status || "";
  const automationTone = watchdogStatus === "pass" ? "healthy" : automation.exists ? "watch" : "watch";
  const automationStatus = watchdogStatus === "pass" ? "Confirmed Today" : automation.exists ? titleCase(watchdogStatus || "Status Written") : "Not confirmed";
  const automationDetail = watchdog.generated_at_et
    ? `${watchdog.headline || "Watchdog report available"} Next: ${watchdog.next_action || "Review morning watchdog."}`
    : automation.exists
      ? `Last status write: ${automation.modified_et}. Morning watchdog will confirm the next scheduled market scan.`
    : "No autonomous workflow status file yet. The dashboard can still be used manually.";
  const dataTone = appStatusLevel(state.data_freshness?.data_status);
  const dataStatus = titleCase(state.data_freshness?.data_status || "unknown");
  const dataDetail = `Latest scanner session: ${state.data_freshness?.latest_scanner_session || "unknown"}.`;
  const candleState = candleFreshnessState(state);
  const reviewable = Number(candidateState.ready_for_review_count || 0);
  const current = Number(candidateState.count || 0);
  const actionNeeded = scanDigest.action || "";
  const candidateTone = actionNeeded === "review_candidate" ? "healthy" : actionNeeded === "data_issue" ? "caution" : "watch";
  const candidateStatus = scanDigest.action ? titleCase(scanDigest.action.replace(/_/g, " ")) : `${reviewable} reviewable`;
  const candidateDetail = scanDigest.headline
    ? `${scanDigest.headline} Next: ${scanDigest.next_action || "Review post-scan digest."}`
    : `${current} current-candle candidate${current === 1 ? "" : "s"} in the latest scanner output.`;
  const liveFlagsOff = safety.live_trading_enabled === false && safety.broker_order_execution_enabled === false;
  const safetyTone = liveFlagsOff ? "healthy" : "caution";
  const safetyStatus = liveFlagsOff ? "Paper only" : "Check flags";
  const safetyDetail = liveFlagsOff
    ? "Broker execution and live trading are disabled."
    : "One or more execution flags is not in the expected disabled state.";
  const backtests = state.backtest_performance || {};
  const best = backtests.best_candidate || {};
  const backtestTone = Number(backtests.positive_expectancy_count || 0) > 0 ? "healthy" : "watch";
  const backtestStatus = `${backtests.positive_expectancy_count || 0} positive`;
  const backtestDetail = best.symbol
    ? `Best: ${best.symbol} ${Number(best.win_rate_pct || 0).toFixed(1)}% win, ${rValue(best.expectancy_r)} exp across ${best.trades} trades.`
    : "No saved backtest trade samples yet.";

  $("command-title").textContent = decision.title;
  $("command-detail").textContent = decision.detail;
  $("command-center").className = `command-center ${decision.tone}`;
  const action = $("command-primary-action");
  action.textContent = decision.button;
  action.dataset.action = decision.action || "";
  action.dataset.target = decision.target || "";
  action.disabled = false;

  setCommandCard("command-automation-card", "command-automation-status", "command-automation-detail", automationTone, automationStatus, automationDetail);
  setCommandCard("command-data-card", "command-data-status", "command-data-detail", dataTone, dataStatus, dataDetail);
  setCommandCard("command-candle-card", "command-candle-status", "command-candle-detail", candleState.tone, candleState.label, candleState.detail);
  setCommandCard("command-candidate-card", "command-candidate-status", "command-candidate-detail", candidateTone, candidateStatus, candidateDetail);
  setCommandCard("command-safety-card", "command-safety-status", "command-safety-detail", safetyTone, safetyStatus, safetyDetail);
  setCommandCard("command-backtest-card", "command-backtest-status", "command-backtest-detail", backtestTone, backtestStatus, backtestDetail);

  if (!marketOpen && decision.action === "refresh-webull") {
    action.disabled = true;
  }
}

function renderBacktestPerformance(state) {
  const backtests = state.backtest_performance || {};
  const best = backtests.best_candidate || {};
  const rows = backtests.top_candidates || [];
  latestBacktestRows = rows;
  const positive = Number(backtests.positive_expectancy_count || 0);
  const candidateCount = Number(backtests.candidate_count || 0);
  const totalTrades = Number(backtests.total_trades || 0);

  $("backtest-message").textContent = rows.length
    ? "Latest historical backtest snapshot from the saved watchlist summary files. Use this for research context; paper-validation evidence remains separate."
    : "No backtest summary rows with trades are available yet. Run the Webull data refresh/backtest workflow to populate this view.";
  setText("backtest-candidate-count", candidateCount);
  setText("backtest-total-trades", totalTrades);
  setText("backtest-positive-count", positive);
  setText("backtest-best-name", best.symbol ? `${best.symbol} ${best.setup_family}` : "--");
  setText(
    "backtest-best-detail",
    best.symbol
      ? `${best.trades} trades / ${Number(best.win_rate_pct || 0).toFixed(1)}% wins / ${rValue(best.expectancy_r)} exp`
      : "No sample yet.",
  );

  $("backtest-table-body").innerHTML = rows.length
    ? rows
        .map((row, index) => {
          const expectancy = Number(row.expectancy_r || 0);
          return `
            <tr>
              <td>${escapeHtml(row.setup_family)}</td>
              <td>${escapeHtml(row.symbol)}</td>
              <td>${escapeHtml(row.candidate)}</td>
              <td>${escapeHtml(row.trades)}</td>
              <td>${escapeHtml(Number(row.win_rate_pct || 0).toFixed(1))}%</td>
              <td class="${expectancy >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(expectancy))}</td>
              <td>${escapeHtml(Number(row.profit_factor || 0) >= 999 ? "inf" : Number(row.profit_factor || 0).toFixed(2))}</td>
              <td><button type="button" class="backtest-view-trades" data-index="${escapeHtml(index)}">View trades</button></td>
            </tr>
          `;
        })
        .join("")
    : '<tr><td colspan="8">No backtest rows with trade samples yet.</td></tr>';

  for (const button of document.querySelectorAll(".backtest-view-trades")) {
    button.addEventListener("click", () => loadBacktestTrades(Number(button.dataset.index)));
  }
}

function renderResearchConfidence(state) {
  const research = state.research_confidence || {};
  const rows = research.top_candidates || [];
  const report = research.source_report || {};

  setText("research-tested-symbols", research.tested_symbols || 0);
  setText("research-ready-count", research.research_ready_count || 0);
  setText("research-promising-count", research.promising_count || 0);
  setText("research-candidate-count", research.candidate_count || 0);

  $("research-confidence-message").textContent = rows.length
    ? "Broad research scores are loaded. Promote nothing directly from here; use these rows to decide what deserves deeper review and forward paper validation."
    : "No broad research confidence file is available yet. Run the research expansion workflow when you want to test the wider universe.";

  const reportLink = $("research-confidence-report-link");
  if (report.exists) {
    reportLink.href = "/logs/universe_expansion/research_confidence.md";
    reportLink.classList.remove("disabled-link");
  } else {
    reportLink.href = "#research";
    reportLink.classList.add("disabled-link");
  }

  $("research-confidence-body").innerHTML = rows.length
    ? rows
        .map((row) => {
          const expectancy = Number(row.expectancy_r || 0);
          const statusClass = String(row.research_status || "").replace(/[^a-z0-9_-]/gi, "_");
          return `
            <tr>
              <td><span class="status ${escapeHtml(statusClass)}">${escapeHtml(titleCase(row.research_status || "review"))}</span></td>
              <td>${escapeHtml(row.readiness_score || 0)}</td>
              <td>${escapeHtml(row.symbol)}</td>
              <td>${escapeHtml(row.setup)}</td>
              <td>${escapeHtml(row.candidate)}${Number(row.duplicate_rows_collapsed || 1) > 1 ? ` <span class="dedupe-note">${escapeHtml(row.duplicate_rows_collapsed)} labels</span>` : ""}</td>
              <td>${escapeHtml(row.trades)}</td>
              <td class="${expectancy >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(expectancy))}</td>
              <td>${escapeHtml(Number(row.profit_factor || 0) >= 999 ? "inf" : Number(row.profit_factor || 0).toFixed(2))}</td>
            </tr>
          `;
        })
        .join("")
    : '<tr><td colspan="8">No broad research scores yet.</td></tr>';
}

function renderPromotionReview(state) {
  const review = state.promotion_review || {};
  const rows = review.top_candidates || [];
  const report = review.source_report || {};

  setText("promotion-paper-watch-count", review.paper_watch_count || 0);
  setText("promotion-needs-review-count", review.needs_review_count || 0);
  setText("promotion-needs-samples-count", review.needs_more_samples_count || 0);
  setText("promotion-candidate-count", review.candidate_count || 0);

  $("promotion-review-message").textContent = rows.length
    ? "Promotion Review is the gate between backtest promise and active paper watch. Only paper-watch rows should be considered for forward validation."
    : "No promotion review file is available yet. Run the promotion review after Research Confidence is updated.";

  const reportLink = $("promotion-review-report-link");
  if (report.exists) {
    reportLink.href = "/logs/promotion_review.md";
    reportLink.classList.remove("disabled-link");
  } else {
    reportLink.href = "#research";
    reportLink.classList.add("disabled-link");
  }

  $("promotion-review-body").innerHTML = rows.length
    ? rows
        .map((row) => {
          const expectancy = Number(row.expectancy_r || 0);
          const statusClass = String(row.promotion_decision || "").replace(/[^a-z0-9_-]/gi, "_");
          return `
            <tr>
              <td><span class="status ${escapeHtml(statusClass)}">${escapeHtml(titleCase(row.promotion_decision || "review"))}</span></td>
              <td>${escapeHtml(row.symbol)}</td>
              <td>${escapeHtml(row.setup)}</td>
              <td>${escapeHtml(row.candidate)}</td>
              <td>${escapeHtml(row.trades)}</td>
              <td class="${expectancy >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(expectancy))}</td>
              <td>${escapeHtml(Number(row.profit_factor || 0) >= 999 ? "inf" : Number(row.profit_factor || 0).toFixed(2))}</td>
              <td class="${Number(row.max_drawdown_r || 0) < 0 ? "negative" : ""}">${escapeHtml(rValue(row.max_drawdown_r || 0))}</td>
              <td>${escapeHtml(row.positive_months || 0)}/${escapeHtml(row.months_tested || 0)}</td>
              <td>${escapeHtml(row.promotion_reason)}</td>
            </tr>
          `;
        })
        .join("")
    : '<tr><td colspan="10">No promotion review rows yet.</td></tr>';
}

function backtestAccountParams() {
  const startingEquity = Math.max(Number($("backtest-starting-equity")?.value || 5000), 100);
  const riskPercent = Math.min(Math.max(Number($("backtest-risk-pct")?.value || 0.5), 0.1), 10);
  return {
    startingEquity,
    riskPercent,
    riskDecimal: riskPercent / 100,
  };
}

function renderBacktestAccountSummary(account = {}) {
  setAccountSummary("backtest", account);
}

function setAccountSummary(prefix, account = {}) {
  const pnl = Number(account.total_pnl || 0);
  const returnPct = Number(account.return_pct || 0);
  $(`${prefix}-ending-equity`).textContent = dollarValue(account.ending_equity || account.starting_equity || 5000);
  $(`${prefix}-total-pnl`).textContent = `${pnl >= 0 ? "+" : ""}${dollarValue(pnl)}`;
  $(`${prefix}-total-pnl`).className = pnl >= 0 ? "positive" : "negative";
  $(`${prefix}-return-pct`).textContent = `${returnPct >= 0 ? "+" : ""}${returnPct.toFixed(2)}%`;
  $(`${prefix}-return-pct`).className = returnPct >= 0 ? "positive" : "negative";
  $(`${prefix}-max-drawdown`).textContent = dollarValue(account.max_drawdown || 0);
  $(`${prefix}-max-drawdown`).className = Number(account.max_drawdown || 0) < 0 ? "negative" : "";
}

function formatDateLabel(value) {
  if (!value) return "--";
  const date = parseDateValue(value);
  if (Number.isNaN(date.getTime())) return text(value, "--").slice(0, 10);
  return date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function parseDateValue(value) {
  if (!value) return new Date("");
  const raw = text(value, "").trim();
  const normalized = raw.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})([+-]\d{2}:\d{2}|Z)?$/, "$1T$2$3");
  return new Date(normalized);
}

function monthKeyFromValue(value) {
  const date = parseDateValue(value);
  if (Number.isNaN(date.getTime())) return "Undated";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabelFromKey(key) {
  if (key === "Undated") return key;
  const date = new Date(`${key}-01T00:00:00`);
  if (Number.isNaN(date.getTime())) return key;
  return date.toLocaleDateString([], { month: "short", year: "numeric" });
}

function monthlyBreakdown(rows = []) {
  const buckets = new Map();
  for (const row of rows) {
    const key = monthKeyFromValue(row.entry_time || row.exit_time);
    const current = buckets.get(key) || { month: key, trades: 0, pnl: 0, r: 0 };
    current.trades += 1;
    current.pnl += Number(row.pnl_dollars || 0);
    current.r += Number(row.r_result || 0);
    buckets.set(key, current);
  }
  return Array.from(buckets.values()).sort((a, b) => a.month.localeCompare(b.month));
}

function renderMonthlyBreakdown(elementId, rows = []) {
  const element = $(elementId);
  const months = monthlyBreakdown(rows);
  if (!months.length) {
    element.innerHTML = '<p class="paper-empty">Monthly P/L appears after trades are available.</p>';
    return;
  }
  const maxAbs = Math.max(...months.map((month) => Math.abs(month.pnl)), 1);
  element.innerHTML = `
    <div class="monthly-heading">
      <strong>Monthly P/L</strong>
      <span>${escapeHtml(months.length)} months</span>
    </div>
    ${months
      .map((month) => {
        const width = Math.max((Math.abs(month.pnl) / maxAbs) * 100, 4);
        const positive = month.pnl >= 0;
        return `
          <div class="monthly-row">
            <span>${escapeHtml(monthLabelFromKey(month.month))}</span>
            <div class="monthly-bar-track">
              <div class="monthly-bar ${positive ? "positive" : "negative"}" style="width: ${width}%"></div>
            </div>
            <strong class="${positive ? "positive" : "negative"}">${escapeHtml(`${positive ? "+" : ""}${dollarValue(month.pnl)}`)}</strong>
            <em>${escapeHtml(month.trades)} trades / ${escapeHtml(rValue(month.r))}</em>
          </div>
        `;
      })
      .join("")}
  `;
}

function accountParams(prefix) {
  const startingEquity = Math.max(Number($(`${prefix}-starting-equity`)?.value || 5000), 100);
  const riskPercent = Math.min(Math.max(Number($(`${prefix}-risk-pct`)?.value || 0.5), 0.1), 10);
  return {
    startingEquity,
    riskPercent,
    riskDecimal: riskPercent / 100,
  };
}

function backtestTradeStats(rows = []) {
  const results = rows.map((row) => Number(row.r_result || 0));
  const wins = results.filter((value) => value > 0);
  const losses = results.filter((value) => value < 0);
  const flat = results.filter((value) => value === 0);
  const sum = results.reduce((total, value) => total + value, 0);
  const averageR = results.length ? sum / results.length : 0;
  const bestR = results.length ? Math.max(...results) : 0;
  const worstR = results.length ? Math.min(...results) : 0;
  const bestTrade = rows.find((row) => Number(row.r_result || 0) === bestR) || {};
  const worstTrade = rows.find((row) => Number(row.r_result || 0) === worstR) || {};
  let currentLossStreak = 0;
  let maxLossStreak = 0;
  for (const result of results) {
    if (result < 0) {
      currentLossStreak += 1;
      maxLossStreak = Math.max(maxLossStreak, currentLossStreak);
    } else {
      currentLossStreak = 0;
    }
  }
  const exitCounts = rows.reduce((counts, row) => {
    const reason = titleCase(row.exit_reason || "unknown");
    counts[reason] = (counts[reason] || 0) + 1;
    return counts;
  }, {});
  const commonExit = Object.entries(exitCounts).sort((a, b) => b[1] - a[1])[0] || ["--", 0];
  return {
    total: rows.length,
    wins: wins.length,
    losses: losses.length,
    flat: flat.length,
    winRate: rows.length ? (wins.length / rows.length) * 100 : 0,
    averageR,
    bestR,
    worstR,
    bestTrade,
    worstTrade,
    maxLossStreak,
    commonExit,
  };
}

function renderBacktestTradeContext(rows = [], account = {}) {
  if (!rows.length) {
    $("backtest-context-grid").innerHTML = `
      <article><span>Win Rate</span><strong>--</strong><p>Select a backtest row.</p></article>
      <article><span>Average R</span><strong>--</strong><p>Historical simulation.</p></article>
      <article><span>Best / Worst</span><strong>--</strong><p>Trade extremes.</p></article>
      <article><span>Max Loss Streak</span><strong>--</strong><p>Discipline pressure.</p></article>
    `;
    $("backtest-trade-insights").textContent =
      "Select a backtest row to see trade context, drawdown behavior, and exit patterns.";
    return;
  }

  const stats = backtestTradeStats(rows);
  const startingEquity = Number(account.starting_equity || 5000);
  const endingEquity = Number(account.ending_equity || startingEquity);
  const accountClass = endingEquity >= startingEquity ? "positive" : "negative";
  $("backtest-context-grid").innerHTML = `
    <article>
      <span>Win Rate</span>
      <strong>${escapeHtml(stats.winRate.toFixed(1))}%</strong>
      <p>${escapeHtml(stats.wins)} wins / ${escapeHtml(stats.losses)} losses / ${escapeHtml(stats.flat)} flat</p>
    </article>
    <article>
      <span>Average R</span>
      <strong class="${stats.averageR >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(stats.averageR))}</strong>
      <p>Across ${escapeHtml(stats.total)} simulated trades</p>
    </article>
    <article>
      <span>Best / Worst</span>
      <strong>${escapeHtml(rValue(stats.bestR))} / ${escapeHtml(rValue(stats.worstR))}</strong>
      <p>${escapeHtml(text(stats.bestTrade.entry_time, "Best trade"))} / ${escapeHtml(text(stats.worstTrade.entry_time, "Worst trade"))}</p>
    </article>
    <article>
      <span>Max Loss Streak</span>
      <strong class="${stats.maxLossStreak >= 3 ? "negative" : ""}">${escapeHtml(stats.maxLossStreak)}</strong>
      <p>Most common exit: ${escapeHtml(stats.commonExit[0])} (${escapeHtml(stats.commonExit[1])})</p>
    </article>
  `;
  $("backtest-trade-insights").innerHTML = `
    <strong class="${accountClass}">${escapeHtml(dollarValue(startingEquity))} to ${escapeHtml(dollarValue(endingEquity))}</strong>
    using compounded position risk. Best trade: ${escapeHtml(rValue(stats.bestR))} at ${escapeHtml(text(stats.bestTrade.exit_time, "--"))}.
    Worst trade: ${escapeHtml(rValue(stats.worstR))} at ${escapeHtml(text(stats.worstTrade.exit_time, "--"))}.
    This is still historical simulation context only, not live-trade approval.
  `;
}

function backtestDollarEquityChart(rows, startingEquity) {
  if (!rows?.length) {
    return '<div class="paper-empty-chart">Select a backtest row to see the retro paper account curve.</div>';
  }

  const width = 760;
  const height = 300;
  const left = 58;
  const right = 24;
  const top = 24;
  const equityBottom = 190;
  const drawdownTop = 222;
  const bottom = 274;
  const chartRows = [{ account_equity_after: startingEquity }, ...rows];
  const values = chartRows.map((row) => Number(row.account_equity_after || startingEquity));
  const maxValue = Math.max(...values);
  const minValue = Math.min(...values);
  const span = Math.max(maxValue - minValue, 1);
  const x = (index) => left + (index / Math.max(chartRows.length - 1, 1)) * (width - left - right);
  const y = (value) => top + ((maxValue - value) / span) * (equityBottom - top);
  const line = chartRows.map((row, index) => `${x(index)},${y(Number(row.account_equity_after || startingEquity))}`).join(" ");
  const baseline = y(startingEquity);
  const finalValue = values[values.length - 1];
  const runningPeaks = [];
  let peak = values[0];
  for (const value of values) {
    peak = Math.max(peak, value);
    runningPeaks.push(peak);
  }
  const drawdowns = values.map((value, index) => value - runningPeaks[index]);
  const maxDrawdown = Math.min(...drawdowns);
  const drawdownSpan = Math.max(Math.abs(maxDrawdown), 1);
  const drawdownY = (value) => drawdownTop + (Math.abs(value) / drawdownSpan) * (bottom - drawdownTop);
  const gridValues = [maxValue, (maxValue + minValue) / 2, minValue];
  const grid = gridValues
    .map(
      (value) => `
        <line class="chart-grid-line" x1="${left}" y1="${y(value)}" x2="${width - right}" y2="${y(value)}"></line>
        <text class="chart-axis-label" x="${left - 8}" y="${y(value) + 4}" text-anchor="end">${escapeHtml(dollarValue(value))}</text>
      `,
    )
    .join("");
  const markers = rows
    .map((row, index) => {
      const chartIndex = index + 1;
      const result = Number(row.r_result || 0);
      return `
        <circle class="chart-trade-marker ${result >= 0 ? "win" : "loss"}" cx="${x(chartIndex)}" cy="${y(values[chartIndex])}" r="4">
          <title>Trade ${chartIndex}: ${escapeHtml(rValue(result))} / ${escapeHtml(dollarValue(row.pnl_dollars))}</title>
        </circle>
      `;
    })
    .join("");
  const drawdownBars = drawdowns
    .slice(1)
    .map((value, index) => {
      const chartIndex = index + 1;
      const barWidth = Math.max((width - left - right) / Math.max(rows.length, 1) - 2, 2);
      const barHeight = Math.max(drawdownY(value) - drawdownTop, 1);
      return `<rect class="drawdown-bar" x="${x(chartIndex) - barWidth / 2}" y="${drawdownTop}" width="${barWidth}" height="${barHeight}"></rect>`;
    })
    .join("");
  const labelIndexes = Array.from(new Set([0, Math.floor((chartRows.length - 1) / 2), chartRows.length - 1]));
  const xLabels = labelIndexes
    .map(
      (index) =>
        `<text class="chart-axis-label" x="${x(index)}" y="${height - 8}" text-anchor="${index === 0 ? "start" : index === chartRows.length - 1 ? "end" : "middle"}">Trade ${index}</text>`,
    )
    .join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Retro paper account equity chart">
      <text class="chart-title" x="${left}" y="14">Simulated account equity</text>
      ${grid}
      <line class="chart-baseline" x1="${left}" y1="${baseline}" x2="${width - right}" y2="${baseline}"></line>
      <polyline class="chart-line ${finalValue >= startingEquity ? "positive" : "negative"}" points="${line}"></polyline>
      <circle class="chart-endpoint ${finalValue >= startingEquity ? "positive" : "negative"}" cx="${x(chartRows.length - 1)}" cy="${y(finalValue)}" r="5"></circle>
      ${markers}
      <text class="chart-axis-label" x="${left}" y="${Math.max(baseline - 7, 22)}">${escapeHtml(dollarValue(startingEquity))}</text>
      <text class="chart-axis-label" x="${width - right}" y="${Math.max(y(finalValue) - 9, 22)}" text-anchor="end">${escapeHtml(dollarValue(finalValue))}</text>
      <text class="chart-title" x="${left}" y="${drawdownTop - 10}">Drawdown from peak</text>
      <line class="chart-grid-line" x1="${left}" y1="${drawdownTop}" x2="${width - right}" y2="${drawdownTop}"></line>
      ${drawdownBars}
      <text class="chart-axis-label" x="${left - 8}" y="${drawdownTop + 4}" text-anchor="end">$0</text>
      <text class="chart-axis-label" x="${left - 8}" y="${bottom}" text-anchor="end">${escapeHtml(dollarValue(maxDrawdown))}</text>
      ${xLabels}
    </svg>
  `;
}

async function loadBacktestTrades(index) {
  const row = latestBacktestRows[index];
  if (!row?.baseline_trade_log) return;
  selectedBacktestIndex = index;
  const accountParams = backtestAccountParams();
  $("backtest-trade-title").textContent = `${row.symbol} ${row.setup_family} / ${row.candidate}`;
  $("backtest-trade-message").textContent = "Loading simulated trade rows...";
  $("backtest-trade-count").className = "status watch";
  $("backtest-trade-count").textContent = "Loading";
  renderBacktestTradeContext([], {});
  $("backtest-equity-chart").innerHTML = '<div class="paper-empty-chart">Calculating retro paper account curve...</div>';
  $("backtest-trade-body").innerHTML = '<tr><td colspan="13">Loading simulated trades...</td></tr>';

  try {
    const fileName = row.baseline_trade_log.split("/").pop();
    const params = new URLSearchParams({
      file: fileName,
      starting_equity: String(accountParams.startingEquity),
      risk_per_trade_pct: String(accountParams.riskDecimal),
    });
    const response = await fetch(`${backtestTradesUrl}?${params.toString()}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Trade log request failed: ${response.status}`);

    $("backtest-trade-count").className = "status review_only";
    $("backtest-trade-count").textContent = `${payload.row_count} simulated`;
    $("backtest-trade-message").textContent =
      `${payload.filename}. Retro account uses ${dollarValue(payload.account.starting_equity)} starting equity and ${(Number(payload.account.risk_per_trade_pct) * 100).toFixed(2)}% risk per trade. These are historical simulations only.`;
    renderBacktestAccountSummary(payload.account);
    renderBacktestTradeContext(payload.rows || [], payload.account);
    $("backtest-equity-chart").innerHTML = backtestDollarEquityChart(payload.rows, Number(payload.account.starting_equity || 5000));
    $("backtest-trade-body").innerHTML = payload.rows?.length
      ? payload.rows
          .map((trade) => {
            const result = Number(trade.r_result || 0);
            const pnl = Number(trade.pnl_dollars || 0);
            return `
              <tr>
                <td>${escapeHtml(text(trade.entry_time, "--"))}</td>
                <td>${escapeHtml(text(trade.exit_time, "--"))}</td>
                <td>${escapeHtml(text(trade.quality_grade, "--"))} ${escapeHtml(text(trade.quality_score, ""))}</td>
                <td>${escapeHtml(text(trade.entry, "--"))}</td>
                <td>${escapeHtml(text(trade.stop, "--"))}</td>
                <td>${escapeHtml(text(trade.target, "--"))}</td>
                <td>${escapeHtml(text(trade.exit_price, "--"))}</td>
                <td class="${result >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(result))}</td>
                <td>${escapeHtml(dollarValue(trade.risk_dollars))}</td>
                <td class="${pnl >= 0 ? "positive" : "negative"}">${escapeHtml(`${pnl >= 0 ? "+" : ""}${dollarValue(pnl)}`)}</td>
                <td>${escapeHtml(dollarValue(trade.account_equity_after))}</td>
                <td>${escapeHtml(titleCase(trade.exit_reason || "--"))}</td>
                <td>${escapeHtml(text(trade.relative_volume, "--"))}</td>
              </tr>
            `;
          })
          .join("")
      : '<tr><td colspan="13">This trade log exists but has no rows.</td></tr>';
  } catch (error) {
    $("backtest-trade-count").className = "status caution";
    $("backtest-trade-count").textContent = "Unavailable";
    $("backtest-trade-message").textContent = error.message;
    renderBacktestTradeContext([], {});
    $("backtest-trade-body").innerHTML = '<tr><td colspan="13">Could not load simulated trades.</td></tr>';
  }
}

function renderSessionReadiness(state) {
  const summary = readinessSummary(state);
  setStatusPill($("readiness-summary-status"), summary.status);
  $("readiness-summary-status").textContent = summary.label;
  $("readiness-summary-message").textContent = summary.message;
  $("readiness-next-action").textContent = summary.actionText;
  $("readiness-summary-cards").innerHTML = summary.cards
    .map(
      (card) => `
        <article class="${safeClassName(card.level)}">
          <span>${escapeHtml(card.title)}${helpBubble(helpKey(card.title))}</span>
          <strong>${escapeHtml(card.value)}</strong>
          <p>${escapeHtml(card.detail)}</p>
        </article>
      `,
    )
    .join("");
}

function replayCardKey(card) {
  return `${card.symbol}|${card.setup}|${card.entry_time}`;
}

function readReplayJournal() {
  try {
    const saved = window.localStorage.getItem(replayJournalStorageKey);
    const parsed = saved ? JSON.parse(saved) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (error) {
    return {};
  }
}

function saveReplayJournal() {
  try {
    window.localStorage.setItem(replayJournalStorageKey, JSON.stringify(replayJournal));
    return true;
  } catch (error) {
    return false;
  }
}

function replayJournalEntry(card) {
  return replayJournal[replayCardKey(card)] || {};
}

function reviewedReplayRows() {
  return allReplayCards
    .map((card) => ({ card, journal: replayJournalEntry(card) }))
    .filter(({ journal }) => journal.outcome_reviewed && journal.decision)
    .map(({ card, journal }) => ({
      card,
      journal,
      outcome_r: Number(card.r_result),
    }));
}

function selectOptions(values, allLabel) {
  return [
    `<option value="">${escapeHtml(allLabel)}</option>`,
    ...values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`),
  ].join("");
}

function renderReplayFilterOptions() {
  const reviewedCards = allReplayCards.filter((card) => replayJournalEntry(card).outcome_reviewed);
  const unique = (values) => [...new Set(values.filter(Boolean))].sort();
  const selections = {
    symbol: replayFilterState.symbol,
    setup: replayFilterState.setup,
    grade: replayFilterState.grade,
    exit_reason: replayFilterState.exit_reason,
  };
  $("replay-filter-symbol").innerHTML = selectOptions(unique(allReplayCards.map((card) => card.symbol)), "All symbols");
  $("replay-filter-setup").innerHTML = selectOptions(unique(allReplayCards.map((card) => card.setup)), "All setups");
  $("replay-filter-grade").innerHTML = selectOptions(unique(allReplayCards.map((card) => card.quality_grade)), "All grades");
  const exitReasons = unique(reviewedCards.map((card) => card.exit_reason)).map((reason) => titleCase(reason));
  if (replayFilterState.exit_reason && !exitReasons.includes(replayFilterState.exit_reason)) {
    exitReasons.push(replayFilterState.exit_reason);
  }
  $("replay-filter-exit-reason").innerHTML = selectOptions(exitReasons, "All reviewed exits");
  $("replay-filter-symbol").value = selections.symbol;
  $("replay-filter-setup").value = selections.setup;
  $("replay-filter-grade").value = selections.grade;
  $("replay-filter-exit-reason").value = selections.exit_reason;
}

function cardMatchesReplayFilters(card) {
  const journal = replayJournalEntry(card);
  if (replayFilterState.symbol && card.symbol !== replayFilterState.symbol) return false;
  if (replayFilterState.setup && card.setup !== replayFilterState.setup) return false;
  if (replayFilterState.grade && card.quality_grade !== replayFilterState.grade) return false;
  if (replayFilterState.reviewed_only && !journal.outcome_reviewed) return false;
  if (replayFilterState.unreviewed_only && journal.outcome_reviewed) return false;
  if (replayFilterState.result) {
    if (!journal.outcome_reviewed) return false;
    if (replayFilterState.result === "win" && Number(card.r_result) <= 0) return false;
    if (replayFilterState.result === "loss" && Number(card.r_result) >= 0) return false;
  }
  if (replayFilterState.exit_reason) {
    if (!journal.outcome_reviewed || titleCase(card.exit_reason) !== replayFilterState.exit_reason) return false;
  }
  return true;
}

function applyReplayFilters() {
  saveCurrentReplayNote();
  replayCards = allReplayCards.filter(cardMatchesReplayFilters);
  replayIndex = 0;
  resetReplaySession();
  updateReplayFilterMessage();
  updateReplayJournalSummary();
  renderReplayCard();
}

function updateReplayFilterMessage() {
  const protectedFilter = replayFilterState.result || replayFilterState.exit_reason;
  $("replay-filter-message").textContent = `${replayCards.length} of ${allReplayCards.length} historical cards in this session.${
    protectedFilter ? " Outcome-based filters use compared cards only." : ""
  }`;
}

function moveWithinReplaySession(offset) {
  if (!replayCards.length) return;
  saveCurrentReplayNote();
  const currentStillMatches = cardMatchesReplayFilters(replayCards[replayIndex]);
  if (!currentStillMatches) {
    replayCards = allReplayCards.filter(cardMatchesReplayFilters);
    replayIndex = offset < 0 ? Math.max(replayCards.length - 1, 0) : 0;
    updateReplayFilterMessage();
  } else {
    replayIndex = (replayIndex + offset + replayCards.length) % replayCards.length;
  }
  resetReplaySession();
  renderReplayCard();
}

function setReplayPreset(preset) {
  replayFilterState = {
    symbol: "",
    setup: "",
    grade: "",
    result: "",
    exit_reason: "",
    reviewed_only: false,
    unreviewed_only: false,
  };
  if (preset === "unreviewed") {
    replayFilterState.unreviewed_only = true;
  } else if (preset === "a_grade") {
    replayFilterState.grade = "A";
  } else if (preset === "setup_b") {
    replayFilterState.setup = "Setup B Short";
  } else if (preset === "losses") {
    replayFilterState.result = "loss";
  } else if (preset === "stop_losses") {
    replayFilterState.exit_reason = "Stop Loss 5m";
  } else if (preset === "vwap_exits") {
    replayFilterState.exit_reason = "Lost Vwap 2 Closes 5m";
  }
  renderReplayFilterOptions();
  $("replay-filter-result").value = replayFilterState.result;
  for (const button of document.querySelectorAll(".replay-preset-actions button")) {
    button.classList.toggle("active", button.dataset.replayPreset === preset);
  }
  applyReplayFilters();
}

function syncReplayFiltersFromControls() {
  replayFilterState.symbol = $("replay-filter-symbol").value;
  replayFilterState.setup = $("replay-filter-setup").value;
  replayFilterState.grade = $("replay-filter-grade").value;
  replayFilterState.result = $("replay-filter-result").value;
  replayFilterState.exit_reason = $("replay-filter-exit-reason").value;
  replayFilterState.reviewed_only = Boolean(replayFilterState.result || replayFilterState.exit_reason);
  replayFilterState.unreviewed_only = false;
  for (const button of document.querySelectorAll(".replay-preset-actions button")) {
    button.classList.remove("active");
  }
  applyReplayFilters();
}

function averageReplayR(rows, field = "outcome_r") {
  if (!rows.length) return null;
  return rows.reduce((total, row) => total + Number(row[field]), 0) / rows.length;
}

function replayOutcomeSummaryRows(rows, labelForRow) {
  const grouped = new Map();
  rows.forEach((row) => {
    const label = labelForRow(row);
    if (!grouped.has(label)) grouped.set(label, []);
    grouped.get(label).push(row);
  });
  return Array.from(grouped.entries()).map(([label, group]) => ({
    label,
    trades: group.length,
    win_rate: group.filter((row) => row.outcome_r > 0).length / group.length,
    average_r: averageReplayR(group),
  }));
}

function renderReplayOutcomeRows(rows, emptyText) {
  if (!rows.length) return `<p class="paper-empty">${escapeHtml(emptyText)}</p>`;
  return rows
    .map(
      (row) => `
        <div class="replay-score-row">
          <div>
            <strong>${escapeHtml(row.label)}</strong>
            <span>${row.trades} reviewed / ${(row.win_rate * 100).toFixed(1)}% positive outcome</span>
          </div>
          <strong class="${row.average_r >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(row.average_r))} avg</strong>
        </div>
      `,
    )
    .join("");
}

function renderReplayScoring() {
  const reviewed = reviewedReplayRows();
  const takes = reviewed.filter((row) => row.journal.decision === "take");
  const avoidedLosses = reviewed.filter(
    (row) => row.journal.decision !== "take" && row.outcome_r < 0,
  ).length;
  const practiceExits = reviewed
    .filter((row) => Number.isFinite(Number(row.journal.practice_exit_r)))
    .map((row) => ({
      ...row,
      practice_r: Number(row.journal.practice_exit_r),
      delta_r: Number(row.journal.practice_exit_r) - row.outcome_r,
    }));
  const averageExitDelta = averageReplayR(practiceExits, "delta_r");

  $("replay-score-reviewed").textContent = `${reviewed.length} / ${allReplayCards.length}`;
  $("replay-score-take-avg").textContent = takes.length ? rValue(averageReplayR(takes)) : "--";
  $("replay-score-avoided-losses").textContent = String(avoidedLosses);
  $("replay-score-exit-delta").textContent = practiceExits.length ? rValue(averageExitDelta) : "--";
  $("replay-score-exit-delta").className =
    practiceExits.length && averageExitDelta < 0 ? "negative" : practiceExits.length ? "positive" : "";
  $("replay-score-message").textContent = reviewed.length
    ? `${reviewed.length} historical comparison${reviewed.length === 1 ? "" : "s"} scored. Only outcomes you have revealed are included.`
    : "Complete a replay comparison to begin training feedback. Unrevealed outcomes are excluded.";

  const decisionRows = replayOutcomeSummaryRows(reviewed, (row) => titleCase(row.journal.decision));
  const setupRows = replayOutcomeSummaryRows(
    reviewed,
    (row) => `${row.card.setup} / Grade ${text(row.card.quality_grade, "--")}`,
  );
  $("replay-score-decisions").innerHTML = renderReplayOutcomeRows(
    decisionRows,
    "No compared Take, Skip, or Watch decisions yet.",
  );
  $("replay-score-setups").innerHTML = renderReplayOutcomeRows(
    setupRows,
    "No compared setup outcomes yet.",
  );
  $("replay-score-exits").innerHTML = practiceExits.length
    ? practiceExits
        .slice(-5)
        .reverse()
        .map(
          (row) => `
            <div class="replay-score-row">
              <div>
                <strong>${escapeHtml(`${row.card.symbol} / ${row.card.setup}`)}</strong>
                <span>Practice ${escapeHtml(rValue(row.practice_r))} vs strategy ${escapeHtml(rValue(row.outcome_r))}</span>
              </div>
              <strong class="${row.delta_r >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(row.delta_r))}</strong>
            </div>
          `,
        )
        .join("")
    : '<p class="paper-empty">Record a practice exit and compare the historical result to measure management difference.</p>';
}

function updateReplayJournalSummary() {
  const entries = allReplayCards.map((card) => replayJournalEntry(card));
  const decided = entries.filter((entry) => entry.decision);
  const reviewed = entries.filter((entry) => entry.outcome_reviewed);
  const decisionCount = (decision) => decided.filter((entry) => entry.decision === decision).length;
  $("replay-journal-message").textContent =
    `${reviewed.length} outcome${reviewed.length === 1 ? "" : "s"} reviewed from ${allReplayCards.length} saved historical cards. Decisions stay local to this browser.`;
  $("replay-journal-counts").innerHTML = [
    ["Decided", decided.length],
    ["Take", decisionCount("take")],
    ["Skip", decisionCount("skip")],
    ["Watch", decisionCount("watch")],
  ]
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${value}</strong></div>`)
    .join("");
  renderReplayScoring();
}

function saveCurrentReplayNote(showStatus = false) {
  const card = replayCards[replayIndex];
  if (!card) return false;
  const entry = replayJournalEntry(card);
  entry.notes = $("replay-notes").value.trim();
  entry.note_saved_at = new Date().toISOString();
  replayJournal[replayCardKey(card)] = entry;
  const saved = saveReplayJournal();
  if (showStatus) {
    $("replay-save-status").textContent = saved
      ? "Journal note saved locally in this browser."
      : "Note available for this page only; browser storage is unavailable.";
  }
  return saved;
}

function resetReplaySession() {
  replayOutcomeRevealed = false;
  replayManagementStep = null;
  replayLatestChart = null;
  replayPracticeFinished = false;
}

function recordManagementAction(action, extra = {}) {
  const card = replayCards[replayIndex];
  if (!card) return;
  const entry = replayJournalEntry(card);
  const actions = Array.isArray(entry.management_actions) ? entry.management_actions : [];
  actions.push({
    action,
    step: replayManagementStep,
    recorded_at: new Date().toISOString(),
    ...extra,
  });
  entry.management_actions = actions;
  replayJournal[replayCardKey(card)] = entry;
  saveReplayJournal();
}

function replayStopReached(card, chart) {
  if (!chart?.management_active || !chart.step || !chart.candles?.length) return false;
  const candle = chart.candles[chart.candles.length - 1];
  return card.direction === "long"
    ? Number(candle.low) <= Number(card.stop)
    : Number(candle.high) >= Number(card.stop);
}

function renderReplayManagement(card, journal) {
  const chart = replayLatestChart;
  const active = replayManagementStep !== null;
  const ready = Boolean(active && chart?.management_active && chart.step === replayManagementStep);
  const hasVisibleBar = ready && chart.step > 0;
  const completed = Boolean(ready && chart.management_complete);
  const canCompare = replayPracticeFinished || completed;
  const stopReached = replayStopReached(card, chart);

  if (replayOutcomeRevealed) {
    $("replay-management-prompt").textContent =
      "Historical comparison revealed. Review your stored management actions and notes.";
  } else if (!journal.decision) {
    $("replay-management-prompt").textContent =
      "Record a Take, Skip, or Watch decision before starting candle management.";
  } else if (!active) {
    $("replay-management-prompt").textContent =
      "Start management to switch into saved exit-management candles without revealing the recorded outcome.";
  } else if (replayPracticeFinished) {
    $("replay-management-prompt").textContent =
      "Practice exit recorded. Compare it with the historical strategy outcome when ready.";
  } else if (completed) {
    $("replay-management-prompt").textContent =
      "You reached the historical exit candle. Compare with the recorded strategy outcome when ready.";
  } else {
    $("replay-management-prompt").textContent =
      "Only currently visible candles are available. Decide whether to hold or exit before advancing.";
  }

  $("replay-visible-step").textContent = ready
    ? chart.management_complete
      ? `${chart.step} / complete`
      : String(chart.step)
    : active
      ? "Loading..."
      : "Not started";
  $("replay-current-price").textContent = hasVisibleBar ? dollarValue(chart.current_price) : "Hidden";
  $("replay-current-r").textContent = hasVisibleBar ? rValue(chart.current_r) : "Hidden";

  $("replay-start-management").textContent = replayOutcomeRevealed
    ? "Outcome already compared"
    : active
      ? "Management started"
      : journal.decision
        ? "Start management"
        : "Choose Take / Skip / Watch first";
  $("replay-start-management").disabled = replayOutcomeRevealed || !journal.decision || active;
  $("replay-hold").disabled = replayOutcomeRevealed || !ready || completed || replayPracticeFinished;
  $("replay-exit-here").disabled = replayOutcomeRevealed || !hasVisibleBar || replayPracticeFinished;
  $("replay-stop-followed").disabled =
    replayOutcomeRevealed || !hasVisibleBar || replayPracticeFinished || !stopReached;
  $("replay-reveal").disabled = replayOutcomeRevealed || !canCompare;
  $("replay-reveal").textContent = replayOutcomeRevealed
    ? "Outcome compared"
    : canCompare
      ? "Compare with historical outcome"
      : active
        ? "Complete management first"
        : journal.decision
          ? "Use Start management above"
          : "Choose Take / Skip / Watch first";
}

function renderWorkflow(state) {
  const rows = [
    ["Scanner rows", state.scanner.rows],
    ["Refresh status", state.refresh_status?.status || "missing"],
    ["Refresh next action", state.refresh_status?.next_action || "Run python run_refresh_status.py"],
    ["Morning watchdog", state.morning_watchdog?.status || "missing"],
    ["Watchdog next action", state.morning_watchdog?.next_action || "Run python run_morning_watchdog.py"],
    ["Automation timeline", state.automation_timeline?.status || "missing"],
    ["Data reliability", state.data_reliability?.status || "unknown"],
    ["Reliability next action", state.data_reliability?.next_action || "Refresh data before paper review."],
    ["Recent automation errors", state.data_reliability?.possible_failure_count || 0],
    ["Post-scan action", state.post_scan_digest?.action || "missing"],
    ["Post-scan next action", state.post_scan_digest?.next_action || "Run python run_post_scan_digest.py"],
    ["Pre-market gate", state.premarket_verification?.status || "not_run"],
    ["Pre-market probe", state.premarket_verification?.probe_status || "not_run"],
    ["Current candidates", state.scanner.current_candidate_count],
    ["Eligible position sizes", state.position_sizing.eligible_size_count],
    ["Forward observations", state.forward_observations?.rows || 0],
    ["Allowed observations", state.forward_observations?.allowed_rows || 0],
    ["Watch-only observations", state.forward_observations?.blocked_rows || 0],
    ["Allowed completed paper trades", state.paper_progress.allowed_completed_trades],
    ["Trades until 30 gate", state.paper_progress.first_gate_remaining],
    ["Trades until 60 gate", state.paper_progress.strong_gate_remaining],
  ];

  $("workflow-table").innerHTML = rows
    .map(([label, value]) => `<tr><td>${escapeHtml(label)}${helpBubble(helpKey(label))}</td><td>${escapeHtml(text(value, "0"))}</td></tr>`)
    .join("");
}

function renderStrategyVault(state) {
  const vault = state.strategy_vault || {};
  const regime = vault.regime || {};
  const selector = vault.selector || {};
  const strategies = vault.strategies || [];
  const active = strategies.find((strategy) => strategy.decision === "active");
  const research = strategies.find((strategy) => strategy.decision === "research_priority");
  const selected = active || research || strategies[0] || {};
  const passRows = strategies.reduce((total, strategy) => total + Number(strategy.tightened_pass_rows || 0), 0);

  setText("strategy-vault-message", vault.next_action || "Run the strategy vault report to classify market regime and strategy routing.");
  setText("strategy-selector-paper", selector.paper_watch_strategy || active?.name || "No paper-watch strategy");
  setText(
    "strategy-selector-paper-detail",
    `Decision: ${titleCase(selector.paper_watch_decision || active?.decision || "missing")}.`,
  );
  setText("strategy-selector-research", selector.research_strategy || research?.name || "No research priority");
  setText(
    "strategy-selector-research-detail",
    selector.research_decision && selector.research_decision !== "none"
      ? `Research lane: ${titleCase(selector.research_decision)}.`
      : "No research strategy is prioritized right now.",
  );
  setText("strategy-selector-mode", titleCase(selector.mode || "missing"));
  setText("strategy-selector-action", selector.allowed_action || "Run the strategy vault report.");
  setText("strategy-selector-blocked-count", `${Number(selector.research_only_strategy_count || 0)} blocked`);
  setText(
    "strategy-selector-blocked",
    (selector.blocked_actions || ["Research strategies cannot be paper-traded until promoted."]).join(" "),
  );
  setText("strategy-vault-regime", titleCase(regime.market_regime || "missing"));
  setText(
    "strategy-vault-regime-detail",
    `${titleCase(regime.volatility_regime || "unknown")} / ${titleCase(regime.strategy_environment || "unknown")}`,
  );
  setText("strategy-vault-action", selected.name || "No strategy selected");
  setText("strategy-vault-action-detail", selected.action || vault.guardrail || "Research routing only.");
  setText("strategy-vault-evidence", `${passRows} pass row${passRows === 1 ? "" : "s"}`);
  setText("strategy-promotion-decision", titleCase(selected.paper_watch_decision || "not available"));
  setText(
    "strategy-promotion-detail",
    selected.paper_watch_decision === "paper_watch_eligible"
      ? "Eligible for manual paper-watch review only."
      : "Not ready for paper-watch review yet.",
  );
  setText("strategy-promotion-blocker", selected.paper_watch_blocker || "No blocker reported");
  setText(
    "strategy-promotion-blocker-detail",
    `${Number(selected.paper_watch_blocked_count || 0)} blocked check${Number(selected.paper_watch_blocked_count || 0) === 1 ? "" : "s"}.`,
  );
  setText(
    "strategy-promotion-shadow",
    `${Number(selected.matured_shadow_samples || 0)} / ${Number(selected.shadow_samples || 0)}`,
  );
  setText("strategy-promotion-shadow-detail", `${rValue(selected.shadow_average_r)} avg matured shadow R.`);
  setText(
    "strategy-promotion-forward",
    `${Number(selected.matured_forward_observations || 0)} / ${Number(selected.forward_observations || 0)}`,
  );
  setText("strategy-promotion-forward-detail", `${rValue(selected.forward_average_r)} avg matured forward R.`);
  setText(
    "strategy-vault-evidence-detail",
    selected.walk_forward_status
      ? `${titleCase(selected.walk_forward_status)} / ${selected.evidence_note || "Evidence appears after strategy-specific reports run."}`
      : selected.evidence_note || "Evidence appears after strategy-specific reports run.",
  );

  $("strategy-vault-table").innerHTML = strategies.length
    ? strategies
        .map(
          (strategy) => `
            <tr>
              <td>${escapeHtml(strategy.name || "")}</td>
              <td><span class="status ${safeClassName(strategy.decision || "watch")}">${escapeHtml(titleCase(strategy.decision || ""))}</span></td>
              <td>${escapeHtml(text(strategy.score, "0"))}</td>
              <td>${escapeHtml(strategy.evidence_status || "")}${strategy.best_symbols ? ` / ${escapeHtml(strategy.best_symbols)}` : ""}${strategy.walk_forward_status ? ` / WF: ${escapeHtml(titleCase(strategy.walk_forward_status))}` : ""}${Number(strategy.shadow_samples || 0) ? ` / Shadow: ${escapeHtml(strategy.matured_shadow_samples || 0)}/${escapeHtml(strategy.shadow_samples || 0)}` : ""}${Number(strategy.forward_observations || 0) ? ` / Forward: ${escapeHtml(strategy.matured_forward_observations || 0)}/${escapeHtml(strategy.forward_observations || 0)}` : ""}${strategy.paper_watch_decision ? ` / Gate: ${escapeHtml(titleCase(strategy.paper_watch_decision))}` : ""}</td>
              <td>${escapeHtml(strategy.action || "")}</td>
            </tr>
          `,
        )
        .join("")
    : '<tr><td colspan="5">No strategy vault rows available. Run python run_strategy_vault.py.</td></tr>';
}

function renderAppHealth(state) {
  const files = state.app_health?.source_file_states || {};
  const rows = [
    ["Generated", state.app_health?.generated_at_et],
    ["System state JSON", files.system_state_json?.modified_et || "not written yet"],
    ["Refresh status JSON", files.refresh_status_json?.modified_et || "missing"],
    ["Morning watchdog", files.morning_watchdog_json?.modified_et || "missing"],
    ["Automation timeline", files.automation_timeline_json?.modified_et || "missing"],
    ["Post-scan digest", files.post_scan_digest_json?.modified_et || "missing"],
    ["Pre-market verification", files.premarket_verification_json?.modified_et || "missing"],
    ["Dashboard report", files.dashboard_md?.modified_et || "missing"],
    ["Scanner CSV", files.scanner_csv?.modified_et || "missing"],
    ["Observations CSV", files.forward_observations_csv?.modified_et || "missing"],
    ["Near-miss observations", files.near_miss_csv?.modified_et || "no open-session rows yet"],
    ["Near-miss report", files.near_miss_md?.modified_et || "missing"],
    ["Observation Results", files.forward_results_csv?.modified_et || "missing"],
    ["Integrity Report", files.integrity_csv?.modified_et || "missing"],
    ["Refresh Audit", files.refresh_audit_csv?.modified_et || "missing"],
    ["Position sizing CSV", files.sizing_csv?.modified_et || "missing"],
    ["Setup health CSV", files.setup_health_csv?.modified_et || "missing"],
    ["Strategy vault", files.strategy_vault_json?.modified_et || "not run yet"],
    ["Strategy evidence accumulator", files.strategy_evidence_accumulator_json?.modified_et || "not run yet"],
    ["VWAP mean reversion", files.vwap_mean_reversion_json?.modified_et || "not run yet"],
    ["VWAP mean reversion walk-forward", files.vwap_mean_reversion_walk_forward_json?.modified_et || "not run yet"],
    ["VWAP mean reversion shadow", files.vwap_mean_reversion_shadow_outcomes_csv?.modified_et || "not run yet"],
    ["VWAP mean reversion forward observations", files.vwap_mean_reversion_forward_observation_results_csv?.modified_et || "not run yet"],
    ["VWAP mean reversion paper-watch gate", files.vwap_mean_reversion_paper_watch_gate_json?.modified_et || "not run yet"],
    ["Opening range failure", files.opening_range_failure_json?.modified_et || "not run yet"],
    ["Research confidence", files.research_confidence_csv?.modified_et || "not run yet"],
    ["Promotion review", files.promotion_review_csv?.modified_et || "not run yet"],
    ["Paper log", files.paper_csv?.modified_et || "missing"],
  ];

  $("app-health-table").innerHTML = rows
    .map(([label, value]) => `<tr><td>${escapeHtml(label)}${helpBubble(helpKey(label))}</td><td>${escapeHtml(text(value))}</td></tr>`)
    .join("");
}

function renderBadges(state) {
  const refresh = state.refresh_status || {};
  const premarket = state.premarket_verification || {};
  const badges = [
    {
      label: `Data: ${titleCase(state.data_freshness.data_status)}`,
      level: state.data_freshness.data_status === "fresh_for_today" ? "good" : "bad",
    },
    {
      label: `Market: ${titleCase(refresh.market?.market_status || state.market.today_status)}`,
      level: refresh.market?.market_is_open ? "good" : "warn",
    },
    {
      label: `Paper Gate: ${state.paper_progress.allowed_completed_trades}/30`,
      level: state.paper_progress.allowed_completed_trades >= 30 ? "good" : "warn",
    },
    {
      label: `Setup Attention: ${state.setup_health.attention_count}`,
      level: state.setup_health.attention_count > 0 ? "warn" : "good",
    },
    {
      label: `Paper Import: ${refresh.paper_import_blocked === false ? "Review First" : "Blocked"}`,
      level: refresh.paper_import_blocked === false ? "warn" : "bad",
    },
    {
      label: `Pre-Market: ${titleCase(premarket.status || "not_run")}`,
      level: premarket.status === "passed" ? "good" : premarket.status === "failed" ? "bad" : "warn",
    },
  ];

  $("warning-badges").innerHTML = badges
    .map((badge) => `<span class="badge ${safeClassName(badge.level)}">${escapeHtml(badge.label)}</span>`)
    .join("");
}

function renderGuardrails(state) {
  const safety = state.safety;
  const items = [
    `Live trading enabled: ${safety.live_trading_enabled}`,
    `Broker order execution enabled: ${safety.broker_order_execution_enabled}`,
    `Real-money ready: ${safety.real_money_ready}`,
    `Project phase: ${titleCase(state.project_phase)}`,
    `Data status: ${titleCase(state.data_freshness.data_status)}`,
  ];

  $("guardrails").innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function dollarValue(value) {
  if (value === undefined || value === null || value === "") return "--";
  return `$${Number(value).toFixed(2)}`;
}

function signedValue(value, digits = 2) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function tradingChartSvg(candles, signalMarkers = [], planLevels = []) {
  if (!candles?.length) {
    return '<div class="terminal-empty">No saved candles are available for this chart.</div>';
  }

  const width = 920;
  const height = 405;
  const left = 16;
  const right = 62;
  const top = 14;
  const priceBottom = 305;
  const volumeTop = 328;
  const volumeBottom = 380;
  const plotWidth = width - left - right;
  const indicatorKeys = ["vwap", "ema_9", "ema_21", "ema_200"];
  const priceValues = [];
  candles.forEach((candle) => {
    priceValues.push(Number(candle.low), Number(candle.high));
    indicatorKeys.forEach((key) => {
      if (candle[key] !== null) priceValues.push(Number(candle[key]));
    });
  });
  planLevels.forEach((level) => {
    if (level.value !== null) priceValues.push(Number(level.value));
  });
  const rawMin = Math.min(...priceValues);
  const rawMax = Math.max(...priceValues);
  const padding = Math.max((rawMax - rawMin) * 0.06, rawMax * 0.0004);
  const low = rawMin - padding;
  const high = rawMax + padding;
  const range = Math.max(high - low, 0.01);
  const maxVolume = Math.max(...candles.map((candle) => Number(candle.volume)), 1);
  const step = plotWidth / candles.length;
  const bodyWidth = Math.max(Math.min(step * 0.68, 9), 2);
  const x = (index) => left + step * index + step / 2;
  const y = (value) => top + ((high - Number(value)) / range) * (priceBottom - top);
  const volumeY = (volume) => volumeBottom - (Number(volume) / maxVolume) * (volumeBottom - volumeTop);

  const grid = Array.from({ length: 5 }, (_, index) => {
    const value = high - (range / 4) * index;
    const lineY = y(value);
    return `
      <line class="price-grid" x1="${left}" y1="${lineY}" x2="${width - right}" y2="${lineY}"></line>
      <text class="price-axis" x="${width - right + 7}" y="${lineY + 4}">${value.toFixed(2)}</text>
    `;
  }).join("");

  const volumeBars = candles
    .map((candle, index) => {
      const className = Number(candle.close) >= Number(candle.open) ? "volume-up" : "volume-down";
      const barTop = volumeY(candle.volume);
      return `<rect class="${className}" x="${x(index) - bodyWidth / 2}" y="${barTop}" width="${bodyWidth}" height="${volumeBottom - barTop}"></rect>`;
    })
    .join("");

  const candleBars = candles
    .map((candle, index) => {
      const className = Number(candle.close) >= Number(candle.open) ? "candle-up" : "candle-down";
      const bodyTop = Math.min(y(candle.open), y(candle.close));
      const bodyHeight = Math.max(Math.abs(y(candle.open) - y(candle.close)), 1.5);
      return `
        <line class="${className}" x1="${x(index)}" y1="${y(candle.high)}" x2="${x(index)}" y2="${y(candle.low)}"></line>
        <rect class="${className}" x="${x(index) - bodyWidth / 2}" y="${bodyTop}" width="${bodyWidth}" height="${bodyHeight}"></rect>
      `;
    })
    .join("");

  const indicator = (key, className) => {
    const points = candles
      .map((candle, index) => (candle[key] === null ? "" : `${x(index)},${y(candle[key])}`))
      .filter(Boolean)
      .join(" ");
    return points ? `<polyline class="indicator-line ${className}" points="${points}"></polyline>` : "";
  };

  const last = candles[candles.length - 1];
  const sessionStartIndex = Math.max(
    candles.findIndex((candle) => candle.session_date === last.session_date),
    0,
  );
  const sessionLineStart = x(sessionStartIndex) - step / 2;
  const rangeLines = ["opening_range_high", "opening_range_low"]
    .filter((key) => last[key] !== null)
    .map(
      (key) =>
        `<line class="opening-range-line" x1="${sessionLineStart}" y1="${y(last[key])}" x2="${width - right}" y2="${y(last[key])}"></line>`,
    )
    .join("");
  const levelLines = planLevels
    .filter((level) => level.value !== null)
    .map(
      (level) => `
        <line class="replay-plan-line ${escapeHtml(level.kind)}" x1="${left}" y1="${y(level.value)}" x2="${width - right}" y2="${y(level.value)}"></line>
        <text class="replay-plan-label ${escapeHtml(level.kind)}" x="${width - right - 5}" y="${y(level.value) - 4}" text-anchor="end">${escapeHtml(level.label)}</text>
      `,
    )
    .join("");

  const labelIndexes = Array.from(new Set([0, Math.floor((candles.length - 1) / 2), candles.length - 1]));
  const timeLabels = labelIndexes
    .map(
      (index) =>
        `<text class="price-axis" x="${x(index)}" y="${height - 7}" text-anchor="${index === 0 ? "start" : index === candles.length - 1 ? "end" : "middle"}">${escapeHtml(candles[index].time_et)}</text>`,
    )
    .join("");
  const markers = signalMarkers
    .map((marker) => {
      const index = candles.findIndex((candle) => candle.time_et === marker.time_et);
      if (index < 0) return "";
      const markerY = Math.max(y(candles[index].high) - 17, top + 9);
      const className = marker.kind || (marker.scanner_status === "allowed" ? "allowed" : "watch");
      return `
        <line class="signal-marker-guide ${className}" x1="${x(index)}" y1="${markerY + 8}" x2="${x(index)}" y2="${y(candles[index].high) - 2}"></line>
        <circle class="signal-marker ${className}" cx="${x(index)}" cy="${markerY}" r="9"></circle>
        <text class="signal-marker-label" x="${x(index)}" y="${markerY + 4}">${escapeHtml(marker.label)}</text>
      `;
    })
    .join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Saved Webull candle chart with strategy indicators">
      ${grid}
      ${rangeLines}
      ${levelLines}
      ${volumeBars}
      ${candleBars}
      ${indicator("vwap", "line-vwap")}
      ${indicator("ema_9", "line-ema9")}
      ${indicator("ema_21", "line-ema21")}
      ${indicator("ema_200", "line-ema200")}
      ${markers}
      ${timeLabels}
    </svg>
  `;
}

function renderTerminalTicket(state, chart) {
  const matchingCard = (state.current_candidates?.cards || []).find((card) => card.symbol === chart.symbol);
  $("ticket-setups").textContent = chart.approved_setups.join(" / ") || "No approved setup for this symbol.";

  if (!matchingCard) {
    $("ticket-title").textContent = `${chart.symbol} / No Current Signal`;
    setStatusPill($("ticket-status"), "review_only");
    setText("ticket-entry", "--");
    setText("ticket-stop", "--");
    setText("ticket-target", "--");
    setText("ticket-shares", "--");
    $("ticket-message").textContent =
      "No current-candle candidate is available for the selected symbol. The chart remains available for review.";
    return;
  }

  $("ticket-title").textContent = `${matchingCard.symbol} ${matchingCard.setup}`;
  setStatusPill($("ticket-status"), matchingCard.ready_for_review ? "ready_for_review" : "not_ready");
  setText("ticket-entry", dollarValue(matchingCard.entry));
  setText("ticket-stop", dollarValue(matchingCard.stop));
  setText("ticket-target", dollarValue(matchingCard.target));
  setText("ticket-shares", matchingCard.suggested_shares || "--");
  $("ticket-message").textContent = matchingCard.ready_for_review
    ? "Current signal is ready for manual paper review. Orders remain disabled."
    : matchingCard.blockers?.join(" ") || "Signal exists but is not eligible for review.";
}

function meaningfulValue(value) {
  return value !== undefined && value !== null && String(value).trim() !== "" && String(value).trim() !== "--";
}

function candidateKey(card) {
  if (!card) return "";
  return [card.symbol, card.setup, card.direction, card.signal_time_et].map((part) => text(part, "")).join("|");
}

function renderPreEntryChecklist(state, chart, chartFreshness) {
  const card = (state.current_candidates?.cards || []).find((candidate) => candidate.symbol === chart.symbol);
  const dataFresh = state.data_freshness?.data_status === "fresh_for_today";
  const candleFresh = chartFreshness?.status === "fresh";
  const entryChart = chart.timeframe === "M30";
  const scannerAllowed = card?.scanner_status === "allowed";
  const sizingOk = card?.sizing_status === "size_ok";
  const importAllowed = (card?.checklist_flags || []).some(
    (flag) => flag.label === "Paper import review available" && flag.passed,
  );
  const planComplete = card && ["entry", "stop", "target"].every((field) => meaningfulValue(card[field]));
  const sharesReady = card && Number(card.suggested_shares || 0) > 0;
  const riskGuard = state.risk_guard || {};
  const riskGuardKnown = Boolean(riskGuard.status);

  const checks = [
    ["Data fresh", dataFresh, state.data_freshness?.action || "Refresh Webull data before review."],
    ["30m entry chart selected", entryChart, "Use the 30m chart for entry structure before paper preview."],
    ["Candle age fresh", candleFresh, chartFreshness?.message || "Refresh saved candles before review."],
    ["Current-candle candidate", Boolean(card), "No current-candle candidate exists for this symbol."],
    ["Scanner allowed", scannerAllowed, card?.blockers?.join(" ") || "Scanner has not allowed this setup."],
    ["Sizing size_ok", sizingOk, "Position sizing is not ready for local paper entry."],
    ["Paper gate unblocked", importAllowed, "Paper import gate is still blocked."],
    ["Entry, stop, target present", Boolean(planComplete), "The paper plan is incomplete."],
    ["Shares calculated", Boolean(sharesReady), "Suggested paper shares are missing or zero."],
    ["Risk guard visible", riskGuardKnown, riskGuard.message || "Risk guard state is missing."],
  ];
  const systemReady = checks.every(([, passed]) => Boolean(passed));
  activePreEntryKey = candidateKey(card);
  const reviewed = activePreEntryKey && preEntryReviewedKeys.has(activePreEntryKey);
  const previewReady = systemReady && reviewed;

  $("pre-entry-title").textContent = card
    ? previewReady
      ? "Preview ready"
      : systemReady
        ? "Manual review needed"
        : "Blocked"
    : "No candidate";
  $("pre-entry-title").className = previewReady ? "healthy-text" : systemReady ? "watch-text" : "caution-text";
  $("pre-entry-list").innerHTML = checks
    .map(
      ([label, passed, detail]) => `
        <li class="${passed ? "pass" : "hold"}">
          <strong>${passed ? "Pass" : "Hold"}: ${escapeHtml(label)}</strong>
          <span>${escapeHtml(detail)}</span>
        </li>
      `,
    )
    .join("");

  const reviewedBox = $("pre-entry-reviewed");
  reviewedBox.checked = Boolean(reviewed);
  reviewedBox.disabled = !systemReady || !activePreEntryKey;
  $("ticket-paper-preview").disabled = !previewReady;
  $("pre-entry-message").textContent = previewReady
    ? "All checks passed. Run preview, then confirm local paper entry only if the preview matches your plan."
    : systemReady
      ? "System checks passed. Tick manual review after checking the chart and risk."
      : card
        ? "Do not run paper preview yet. Resolve the hold items first."
        : "No ready current-candle candidate for this symbol.";
  hydrateHelpBubbles($("pre-entry-list"));
}

function renderTerminalFocus(chart) {
  const note = $("terminal-focus-note");
  if (!terminalFocus || terminalFocus.symbol !== chart.symbol) {
    note.hidden = true;
    note.textContent = "";
    return;
  }
  note.hidden = false;
  note.textContent = `From Sample Queue: ${terminalFocus.symbol} ${terminalFocus.setup} ${titleCase(terminalFocus.direction)} / ${titleCase(terminalFocus.queue_status)}. ${terminalFocus.next_action}`;
}

function renderTerminalSymbols(chart) {
  $("terminal-symbols").innerHTML = chart.available_symbols
    .map(
      (entry) => `
        <button type="button" class="terminal-symbol ${entry.symbol === terminalSymbol ? "active" : ""}" data-symbol="${escapeHtml(entry.symbol)}">
          <strong>${escapeHtml(entry.symbol)}</strong>
          <span>${escapeHtml(entry.setups.map((setup) => setup.replace("Setup ", "")).join(" / "))}</span>
        </button>
      `,
    )
    .join("");

  for (const button of document.querySelectorAll(".terminal-symbol")) {
    button.addEventListener("click", () => {
      terminalFocus = null;
      terminalSymbol = button.dataset.symbol;
      loadTradingWorkspace();
    });
  }
}

function renderTerminalTimeframes(chart) {
  const timeframes = chart.available_timeframes?.length
    ? chart.available_timeframes
    : [
        { timeframe: "M5", label: "5m", exists: true, role: "signal" },
        { timeframe: "M30", label: "30m", exists: true, role: "signal" },
      ];
  $("terminal-timeframes").innerHTML = timeframes
    .map(
      (entry) => `
        <button
          type="button"
          data-timeframe="${escapeHtml(entry.timeframe)}"
          class="${entry.timeframe === chart.timeframe ? "active" : ""}"
          ${entry.exists ? "" : "disabled"}
          title="${entry.role === "signal" ? "Strategy signal timeframe" : "Chart-only review timeframe"}"
        >
          ${escapeHtml(entry.label)}
        </button>
      `,
    )
    .join("");

  for (const button of document.querySelectorAll("#terminal-timeframes button")) {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      terminalTimeframe = button.dataset.timeframe;
      loadTradingWorkspace();
    });
  }
}

function metricValue(value, suffix = "") {
  if (value === undefined || value === null || value === "") return "--";
  return `${Number(value).toFixed(2)}${suffix}`;
}

function renderSetupReadiness(readiness) {
  $("readiness-symbol").textContent = readiness.symbol;
  $("readiness-message").textContent = readiness.message;
  $("readiness-guardrail").textContent = readiness.guardrail;
  if (!readiness.setups?.length) {
    $("readiness-cards").innerHTML = '<div class="radar-empty">No scanner setup state is available for this symbol yet.</div>';
    return;
  }
  $("readiness-cards").innerHTML = readiness.setups
    .map(
      (setup) => `
        <article class="readiness-card">
          <header>
            <div>
              <h5>${escapeHtml(setup.setup)}</h5>
              <p>${escapeHtml(titleCase(setup.direction))}${setup.latest_signal_et ? ` / Signal ${escapeHtml(setup.latest_signal_et.slice(11))} ET` : ""}</p>
            </div>
            <span class="status ${escapeHtml(setup.status_tone)}">${escapeHtml(setup.status_label)}</span>
          </header>
          <div class="readiness-stats">
            <div><span>Checks${helpBubble("checks")}</span><strong>${escapeHtml(setup.passed_condition_count)} / ${escapeHtml(setup.condition_count)}</strong></div>
            <div><span>Quality${helpBubble("quality")}</span><strong>${escapeHtml(setup.quality_grade || "--")} ${escapeHtml(setup.quality_score ?? "--")}</strong></div>
            <div><span>Rel Vol${helpBubble("rel-vol")}</span><strong>${escapeHtml(metricValue(setup.relative_volume, "x"))}</strong></div>
            <div><span>Room${helpBubble("room-r")}</span><strong>${escapeHtml(metricValue(setup.room_to_target_r, "R"))}</strong></div>
          </div>
          <div class="readiness-checks">
            <div>
              <p class="eyebrow">Passed Now</p>
              <ul class="radar-pass">
                ${(setup.passed_conditions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>Pending scanner detail.</li>"}
              </ul>
            </div>
            <div>
              <p class="eyebrow">Missing Now</p>
              <ul class="radar-missing">
                ${(setup.missing_conditions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>None on the latest scanner candle.</li>"}
              </ul>
            </div>
          </div>
        </article>
      `,
    )
    .join("");
  hydrateHelpBubbles($("readiness-cards"));
}

async function loadTradingWorkspace() {
  const requestId = ++terminalRequestId;
  $("terminal-chart").innerHTML = '<div class="terminal-empty">Loading latest saved chart data...</div>';
  try {
    const response = await fetch(
      `${tradingWorkspaceUrl}?symbol=${encodeURIComponent(terminalSymbol)}&timeframe=${encodeURIComponent(terminalTimeframe)}`,
      { cache: "no-store" },
    );
    const chart = await response.json();
    if (!response.ok) throw new Error(chart.error || `Chart request failed: ${response.status}`);
    if (requestId !== terminalRequestId) return;

    renderTerminalSymbols(chart);
    renderTerminalTimeframes(chart);
    $("terminal-source").textContent = `${chart.source} / Session ${chart.latest_session}`;
    $("terminal-chart-symbol").textContent = chart.symbol;
    $("terminal-price").textContent = dollarValue(chart.last_price);
    const positive = Number(chart.day_change) >= 0;
    $("terminal-change").className = `terminal-change ${positive ? "positive" : "negative"}`;
    $("terminal-change").textContent = `${signedValue(chart.day_change)} (${signedValue(chart.day_change_pct)}%) vs prior session close`;
    let readiness = { signal_markers: [], setups: [], symbol: chart.symbol };
    try {
      const readinessResponse = await fetch(
        `${setupReadinessUrl}?symbol=${encodeURIComponent(chart.symbol)}`,
        { cache: "no-store" },
      );
      readiness = await readinessResponse.json();
      if (!readinessResponse.ok) {
        throw new Error(readiness.error || `Readiness request failed: ${readinessResponse.status}`);
      }
      if (requestId !== terminalRequestId) return;
      renderSetupReadiness(readiness);
    } catch (readinessError) {
      if (requestId !== terminalRequestId) return;
      $("readiness-symbol").textContent = chart.symbol;
      $("readiness-message").textContent = readinessError.message;
      $("readiness-cards").innerHTML = '<div class="radar-empty">Setup readiness is unavailable.</div>';
    }
    if (requestId !== terminalRequestId) return;
    $("terminal-expand-chart").href = `/chart.html?symbol=${encodeURIComponent(chart.symbol)}&timeframe=${encodeURIComponent(chart.timeframe)}`;
    $("terminal-chart").innerHTML = tradingChartSvg(chart.candles, readiness.signal_markers);
    $("terminal-chart-time").textContent =
      `${chart.timeframe_role || "Chart timeframe"}. Latest stored bar: ${chart.latest_bar_et} (${chart.data_lag_minutes ?? "--"} min behind now). Data updates when the Webull market-data workflow is run.`;
    const chartFreshness = chartFreshnessState(chart, currentState || {});
    $("terminal-freshness-warning").className = `terminal-freshness-warning ${chartFreshness.tone}`;
    $("terminal-freshness-warning").textContent = chartFreshness.message;
    renderTerminalTicket(currentState || { current_candidates: { cards: [] } }, chart);
    renderPreEntryChecklist(currentState || { current_candidates: { cards: [] } }, chart, chartFreshness);
    renderTerminalFocus(chart);
    loadInvestmentNarrative(chart.symbol);
    hydrateHelpBubbles($("trading-workspace"));
  } catch (error) {
    $("terminal-chart").innerHTML = `<div class="terminal-empty">${escapeHtml(error.message)}</div>`;
    $("terminal-chart-time").textContent = "Run a market-data refresh to populate this read-only chart.";
    $("terminal-freshness-warning").className = "terminal-freshness-warning caution";
    $("terminal-freshness-warning").textContent = "Candle freshness cannot be checked until chart data loads.";
    $("terminal-focus-note").hidden = true;
    renderPreEntryChecklist(currentState || { current_candidates: { cards: [] } }, { symbol: terminalSymbol, timeframe: terminalTimeframe }, { status: "unknown", message: error.message });
  }
}

function renderInvestmentNarrative(narrative) {
  $("narrative-symbol").textContent = narrative.symbol;
  $("narrative-asset-type").textContent = `/ ${narrative.asset_type}`;
  $("narrative-scope").textContent = narrative.scope;
  $("narrative-source-status").className = "status watch";
  $("narrative-source-status").textContent = narrative.source_status_label;
  $("narrative-summary-text").textContent = narrative.summary;
  $("narrative-thesis-focus").textContent = narrative.thesis_focus;
  $("narrative-guardrail").textContent = narrative.guardrail;

  $("narrative-themes").innerHTML = narrative.monitoring_themes
    .map(
      (theme) => `
        <div class="narrative-theme">
          <strong>${escapeHtml(theme.label)}</strong>
          <p>${escapeHtml(theme.detail)}</p>
        </div>
      `,
    )
    .join("");
  $("narrative-sources").innerHTML = narrative.source_slots
    .map(
      (source) => `
        <div class="narrative-source">
          <header><strong>${escapeHtml(source.label)}</strong><span>${escapeHtml(source.status)}</span></header>
          <p>${escapeHtml(source.detail)}</p>
        </div>
      `,
    )
    .join("");
  $("narrative-questions").innerHTML = narrative.review_questions
    .map((question) => `<li>${escapeHtml(question)}</li>`)
    .join("");
}

function renderNearMissAnalytics(analytics) {
  $("near-miss-basis").className = "status review_only";
  $("near-miss-basis").textContent = analytics.basis_label;
  $("near-miss-message").textContent = analytics.message;
  $("near-miss-count").textContent = `${analytics.observed_rows || analytics.snapshot_blocker_rows || 0} blockers`;
  $("near-miss-guardrail").textContent = analytics.guardrail;
  const missedSummary = analytics.missed_summary || {};
  $("near-miss-missed-count").textContent = `${missedSummary.later_allowed_matured || 0} matured`;

  const peak = Math.max(...(analytics.top_blockers || []).map((blocker) => Number(blocker.occurrences)), 1);
  $("near-miss-blockers").innerHTML = analytics.top_blockers?.length
    ? analytics.top_blockers
        .map(
          (blocker) => `
            <div class="blocker-row">
              <div><strong>${escapeHtml(titleCase(blocker.missing_condition))}</strong><span>${escapeHtml(blocker.occurrences)} occurrence(s)</span></div>
              <div class="blocker-track"><span style="width: ${(Number(blocker.occurrences) / peak) * 100}%"></span></div>
            </div>
          `,
        )
        .join("")
    : '<p class="radar-empty">No missing scanner conditions available yet.</p>';

  $("near-miss-closest").innerHTML = analytics.closest_setups?.length
    ? analytics.closest_setups
        .map(
          (setup) => `
            <div class="closest-row">
              <div>
                <strong>${escapeHtml(setup.symbol)} ${escapeHtml(setup.setup)}</strong>
                <span>${escapeHtml(titleCase(setup.direction))} / Missing: ${escapeHtml(setup.missing_conditions.join(", "))}</span>
              </div>
              <b>${escapeHtml(setup.passed_condition_count)} / ${escapeHtml(setup.condition_count)}</b>
            </div>
          `,
        )
        .join("")
    : '<p class="radar-empty">No near-miss setup rows available yet.</p>';

  $("near-miss-missed").innerHTML = analytics.missed_opportunities?.length
    ? analytics.missed_opportunities
        .map(
          (row) => `
            <div class="closest-row">
              <div>
                <strong>${escapeHtml(row.symbol)} ${escapeHtml(row.setup)}</strong>
                <span>${escapeHtml(titleCase(row.direction))} / ${escapeHtml(titleCase(row.resolution))}</span>
                <span>Near miss: ${escapeHtml(row.near_miss_time_et || "--")} / Later signal: ${escapeHtml(row.later_signal_time_et || "--")}</span>
                <span>Missing: ${escapeHtml((row.missing_conditions || []).join(", ") || "None listed")}</span>
                <span>${escapeHtml(row.result_note || "")}</span>
              </div>
              <b>${row.hypothetical_r === "" ? "--" : escapeHtml(rValue(row.hypothetical_r))}</b>
            </div>
          `,
        )
        .join("")
    : '<p class="radar-empty">No almost-ready rows have resolved into later allowed observations yet.</p>';
}

async function loadNearMissAnalytics() {
  try {
    const response = await fetch(nearMissAnalyticsUrl, { cache: "no-store" });
    const analytics = await response.json();
    if (!response.ok) throw new Error(analytics.error || `Near-miss request failed: ${response.status}`);
    renderNearMissAnalytics(analytics);
  } catch (error) {
    $("near-miss-basis").className = "status caution";
    $("near-miss-basis").textContent = "Unavailable";
    $("near-miss-message").textContent = error.message;
  }
}

async function loadInvestmentNarrative(symbol) {
  const requestId = ++narrativeRequestId;
  $("narrative-source-status").textContent = "Loading";
  try {
    const response = await fetch(
      `${investmentNarrativeUrl}?symbol=${encodeURIComponent(symbol)}`,
      { cache: "no-store" },
    );
    const narrative = await response.json();
    if (!response.ok) throw new Error(narrative.error || `Narrative request failed: ${response.status}`);
    if (requestId !== narrativeRequestId) return;
    renderInvestmentNarrative(narrative);
  } catch (error) {
    $("narrative-source-status").className = "status caution";
    $("narrative-source-status").textContent = "Unavailable";
    $("narrative-summary-text").textContent = error.message;
  }
}

function renderHealth(state) {
  const setups = state.setup_health.action_plan || state.setup_health.attention_setups || [];
  const container = $("health-list");

  if (!setups.length) {
    container.innerHTML = '<div class="health-card"><p>No setup health cautions right now.</p></div>';
    return;
  }

  container.innerHTML = setups
    .map(
      (setup) => `
        <article class="health-card">
          <header>
            <div>
              <h4>${escapeHtml(setup.symbol)} ${escapeHtml(setup.setup)}</h4>
              <div class="health-meta">${escapeHtml(setup.direction)} / ${escapeHtml(setup.trades)} trades</div>
            </div>
            <span class="status ${safeClassName(setup.health_status)}">${escapeHtml(titleCase(setup.health_status))}</span>
          </header>
          <dl>
            <div><dt>Score${helpBubble("quality")}</dt><dd>${escapeHtml(setup.health_score)}</dd></div>
            <div><dt>Exp R${helpBubble("exp-r")}</dt><dd>${escapeHtml(setup.expectancy_r)}</dd></div>
            <div><dt>PF${helpBubble("pf")}</dt><dd>${escapeHtml(setup.profit_factor)}</dd></div>
            <div><dt>Trades${helpBubble("trades")}</dt><dd>${escapeHtml(setup.trades)}</dd></div>
          </dl>
          <p>${escapeHtml(setup.flags)}</p>
          ${setup.action ? `<p class="health-action"><strong>Action:</strong> ${escapeHtml(setup.action)}</p>` : ""}
        </article>
      `,
    )
    .join("");
}

function renderCandidates(state) {
  const candidateState = state.current_candidates || { count: 0, ready_for_review_count: 0, cards: [] };
  const cards = candidateState.cards || [];
  const list = $("candidate-list");
  const dataFresh = state.data_freshness.data_status === "fresh_for_today";
  renderPaperWorkflowGuide(state);

  $("candidate-count").className = `status ${candidateState.ready_for_review_count > 0 ? "healthy" : "watch"}`;
  $("candidate-count").textContent = `${candidateState.count} current / ${candidateState.ready_for_review_count} reviewable`;

  if (!cards.length) {
    $("candidate-message").textContent = dataFresh
      ? "No current-candle candidates exist in the latest scanner output."
      : "No actionable current-candle candidates. Refresh Webull data during the next open market session before review.";
    list.innerHTML = '<article class="candidate-empty">No candidate cards to display.</article>';
    return;
  }

  $("candidate-message").textContent = dataFresh
    ? "Review-only display from the existing scanner and position sizing outputs. It cannot place trades."
    : "Candidate rows exist, but data is stale or prep-only. Do not import or size a paper trade from this view.";
  list.innerHTML = cards
    .map(
      (card) => `
        <article class="candidate-card">
          <header>
            <div>
              <h4>${escapeHtml(card.symbol)} ${escapeHtml(card.setup)}</h4>
              <p>${escapeHtml(titleCase(card.direction))} / Signal ${escapeHtml(card.signal_time_et)}</p>
            </div>
            <span class="status ${card.ready_for_review ? "healthy" : "watch"}">
              ${card.ready_for_review ? "Ready To Review" : "Not Ready"}
            </span>
          </header>
          <div class="candidate-prices">
            <div><span>Entry${helpBubble("entry")}</span><strong>${escapeHtml(card.entry)}</strong></div>
            <div><span>Stop${helpBubble("stop")}</span><strong>${escapeHtml(card.stop)}</strong></div>
            <div><span>Target${helpBubble("target")}</span><strong>${escapeHtml(card.target)}</strong></div>
            <div><span>Shares${helpBubble("shares")}</span><strong>${escapeHtml(card.suggested_shares || "Not sized")}</strong></div>
          </div>
          <p class="candidate-meta">
            Scanner: ${escapeHtml(titleCase(card.scanner_status))} /
            Sizing: ${escapeHtml(titleCase(card.sizing_status))} /
            Risk per share${helpBubble("risk-share")}: ${escapeHtml(card.risk_per_share)} /
            Est. paper risk${helpBubble("est-risk")}: ${escapeHtml(card.estimated_risk_dollars || "Not sized")} /
            Quality${helpBubble("quality")}: ${escapeHtml(card.quality_grade)} ${escapeHtml(card.quality_score)} /
            Rel Vol${helpBubble("rel-vol")}: ${escapeHtml(metricValue(card.relative_volume, "x"))} /
            Room${helpBubble("room-r")}: ${escapeHtml(metricValue(card.room_to_target_r, "R"))}
          </p>
          <div class="scale-guidance ${safeClassName(card.scale_tier || "no_scale")}">
            <div>
              <span>Scale Guidance${helpBubble("scale-tier")}</span>
              <strong>${escapeHtml(card.scale_label || "No Scale")}</strong>
            </div>
            <div>
              <span>Paper Risk</span>
              <strong>${escapeHtml(Number(card.suggested_risk_pct || 0).toFixed(2))}%</strong>
            </div>
            <div>
              <span>Option Premium Cap${helpBubble("premium-cap")}</span>
              <strong>${escapeHtml(Number(card.option_premium_cap_pct || 0).toFixed(2))}%</strong>
            </div>
            <p>${escapeHtml(card.scale_reason || "No scale guidance is available.")}</p>
          </div>
          <div class="evidence-priority ${safeClassName(card.evidence_priority || "standard_watch")}">
            <div>
              <span>Evidence Priority${helpBubble("evidence-priority")}</span>
              <strong>${escapeHtml(titleCase(card.evidence_priority || "standard watch"))}</strong>
            </div>
            <div>
              <span>Historical</span>
              <strong>${escapeHtml(Number(card.historical_trades || 0))} trades / ${escapeHtml(metricValue(card.historical_expectancy_r, "R"))}</strong>
            </div>
            <div>
              <span>Setup Health</span>
              <strong>${escapeHtml(titleCase(card.setup_health_status || "unknown"))}</strong>
            </div>
            <p>${escapeHtml(card.priority_reason || "Use standard paper-review caution.")}</p>
          </div>
          <ul class="candidate-checks">
            ${(card.checklist_flags || [])
              .map(
                (flag) =>
                  `<li class="${flag.passed ? "pass" : "hold"}">${flag.passed ? "Pass" : "Hold"}: ${escapeHtml(flag.label)}</li>`,
              )
              .join("")}
          </ul>
          ${
            card.blockers?.length
              ? `<p class="candidate-blockers">${card.blockers.map((blocker) => escapeHtml(blocker)).join(" ")}</p>`
              : ""
          }
          ${candidateWorkflowHtml(card, state)}
          <p class="candidate-notes">${escapeHtml(card.notes)}</p>
        </article>
      `,
    )
    .join("");
}

function renderSampleQueue(state) {
  const queue = state.forward_sample_queue || {};
  const summary = queue.summary || {};
  const rows = queue.rows || [];
  const ready = Number(summary.ready_for_review || 0);
  const blocked = Number(summary.blocked_current || 0);
  const almost = Number(summary.almost_ready || 0);
  const remaining = Number(summary.remaining_to_30 || 30);
  const status = $("sample-queue-status");
  const list = $("sample-queue-list");

  status.className = `status ${ready > 0 ? "healthy" : blocked > 0 || almost > 0 ? "watch" : "review_only"}`;
  status.textContent = ready > 0 ? "Ready" : blocked > 0 || almost > 0 ? "Watching" : "Waiting";
  setText("sample-ready-count", ready);
  setText("sample-blocked-count", blocked);
  setText("sample-almost-count", almost);
  setText("sample-to-30-count", remaining);
  $("sample-queue-message").textContent =
    queue.verdict || "No forward paper candidate is ready right now.";

  if (!rows.length) {
    list.innerHTML = '<article class="candidate-empty">No sample queue rows yet. Run the daily workflow after fresh data is available.</article>';
    return;
  }

  const visible = rows.filter((row) => ["ready_for_review", "blocked_current", "almost_ready"].includes(row.queue_status)).slice(0, 10);
  if (!visible.length) {
    list.innerHTML = '<article class="candidate-empty">No ready or near-ready rows in the latest scanner output.</article>';
    return;
  }

  list.innerHTML = visible
    .map((row) => {
      const tone = row.queue_status === "ready_for_review" ? "healthy" : row.queue_status === "blocked_current" ? "watch" : "review_only";
      const score = Number(row.check_score || 0) * 100;
      return `
        <article class="sample-queue-card">
          <header>
            <div>
              <h4>${escapeHtml(row.symbol)} ${escapeHtml(row.setup)}</h4>
              <p>${escapeHtml(titleCase(row.direction))} / ${escapeHtml(row.signal_time_et || row.latest_candle_et || "No signal time")}</p>
            </div>
            <span class="status ${tone}">${escapeHtml(titleCase(row.queue_status))}</span>
          </header>
          <div class="candidate-prices">
            <div><span>Checks${helpBubble("checks")}</span><strong>${escapeHtml(score.toFixed(0))}%</strong></div>
            <div><span>Quality${helpBubble("quality")}</span><strong>${escapeHtml(row.quality_grade || "--")} ${escapeHtml(row.quality_score || "")}</strong></div>
            <div><span>Rel Vol${helpBubble("rel-vol")}</span><strong>${escapeHtml(metricValue(row.relative_volume, "x"))}</strong></div>
            <div><span>Room${helpBubble("room-r")}</span><strong>${escapeHtml(metricValue(row.room_to_target_r, "R"))}</strong></div>
          </div>
          <p class="candidate-meta">
            Scanner: ${escapeHtml(titleCase(row.scanner_status))} /
            Freshness: ${escapeHtml(titleCase(row.signal_freshness || "not current"))} /
            Sizing: ${escapeHtml(titleCase(row.sizing_status || "missing"))} /
            Shares${helpBubble("shares")}: ${escapeHtml(row.shares || "Not sized")}
          </p>
          <p class="sample-next-action">${escapeHtml(row.next_action || "Wait for the next scan.")}</p>
          <div class="sample-queue-actions">
            <button
              type="button"
              class="secondary-button sample-chart-action"
              data-symbol="${escapeHtml(row.symbol)}"
              data-setup="${escapeHtml(row.setup)}"
              data-direction="${escapeHtml(row.direction)}"
              data-status="${escapeHtml(row.queue_status)}"
              data-next-action="${escapeHtml(row.next_action || "Review the saved chart context.")}"
            >
              Review 30m chart
            </button>
            <a href="/chart.html?symbol=${encodeURIComponent(row.symbol)}&timeframe=M30" target="_blank" rel="noopener" class="secondary-link">
              Expanded chart
            </a>
          </div>
          ${row.blockers ? `<p class="candidate-blockers">${escapeHtml(row.blockers)}</p>` : ""}
        </article>
      `;
    })
    .join("");
  for (const button of list.querySelectorAll(".sample-chart-action")) {
    button.addEventListener("click", () => {
      openSampleQueueChart({
        symbol: button.dataset.symbol,
        setup: button.dataset.setup,
        direction: button.dataset.direction,
        queue_status: button.dataset.status,
        next_action: button.dataset.nextAction,
      });
    });
  }
}

function renderAlmostReadyBreakout(state) {
  const breakout = state.almost_ready_breakout || {};
  const rows = breakout.rows || [];
  const status = $("almost-breakout-status");
  const list = $("almost-breakout-list");
  const message = $("almost-breakout-message");
  if (!status || !list || !message) return;

  status.className = `status ${rows.length ? "watch" : "review_only"}`;
  status.textContent = rows.length ? `${rows.length} Rows` : "Empty";
  message.textContent = rows.length
    ? "Use this to decide which near-ready blockers deserve strict enforcement versus shadow-only testing."
    : "No almost-ready breakout rows are available yet.";

  if (!rows.length) {
    list.innerHTML = '<article class="candidate-empty">No almost-ready rows to explain right now.</article>';
    return;
  }

  list.innerHTML = rows.slice(0, 6).map((row) => {
    const actionClass = safeClassName(row.action || "watch");
    return `
      <article class="almost-breakout-card ${actionClass}">
        <header>
          <div>
            <h4>${escapeHtml(row.symbol)} ${escapeHtml(row.setup)}</h4>
            <p>${escapeHtml(titleCase(row.direction))} / ${escapeHtml(row.check_score_pct || 0)}% checks / ${escapeHtml(row.quality || "--")}</p>
          </div>
          <span class="status ${actionClass}">${escapeHtml(titleCase(row.action || "watch"))}</span>
        </header>
        <div class="candidate-prices">
          <div><span>Shadow Avg</span><strong>${escapeHtml(metricValue(row.shadow_average_r, "R"))}</strong></div>
          <div><span>Shadow Samples</span><strong>${escapeHtml(row.shadow_samples || 0)}</strong></div>
          <div><span>Setup Health</span><strong>${escapeHtml(titleCase(row.setup_health || "unknown"))}</strong></div>
          <div><span>History Rows</span><strong>${escapeHtml(row.near_miss_rows || 0)}</strong></div>
        </div>
        <p class="candidate-meta">
          Blockers: ${escapeHtml(row.core_blockers || "None")}<br>
          Common history: ${escapeHtml(row.top_historical_blockers || "No blocker history yet.")}
        </p>
        <p class="sample-next-action">${escapeHtml(row.reason || "Keep collecting evidence.")}</p>
      </article>
    `;
  }).join("");
}

function openSampleQueueChart(row) {
  terminalFocus = row;
  terminalSymbol = row.symbol || terminalSymbol;
  terminalTimeframe = "M30";
  terminalInitialized = true;
  if (window.location.hash !== "#trading-workspace") {
    window.location.hash = "#trading-workspace";
  } else {
    updateAppRoute();
  }
  loadTradingWorkspace();
}

function syncTradeLoggerForm() {
  const rowNumber = Number($("trade-log-row").value || 0);
  const row = openPaperRows.find((item) => Number(item.row) === rowNumber);
  if (!row) return;

  $("trade-log-actual-entry").value = row.actual_entry || row.planned_entry || "";
  $("trade-log-actual-exit").value = row.actual_exit || "";
  $("trade-log-vehicle").value = row.vehicle || "options";
  $("trade-log-risk-tier").value = row.risk_tier || "standard";
  $("trade-log-premium").value = row.planned_option_premium || "";
  $("trade-log-shares").value = row.shares || "";
}

async function loadOpenPaperTrades() {
  const message = $("trade-logger-message");
  try {
    const response = await fetch(openPaperTradesUrl, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Open paper rows request failed: ${response.status}`);

    openPaperRows = payload.rows || [];
    monitorExitAlerts(openPaperRows);
    $("trade-logger-count").className = `status ${openPaperRows.length ? "watch" : "review_only"}`;
    $("trade-logger-count").textContent = `${openPaperRows.length} open`;
    $("trade-log-submit").disabled = openPaperRows.length === 0;
    $("trade-log-row").disabled = openPaperRows.length === 0;

    if (!openPaperRows.length) {
      message.textContent = "No open local paper rows need an outcome yet.";
      $("trade-log-row").innerHTML = '<option value="">No open rows</option>';
      return;
    }

    message.textContent = "Pick the row you manually closed, then save the underlying result and lightweight options fields.";
    $("trade-log-row").innerHTML = openPaperRows
      .map(
        (row) =>
          `<option value="${escapeHtml(row.row)}">#${escapeHtml(row.row)} ${escapeHtml(row.symbol)} ${escapeHtml(row.setup)} ${escapeHtml(row.entry_time_et)}</option>`,
      )
      .join("");
    syncTradeLoggerForm();
  } catch (error) {
    $("trade-logger-count").className = "status caution";
    $("trade-logger-count").textContent = "Unavailable";
    message.textContent = error.message;
  }
}

async function submitTradeLogger(event) {
  event.preventDefault();
  const message = $("trade-logger-message");
  const button = $("trade-log-submit");
  button.disabled = true;
  message.textContent = "Saving local paper outcome...";

  const payload = {
    row: $("trade-log-row").value,
    actual_entry: $("trade-log-actual-entry").value,
    actual_exit: $("trade-log-actual-exit").value,
    exit_time: $("trade-log-exit-time").value,
    vehicle: $("trade-log-vehicle").value,
    risk_tier: $("trade-log-risk-tier").value,
    planned_option_premium: $("trade-log-premium").value,
    shares: $("trade-log-shares").value,
    followed_plan: $("trade-log-followed-plan").value,
    exit_reason: $("trade-log-exit-reason").value,
    notes: $("trade-log-notes").value,
    append_notes: true,
  };

  try {
    const response = await fetch(updatePaperTradeActionUrl, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Paper-log update failed: ${response.status}`);

    renderState(result.state);
    message.textContent = result.message;
    $("trade-log-notes").value = "";
    await loadOpenPaperTrades();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = openPaperRows.length === 0;
  }
}

function rValue(value) {
  const number = Number(value || 0);
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toFixed(2)}R`;
}

function renderSummaryRows(rows, emptyText) {
  if (!rows?.length) {
    return `<p class="paper-empty">${escapeHtml(emptyText)}</p>`;
  }
  return rows
    .map(
      (row) => `
        <div class="paper-summary-row">
          <div>
            <strong>${escapeHtml(row.label === "blocked" ? "Watch Only" : titleCase(row.label))}</strong>
            <span>${escapeHtml(row.trades)} trades / ${escapeHtml((Number(row.win_rate) * 100).toFixed(1))}% wins</span>
          </div>
          <strong class="${Number(row.average_r) >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(row.average_r))} avg</strong>
        </div>
      `,
    )
    .join("");
}

function equityChart(points) {
  if (!points?.length) {
    return '<div class="paper-empty-chart">No completed forward paper trades yet.</div>';
  }

  const width = 620;
  const height = 210;
  const inset = 26;
  const values = [0, ...points.map((point) => Number(point.cumulative_r))];
  const maxValue = Math.max(...values);
  const minValue = Math.min(...values);
  const span = Math.max(maxValue - minValue, 1);
  const chartPoints = [{ trade_number: 0, cumulative_r: 0 }, ...points];
  const x = (index) => inset + (index / Math.max(chartPoints.length - 1, 1)) * (width - inset * 2);
  const y = (value) => inset + ((maxValue - value) / span) * (height - inset * 2);
  const line = chartPoints.map((point, index) => `${x(index)},${y(Number(point.cumulative_r))}`).join(" ");
  const baseline = y(0);
  const finalValue = Number(points[points.length - 1].cumulative_r);

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Cumulative paper performance chart in R">
      <line class="chart-baseline" x1="${inset}" y1="${baseline}" x2="${width - inset}" y2="${baseline}"></line>
      <polyline class="chart-line ${finalValue >= 0 ? "positive" : "negative"}" points="${line}"></polyline>
      <circle class="chart-endpoint ${finalValue >= 0 ? "positive" : "negative"}" cx="${x(chartPoints.length - 1)}" cy="${y(finalValue)}" r="5"></circle>
      <text x="${inset}" y="${Math.max(baseline - 7, 14)}">0R</text>
      <text x="${width - inset}" y="${Math.max(y(finalValue) - 9, 14)}" text-anchor="end">${escapeHtml(rValue(finalValue))}</text>
    </svg>
  `;
}

function renderPaperVisualization(state) {
  const progress = state.paper_visualization || {
    completed_trades: 0,
    allowed_completed_trades: 0,
    first_gate_percent: 0,
    strong_gate_percent: 0,
    total_r: 0,
    cumulative_r_points: [],
    by_signal_status: [],
    by_plan_adherence: [],
  };
  latestPaperProgress = progress;

  $("paper-first-gate-label").textContent = `${progress.allowed_completed_trades} / 30`;
  $("paper-strong-gate-label").textContent = `${progress.allowed_completed_trades} / 60`;
  $("paper-first-gate-bar").style.width = `${progress.first_gate_percent}%`;
  $("paper-strong-gate-bar").style.width = `${progress.strong_gate_percent}%`;
  $("paper-total-r").textContent = rValue(progress.total_r);

  if (!progress.completed_trades) {
    $("paper-viz-message").textContent =
      "No completed forward paper trades yet. This panel will populate from the existing paper review log after outcomes are recorded.";
  } else {
    $("paper-viz-message").textContent =
      `${progress.completed_trades} completed forward paper trades recorded. Continue toward the 30-trade first checkpoint before strategy conclusions.`;
  }

  $("paper-equity-chart").innerHTML = equityChart(progress.cumulative_r_points);
  $("paper-status-summary").innerHTML = renderSummaryRows(
    progress.by_signal_status,
    "No completed allowed or watch-only results recorded.",
  );
  $("paper-plan-summary").innerHTML = renderSummaryRows(
    progress.by_plan_adherence,
    "No completed plan-adherence results recorded.",
  );
  renderForwardPaperAccount(progress);
  renderEvidenceBridge(state);
}

function paperAccountRows(progress = {}) {
  const params = accountParams("paper-account");
  const points = progress.cumulative_r_points || [];
  let equity = params.startingEquity;
  let peakEquity = params.startingEquity;
  let maxDrawdown = 0;
  const rows = points.map((point, index) => {
    const resultR = Number(point.result_r || 0);
    const riskDollars = equity * params.riskDecimal;
    const pnlDollars = resultR * riskDollars;
    equity += pnlDollars;
    peakEquity = Math.max(peakEquity, equity);
    maxDrawdown = Math.min(maxDrawdown, equity - peakEquity);
    return {
      symbol: point.symbol || "",
      entry_time: `Paper trade ${index + 1}`,
      exit_time: `Paper trade ${index + 1}`,
      r_result: resultR,
      risk_dollars: Number(riskDollars.toFixed(2)),
      pnl_dollars: Number(pnlDollars.toFixed(2)),
      account_equity_after: Number(equity.toFixed(2)),
      exit_reason: point.signal_status || "logged paper",
    };
  });
  const account = {
    starting_equity: Number(params.startingEquity.toFixed(2)),
    ending_equity: Number(equity.toFixed(2)),
    total_pnl: Number((equity - params.startingEquity).toFixed(2)),
    return_pct: Number((((equity - params.startingEquity) / params.startingEquity) * 100).toFixed(2)),
    max_drawdown: Number(maxDrawdown.toFixed(2)),
    risk_per_trade_pct: Number(params.riskDecimal.toFixed(6)),
  };
  return { rows, account };
}

function renderForwardPaperAccount(progress = {}) {
  const { rows, account } = paperAccountRows(progress);
  const completed = Number(progress.completed_trades || 0);
  const allowed = Number(progress.allowed_completed_trades || 0);
  setAccountSummary("paper-account", account);
  $("paper-account-count").className = `status ${completed ? "review_only" : "watch"}`;
  $("paper-account-count").textContent = `${completed} logged`;
  $("paper-account-message").textContent = completed
    ? `Actual logged paper trades applied to a ${dollarValue(account.starting_equity)} account at ${(Number(account.risk_per_trade_pct || 0) * 100).toFixed(2)}% risk per trade.`
    : "No completed paper trades are logged yet. This account will update after Trade Logger saves outcomes.";

  if (!rows.length) {
    $("paper-account-context-grid").innerHTML = `
      <article><span>Win Rate</span><strong>--</strong><p>Logged paper trades.</p></article>
      <article><span>Average R</span><strong>--</strong><p>Forward validation.</p></article>
      <article><span>Allowed Trades</span><strong>${escapeHtml(allowed)}</strong><p>Progress gate count.</p></article>
      <article><span>Total Logged</span><strong>${escapeHtml(completed)}</strong><p>Completed outcomes.</p></article>
    `;
    renderMonthlyBreakdown("paper-account-monthly", []);
    $("paper-account-equity-chart").innerHTML = '<div class="paper-empty-chart">No actual logged paper trades yet.</div>';
    return;
  }

  const stats = backtestTradeStats(rows);
  $("paper-account-context-grid").innerHTML = `
    <article>
      <span>Win Rate</span>
      <strong>${escapeHtml(stats.winRate.toFixed(1))}%</strong>
      <p>${escapeHtml(stats.wins)} wins / ${escapeHtml(stats.losses)} losses / ${escapeHtml(stats.flat)} flat</p>
    </article>
    <article>
      <span>Average R</span>
      <strong class="${stats.averageR >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(stats.averageR))}</strong>
      <p>Actual completed paper outcomes</p>
    </article>
    <article>
      <span>Allowed Trades</span>
      <strong>${escapeHtml(allowed)}</strong>
      <p>Progress gate count</p>
    </article>
    <article>
      <span>Total Logged</span>
      <strong>${escapeHtml(completed)}</strong>
      <p>Completed outcomes</p>
    </article>
  `;
  renderMonthlyBreakdown("paper-account-monthly", rows);
  $("paper-account-equity-chart").innerHTML = backtestDollarEquityChart(rows, Number(account.starting_equity || 5000));
}

function portfolioAccountParams() {
  return {
    ...accountParams("portfolio"),
    riskModel: $("portfolio-risk-model")?.value || "tiered",
  };
}

function renderPortfolioContext(rows = [], account = {}) {
  if (!rows.length) {
    $("portfolio-context-grid").innerHTML = `
      <article><span>Win Rate</span><strong>--</strong><p>Promoted historical trades.</p></article>
      <article><span>Average R</span><strong>--</strong><p>Research simulation.</p></article>
      <article><span>Source Files</span><strong>${escapeHtml(account.source_files || 0)}</strong><p>Promoted candidates.</p></article>
      <article><span>Collapsed Duplicates</span><strong>${escapeHtml(account.duplicates_collapsed || 0)}</strong><p>Overlap control.</p></article>
    `;
    $("portfolio-risk-tier-summary").innerHTML = `
      <div>
        <strong>Risk tiers</strong>
        <span>${escapeHtml(account.risk_model === "tiered" ? "Tiered setup risk selected." : "Fixed risk selected.")}</span>
      </div>
      <strong>--</strong>
    `;
    $("portfolio-timeline-grid").innerHTML = `
      <article><span>First Trade</span><strong>--</strong><p>Historical start.</p></article>
      <article><span>Last Trade</span><strong>--</strong><p>Historical end.</p></article>
      <article><span>Active Dates</span><strong>--</strong><p>Days with trades.</p></article>
      <article><span>Active Months</span><strong>--</strong><p>Months represented.</p></article>
    `;
    renderMonthlyBreakdown("portfolio-monthly", []);
    renderPortfolioFreshness(account, rows);
    return;
  }
  const stats = backtestTradeStats(rows);
  const tierCounts = rows.reduce((counts, row) => {
    const tier = titleCase(row.research_risk_tier || "fixed");
    counts[tier] = (counts[tier] || 0) + 1;
    return counts;
  }, {});
  const tierText = Object.entries(tierCounts)
    .map(([tier, count]) => `${tier}: ${count}`)
    .join(" / ");
  const averageRiskPct = Number(account.average_risk_per_trade_pct || account.risk_per_trade_pct || 0) * 100;
  const maxRiskPct = Number(account.max_risk_per_trade_pct || account.risk_per_trade_pct || 0) * 100;
  $("portfolio-context-grid").innerHTML = `
    <article>
      <span>Win Rate</span>
      <strong>${escapeHtml(stats.winRate.toFixed(1))}%</strong>
      <p>${escapeHtml(stats.wins)} wins / ${escapeHtml(stats.losses)} losses / ${escapeHtml(stats.flat)} flat</p>
    </article>
    <article>
      <span>Average R</span>
      <strong class="${stats.averageR >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(stats.averageR))}</strong>
      <p>${escapeHtml(stats.total)} deduped historical trades</p>
    </article>
    <article>
      <span>Source Files</span>
      <strong>${escapeHtml(account.source_files || 0)}</strong>
      <p>${escapeHtml(account.source_candidates || 0)} promoted candidates</p>
    </article>
    <article>
      <span>Collapsed Duplicates</span>
      <strong>${escapeHtml(account.duplicates_collapsed || 0)}</strong>
      <p>Overlap control before P/L</p>
    </article>
  `;
  const timeline = portfolioTimelineFromRows(rows, account);
  $("portfolio-timeline-grid").innerHTML = `
    <article><span>First Trade</span><strong>${escapeHtml(formatDateLabel(timeline.first_entry))}</strong><p>Historical start.</p></article>
    <article><span>Last Trade</span><strong>${escapeHtml(formatDateLabel(timeline.last_entry))}</strong><p>Historical end.</p></article>
    <article><span>Active Dates</span><strong>${escapeHtml(timeline.active_trade_dates || "--")}</strong><p>Days with trades.</p></article>
    <article><span>Active Months</span><strong>${escapeHtml(timeline.active_months || "--")}</strong><p>Months represented.</p></article>
  `;
  $("portfolio-risk-tier-summary").innerHTML = `
    <div>
      <strong>Risk tiers</strong>
      <span>${escapeHtml(tierText || "Fixed risk")} / Avg risk ${escapeHtml(averageRiskPct.toFixed(2))}% / Max risk ${escapeHtml(maxRiskPct.toFixed(2))}%</span>
    </div>
    <strong>${escapeHtml(titleCase(account.risk_model || "fixed"))}</strong>
  `;
  renderMonthlyBreakdown("portfolio-monthly", rows);
  renderPortfolioFreshness(account, rows);
}

function dateOnly(value) {
  if (!value) return "";
  const date = parseDateValue(value);
  if (Number.isNaN(date.getTime())) return text(value, "").slice(0, 10);
  return date.toISOString().slice(0, 10);
}

function portfolioTimelineFromRows(rows = [], account = {}) {
  const fallback = account.timeline || {};
  const dates = rows
    .map((row) => parseDateValue(row.entry_time || row.exit_time || ""))
    .filter((date) => !Number.isNaN(date.getTime()));
  if (!dates.length) return fallback;

  const timestamps = dates.map((date) => date.getTime());
  const dateKeys = dates.map((date) => date.toISOString().slice(0, 10));
  const monthKeys = dates.map((date) => date.toISOString().slice(0, 7));
  return {
    first_entry: new Date(Math.min(...timestamps)).toISOString().slice(0, 10),
    last_entry: new Date(Math.max(...timestamps)).toISOString().slice(0, 10),
    active_trade_dates: new Set(dateKeys).size,
    active_months: new Set(monthKeys).size,
  };
}

function renderPortfolioFreshness(account = {}, rows = latestPortfolioRows) {
  const card = $("portfolio-freshness-card");
  if (!card) return;
  const timeline = portfolioTimelineFromRows(rows, account);
  const historicalThrough = dateOnly(timeline.last_entry);
  const scannerSession = currentState?.data_freshness?.latest_scanner_session || "";
  const hasBothDates = historicalThrough && scannerSession && scannerSession !== "unknown";
  const behind = hasBothDates && historicalThrough < scannerSession;
  const aligned = hasBothDates && historicalThrough >= scannerSession;
  const status = behind ? "stale" : aligned ? "current" : "unknown";
  const detail = behind
    ? `Historical research through ${formatDateLabel(historicalThrough)}. Current scanner session: ${formatDateLabel(scannerSession)}. Today's session is not included in this simulator account. After close, rerun the research/promotion review to refresh this lane.`
    : aligned
      ? `Historical research is current through ${formatDateLabel(historicalThrough)} and matches the latest scanner session.`
      : "Historical simulator date range is unavailable until promoted backtest rows load.";

  card.className = `portfolio-freshness-card ${status}`;
  card.innerHTML = `
    <strong>${behind ? "Historical simulator behind current scanner" : aligned ? "Historical simulator date aligned" : "Historical freshness unknown"}</strong>
    <span>${escapeHtml(detail)}</span>
  `;
}

function tradeYearFromRow(row) {
  const date = parseDateValue(row.entry_time || row.exit_time || "");
  return Number.isNaN(date.getTime()) ? "" : String(date.getFullYear());
}

function tradeMonthFromRow(row) {
  const date = parseDateValue(row.entry_time || row.exit_time || "");
  return Number.isNaN(date.getTime()) ? "" : String(date.getMonth() + 1).padStart(2, "0");
}

function populatePortfolioHistoryFilters(rows = []) {
  const symbolSelect = $("portfolio-history-symbol");
  const yearSelect = $("portfolio-history-year");
  const monthSelect = $("portfolio-history-month");
  if (!symbolSelect || !yearSelect || !monthSelect) return;

  const selectedSymbol = symbolSelect.value;
  const selectedYear = yearSelect.value;
  const selectedMonth = monthSelect.value;
  const symbols = Array.from(new Set(rows.map((row) => text(row.symbol, "").toUpperCase()).filter(Boolean))).sort();
  const years = Array.from(new Set(rows.map(tradeYearFromRow).filter(Boolean))).sort().reverse();
  const months = Array.from(
    new Set(
      rows
        .filter((row) => !selectedYear || tradeYearFromRow(row) === selectedYear)
        .map(tradeMonthFromRow)
        .filter(Boolean),
    ),
  ).sort();

  symbolSelect.innerHTML =
    '<option value="">All symbols</option>' +
    symbols.map((symbol) => `<option value="${escapeHtml(symbol)}">${escapeHtml(symbol)}</option>`).join("");
  symbolSelect.value = symbols.includes(selectedSymbol) ? selectedSymbol : "";

  yearSelect.innerHTML = '<option value="">All years</option>' + years.map((year) => `<option value="${escapeHtml(year)}">${escapeHtml(year)}</option>`).join("");
  yearSelect.value = years.includes(selectedYear) ? selectedYear : "";

  monthSelect.innerHTML =
    '<option value="">All months</option>' +
    months
      .map((month) => {
        const label = monthLabelFromKey(`${yearSelect.value || "2026"}-${month}`).replace(/ 2026$/, "");
        return `<option value="${escapeHtml(month)}">${escapeHtml(label)}</option>`;
      })
      .join("");
  monthSelect.value = months.includes(selectedMonth) ? selectedMonth : "";
}

function portfolioHistoryFiltersActive() {
  return Boolean(
    $("portfolio-history-symbol")?.value ||
      $("portfolio-history-year")?.value ||
      $("portfolio-history-month")?.value ||
      $("portfolio-history-result")?.value ||
      ($("portfolio-history-sort")?.value && $("portfolio-history-sort").value !== "newest") ||
      $("portfolio-history-search")?.value.trim(),
  );
}

function filteredPortfolioHistoryRows(rows = []) {
  const symbol = $("portfolio-history-symbol")?.value || "";
  const year = $("portfolio-history-year")?.value || "";
  const month = $("portfolio-history-month")?.value || "";
  const result = $("portfolio-history-result")?.value || "";
  const sort = $("portfolio-history-sort")?.value || "newest";
  const search = ($("portfolio-history-search")?.value || "").trim().toLowerCase();
  const filtered = rows.filter((row) => {
    if (symbol && text(row.symbol, "").toUpperCase() !== symbol) return false;
    if (year && tradeYearFromRow(row) !== year) return false;
    if (month && tradeMonthFromRow(row) !== month) return false;
    const rResult = Number(row.r_result || 0);
    if (result === "win" && rResult <= 0) return false;
    if (result === "loss" && rResult >= 0) return false;
    if (result === "flat" && rResult !== 0) return false;
    if (!search) return true;
    const haystack = [
      row.symbol,
      row.source_setup,
      row.source_candidate,
      row.quality_grade,
      row.exit_reason,
      row.source_trade_log,
      row.entry_time,
    ]
      .map((value) => text(value, "").toLowerCase())
      .join(" ");
    return haystack.includes(search);
  });
  return filtered.sort((left, right) => {
    const leftDate = parseDateValue(left.entry_time || left.exit_time || "").getTime() || 0;
    const rightDate = parseDateValue(right.entry_time || right.exit_time || "").getTime() || 0;
    if (sort === "oldest") return leftDate - rightDate;
    if (sort === "best") return Number(right.r_result || 0) - Number(left.r_result || 0);
    if (sort === "worst") return Number(left.r_result || 0) - Number(right.r_result || 0);
    return rightDate - leftDate;
  });
}

function compactTradeSourceName(value) {
  const source = text(value, "--");
  if (source === "--") return source;
  const cleaned = source
    .replace(/^logs\//, "")
    .replace(/_webull_30m_entry_5m_exit_(baseline|elite)_trades\.csv$/i, "")
    .replace(/_trades\.csv$/i, "");
  const parts = cleaned.split("_");
  if (parts.length <= 1) return cleaned;
  const symbol = parts[0];
  const setup = parts.slice(1, 4).join("_");
  return `${symbol} ${setup}`;
}

function renderPortfolioTradeHistory(rows = latestPortfolioRows, account = latestPortfolioAccount, totalRows = latestPortfolioTotalRows || rows.length) {
  const count = $("portfolio-history-count");
  const message = $("portfolio-history-message");
  const body = $("portfolio-history-body");
  if (!count || !message || !body) return;

  populatePortfolioHistoryFilters(rows);
  const filteredRows = filteredPortfolioHistoryRows(rows);
  const hasFilters = portfolioHistoryFiltersActive();
  const visibleLimit = hasFilters ? 50 : 12;
  const visibleRows = filteredRows.slice(0, visibleLimit);

  if (!rows.length) {
    count.className = "status watch";
    count.textContent = "No rows";
    message.textContent =
      "No promoted historical trades are available for the current simulator settings.";
    body.innerHTML = '<tr><td colspan="11">No historical simulated trades are loaded.</td></tr>';
    return;
  }

  if (!filteredRows.length) {
    count.className = "status watch";
    count.textContent = "0 matched";
    message.textContent = "No historical simulated trades match the current filters.";
    body.innerHTML = '<tr><td colspan="11">No matching historical simulated trades.</td></tr>';
    return;
  }

  count.className = "status review_only";
  count.textContent = `${visibleRows.length}/${filteredRows.length} shown`;
  const filteredText = hasFilters ? ` after filtering ${rows.length} loaded row${rows.length === 1 ? "" : "s"}` : "";
  const sort = $("portfolio-history-sort")?.value || "newest";
  const sliceLabel = sort === "newest" ? "latest" : "first";
  const capText = filteredRows.length > visibleRows.length ? ` Showing the ${sliceLabel} ${visibleRows.length}; narrow the filters to drill in.` : "";
  message.textContent =
    `${filteredRows.length} historical simulator row${filteredRows.length === 1 ? "" : "s"} matched${filteredText}.${capText} These rows drive the historical account curve, not the forward paper-progress gate.`;
  body.innerHTML = visibleRows
    .map((trade) => {
      const result = Number(trade.r_result || 0);
      const pnl = Number(trade.pnl_dollars || 0);
      const riskPct = Number(trade.applied_risk_per_trade_pct || account.risk_per_trade_pct || 0) * 100;
      const riskLabel = `${dollarValue(trade.risk_dollars)} / ${riskPct.toFixed(2)}%`;
      const fullSource = text(trade.source_trade_log, "--");
      const sourceLabel = compactTradeSourceName(fullSource);
      return `
        <tr>
          <td>${escapeHtml(text(trade.entry_time, "--"))}</td>
          <td>${escapeHtml(text(trade.symbol, "--"))}</td>
          <td class="compact-cell" title="${escapeHtml(text(trade.source_setup, "--"))}">${escapeHtml(text(trade.source_setup, "--"))}</td>
          <td class="compact-cell wide" title="${escapeHtml(text(trade.source_candidate, "--"))}">${escapeHtml(text(trade.source_candidate, "--"))}</td>
          <td>${escapeHtml(text(trade.quality_grade, "--"))} ${escapeHtml(text(trade.quality_score, ""))}</td>
          <td class="${result >= 0 ? "positive" : "negative"}">${escapeHtml(rValue(result))}</td>
          <td>${escapeHtml(riskLabel)}</td>
          <td class="${pnl >= 0 ? "positive" : "negative"}">${escapeHtml(`${pnl >= 0 ? "+" : ""}${dollarValue(pnl)}`)}</td>
          <td>${escapeHtml(dollarValue(trade.account_equity_after))}</td>
          <td>${escapeHtml(titleCase(trade.exit_reason || "--"))}</td>
          <td class="source-cell" title="${escapeHtml(fullSource)}">${escapeHtml(sourceLabel)}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadBacktestPortfolioSimulation() {
  const message = $("research-account-message");
  const badge = $("research-account-count");
  const params = portfolioAccountParams();
  badge.className = "status watch";
  badge.textContent = "Loading";
  message.textContent = "Loading promoted backtest account simulation.";
  $("portfolio-equity-chart").innerHTML = '<div class="paper-empty-chart">Calculating promoted-backtest account curve...</div>';

  try {
    const query = new URLSearchParams({
      starting_equity: String(params.startingEquity),
      risk_per_trade_pct: String(params.riskDecimal),
      risk_model: params.riskModel,
    });
    const response = await fetch(`${backtestPortfolioUrl}?${query.toString()}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Backtest portfolio request failed: ${response.status}`);

    const rows = payload.rows || [];
    const account = payload.account || {};
    latestPortfolioRows = rows;
    latestPortfolioAccount = account;
    latestPortfolioTotalRows = Number(payload.row_count || rows.length);
    setAccountSummary("portfolio", account);
    renderPortfolioContext(rows, account);
    renderPortfolioTradeHistory(rows, account, latestPortfolioTotalRows);
    badge.className = "status review_only";
    badge.textContent = `${payload.row_count || 0} simulated`;
    message.textContent =
      `Promoted historical backtests applied to a ${dollarValue(account.starting_equity)} research account with ${titleCase(account.risk_model || params.riskModel)} risk. Base risk is ${(Number(account.risk_per_trade_pct || 0) * 100).toFixed(2)}%; average applied risk is ${(Number(account.average_risk_per_trade_pct || 0) * 100).toFixed(2)}%. ${account.duplicates_collapsed || 0} overlapping duplicate trades were collapsed.`;
    $("portfolio-equity-chart").innerHTML = backtestDollarEquityChart(rows, Number(account.starting_equity || 5000));
  } catch (error) {
    badge.className = "status caution";
    badge.textContent = "Unavailable";
    message.textContent = error.message;
    latestPortfolioRows = [];
    latestPortfolioAccount = {};
    latestPortfolioTotalRows = 0;
    setAccountSummary("portfolio", { starting_equity: params.startingEquity });
    renderPortfolioContext([], {});
    renderPortfolioTradeHistory([], {});
    $("portfolio-equity-chart").innerHTML = '<div class="paper-empty-chart">Could not load promoted-backtest account simulation.</div>';
  }
}

function renderForwardEvidence(state) {
  const observations = state.forward_observations || {};
  const validation = state.forward_validation || {};
  setText("evidence-observed", observations.rows || 0);
  setText("evidence-matured", validation.matured_outcomes || 0);
  setText("evidence-allowed-r", rValue(validation.allowed_average_r));
  setText("evidence-allowed-count", `${validation.allowed_matured || 0} matured`);
  setText("evidence-blocked-r", rValue(validation.blocked_average_r));
  setText("evidence-blocked-count", `${validation.blocked_matured || 0} matured`);
  setText("evidence-integrity", validation.integrity_issue_count || 0);
}

function renderEvidenceBridge(state) {
  const bridge = state.forward_evidence_bridge || {};
  const official = Number(bridge.official_paper_trades || 0);
  const remaining = Number(bridge.remaining_to_30 ?? 30);
  const observations = Number(bridge.forward_observations || 0);
  const maturedObservations = Number(bridge.matured_observations || 0);
  const shadow = Number(bridge.shadow_samples || 0);
  const maturedShadow = Number(bridge.matured_shadow_samples || 0);
  const agingRows = Number(bridge.candidate_aging_rows || 0);
  const lateAverage = Number(bridge.late_day_average_r || 0);
  const caution = bridge.aging_status === "late_day_caution";

  $("evidence-bridge-status").className = `status ${official > 0 ? "review_only" : "watch"}`;
  $("evidence-bridge-status").textContent = `${official}/30 official`;
  $("evidence-bridge-message").textContent =
    bridge.message || "Only completed allowed paper trades count toward the 30/60 gates. Other lanes are research context.";
  setText("bridge-official-paper", official);
  setText("bridge-official-detail", `${remaining} left to first gate`);
  setText("bridge-observations", observations);
  setText("bridge-observation-detail", `${maturedObservations} matured / ${rValue(bridge.allowed_observation_average_r)} allowed avg`);
  setText("bridge-shadow", shadow);
  setText("bridge-shadow-detail", `${maturedShadow} matured / ${rValue(bridge.shadow_average_r)} avg`);
  setText("bridge-aging", agingRows);
  setText("bridge-aging-detail", caution ? `Late-day caution ${rValue(lateAverage)}` : `Late-day avg ${rValue(lateAverage)}`);
}

function candidateIsLateDay(card) {
  const timeText = text(card.signal_time_et, "");
  const match = timeText.match(/(\d{1,2}):(\d{2})/);
  if (!match) return false;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return hour > 14 || (hour === 14 && minute >= 30);
}

function candidateWorkflowHtml(card, state) {
  const lateCaution = candidateIsLateDay(card) && state.forward_evidence_bridge?.aging_status === "late_day_caution";
  const steps = [
    ["Confirm chart context", "Open Trading Workspace and verify 1H thesis, 30m entry, 5m management."],
    ["Review risk", "Check entry, stop, target, size, and max paper risk before logging anything."],
    ["Respect gate", "Only log after a current-candle candidate is reviewed manually."],
    ["Track outcome", "Use Trade Logger after the paper trade closes so it counts toward forward evidence."],
  ];
  return `
    <div class="candidate-workflow">
      <strong>Paper workflow</strong>
      <ol>
        ${steps.map(([label, detail]) => `<li><span>${escapeHtml(label)}</span>${escapeHtml(detail)}</li>`).join("")}
      </ol>
      ${
        lateCaution
          ? `<p class="candidate-late-warning">Late-day caution: recent late-day candidate evidence is negative. Treat this as caution-only unless every rule is unusually clean.</p>`
          : ""
      }
    </div>
  `;
}

function renderPaperWorkflowGuide(state) {
  const guide = $("paper-workflow-guide");
  if (!guide) return;
  const bridge = state.forward_evidence_bridge || {};
  const ready = Number(state.current_candidates?.ready_for_review_count || 0);
  const gate = Number(bridge.official_paper_trades || 0);
  const remaining = Number(bridge.remaining_to_30 ?? 30);
  const lateCaution = bridge.aging_status === "late_day_caution";
  guide.innerHTML = `
    <article class="workflow-guide-card">
      <header>
        <div>
          <p class="eyebrow">Candidate-to-paper flow</p>
          <h4>How A Trade Starts Counting</h4>
        </div>
        <span class="status ${ready ? "healthy" : "watch"}">${escapeHtml(ready)} ready</span>
      </header>
      <ol>
        <li><span>1</span> Fresh current-candle candidate appears and scanner marks it allowed.</li>
        <li><span>2</span> Position sizing is size_ok and the chart/checklist are manually reviewed.</li>
        <li><span>3</span> You log the local paper entry; no broker order is placed by this app.</li>
        <li><span>4</span> After exit, Trade Logger records the outcome and it counts toward the 30-trade gate.</li>
      </ol>
      <p>${escapeHtml(gate)} official allowed paper trade${gate === 1 ? "" : "s"} logged; ${escapeHtml(remaining)} left to the first checkpoint.</p>
      ${lateCaution ? `<p class="candidate-late-warning">Timing warning: late-day candidate evidence is currently negative, so late signals should be treated with extra caution.</p>` : ""}
    </article>
  `;
}

function renderReplayCard() {
  const card = replayCards[replayIndex];
  if (!card) {
    $("replay-counter").textContent = "No replay cards";
    $("replay-title").textContent = allReplayCards.length ? "No cards match this practice session" : "Run python run_setup_replay.py";
    $("replay-result").textContent = "Missing";
    $("replay-details").innerHTML = "";
    $("replay-prompts").innerHTML = "";
    $("replay-chart").innerHTML = '<div class="terminal-empty">No replay chart available.</div>';
    $("replay-chart-note").textContent = "Generate setup replay cards to load historical chart context.";
    $("replay-decision-prompt").textContent = "No historical setup is available for a practice decision.";
    $("replay-notes").value = "";
    for (const button of document.querySelectorAll(".replay-decision-buttons button")) {
      button.disabled = true;
    }
    for (const id of ["replay-start-management", "replay-hold", "replay-exit-here", "replay-stop-followed"]) {
      $(id).disabled = true;
    }
    $("replay-management-prompt").textContent = "No replay is available for candle management.";
    $("replay-visible-step").textContent = "Not started";
    $("replay-current-price").textContent = "Hidden";
    $("replay-current-r").textContent = "Hidden";
    $("replay-reveal").disabled = true;
    return;
  }

  const journal = replayJournalEntry(card);
  const decisionLocked = Boolean(journal.outcome_reviewed);
  $("replay-counter").textContent = `Replay ${replayIndex + 1} of ${replayCards.length}`;
  $("replay-title").textContent = `${card.symbol} ${card.setup} / ${titleCase(card.direction)}`;
  $("replay-entry").textContent = card.entry;
  $("replay-stop").textContent = card.stop;
  $("replay-target").textContent = card.target;

  const planRows = [
    ["Entry time", card.entry_time],
    ["Quality", `${card.quality_grade} / ${card.quality_score}`],
    ["Relative volume", card.relative_volume],
    ["Room to target R", card.room_to_target_r],
  ];
  const outcomeRows = [
    ["Exit time", card.exit_time],
    ["Exit price", card.exit_price],
    ["Exit reason", card.exit_reason],
    ["Notes", card.notes],
  ];
  const practiceRows = journal.practice_exit_action
    ? [
        ["Practice exit", titleCase(journal.practice_exit_action)],
        ["Practice exit price", journal.practice_exit_price],
        ["Practice result", `${journal.practice_exit_r}R`],
      ]
    : [];
  const prompts = replayOutcomeRevealed
    ? [...(card.plan_prompts || []), ...(card.outcome_review_prompts || card.what_to_notice || [])]
    : card.plan_prompts || ["Review entry, stop, and target before revealing this historical outcome."];

  if (replayOutcomeRevealed) {
    $("replay-result").className = `status ${card.r_result >= 0 ? "healthy" : "caution"}`;
    $("replay-result").textContent = titleCase(card.result_type);
    $("replay-r").textContent = `${card.r_result}R`;
  } else {
    $("replay-result").className = "status watch";
    $("replay-result").textContent = "Outcome Hidden";
    $("replay-r").textContent = "Hidden";
  }
  $("replay-details").innerHTML = [...planRows, ...practiceRows, ...(replayOutcomeRevealed ? outcomeRows : [])]
    .map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(text(value))}</td></tr>`)
    .join("");

  $("replay-prompts").innerHTML = prompts
    .map((prompt) => `<li>${escapeHtml(prompt)}</li>`)
    .join("");
  $("replay-decision-prompt").textContent = journal.decision
    ? `Recorded decision: ${titleCase(journal.decision)}.${decisionLocked ? " Locked after outcome review." : " Reveal when ready."}`
    : "Would you take, skip, or watch this historical setup before seeing its result?";
  for (const button of document.querySelectorAll(".replay-decision-buttons button")) {
    button.disabled = decisionLocked;
    button.classList.toggle("active", button.dataset.decision === journal.decision);
  }
  $("replay-notes").value = journal.notes || "";
  $("replay-save-status").textContent = journal.notes
    ? "Saved locally in this browser."
    : "Optional notes are stored locally in this browser only.";
  renderReplayManagement(card, journal);
  loadReplayChart(card);
}

async function loadReplayChart(card) {
  const requestId = ++replayChartRequestId;
  $("replay-chart").innerHTML = '<div class="terminal-empty">Loading historical decision view...</div>';
  $("replay-chart-note").textContent = replayOutcomeRevealed
    ? "Loading revealed historical outcome..."
    : "Outcome candles stay hidden until reveal.";

  try {
    const chartParams = new URLSearchParams({ id: card.replay_id, revealed: replayOutcomeRevealed });
    if (!replayOutcomeRevealed && replayManagementStep !== null) {
      chartParams.set("step", replayManagementStep);
    }
    const response = await fetch(`${replayChartUrl}?${chartParams.toString()}`, { cache: "no-store" });
    const chart = await response.json();
    if (!response.ok) throw new Error(chart.error || `Replay chart request failed: ${response.status}`);
    if (requestId !== replayChartRequestId) return;

    replayLatestChart = chart;
    $("replay-chart").innerHTML = tradingChartSvg(chart.candles, chart.markers, chart.plan_levels);
    $("replay-chart-note").textContent = `${chart.source}. ${chart.chart_note}`;
    renderReplayManagement(card, replayJournalEntry(card));
  } catch (error) {
    if (requestId !== replayChartRequestId) return;
    $("replay-chart").innerHTML = `<div class="terminal-empty">${escapeHtml(error.message)}</div>`;
    $("replay-chart-note").textContent = "Historical replay chart data is unavailable for this card.";
  }
}

function renderReplay(state) {
  allReplayCards = state.setup_replay?.cards || [];
  replayJournal = readReplayJournal();
  renderReplayFilterOptions();
  applyReplayFilters();
}

function renderFiles(state) {
  const files = [
    ["System state", "system_state.json", state.source_files.setup_health_csv ? "App JSON" : "JSON"],
    ["Dashboard", "project_gwala_dashboard.md", "Markdown"],
    ["Scanner", "daily_paper_signal_scanner.md", "Markdown"],
    ["Observations", "forward_signal_observations.md", "Markdown"],
    ["Near misses", "near_miss_analytics.md", "Markdown"],
    ["Observation review", "forward_observation_review.md", "Markdown"],
    ["Reconciliation", "observation_paper_reconciliation.md", "Markdown"],
    ["Data integrity", "candle_data_integrity.md", "Markdown"],
    ["Refresh audit", "market_refresh_audit.md", "Markdown"],
    ["Position sizing", "position_sizing.md", "Markdown"],
    ["Setup health", "setup_health.md", "Markdown"],
    ["Paper session", "paper_session_cycle.md", "Markdown"],
    ["Paper execution", "local_paper_execution_simulator.md", "Markdown"],
    ["Candidate alerts", "paper_candidate_alerts.md", "Markdown"],
    ["Forward sample queue", "forward_sample_queue.md", "Markdown"],
    ["Forward evidence", "forward_evidence.md", "Markdown"],
    ["Candidate aging", "candidate_aging.md", "Markdown"],
    ["No-trade analysis", "no_trade_blocker_analysis.md", "Markdown"],
    ["Shadow samples", "shadow_samples.md", "Markdown"],
    ["Open paper monitor", "open_paper_trade_monitor.md", "Markdown"],
    ["Refresh status", "refresh_status.md", "Markdown"],
    ["Pre-market verification", "premarket_verification.md", "Markdown"],
    ["Setup replay", "setup_replay.md", "Markdown"],
    ["Strategy vault", "strategy_vault.md", "Markdown"],
    ["VWAP mean reversion", "vwap_mean_reversion.md", "Markdown"],
    ["VWAP mean reversion walk-forward", "vwap_mean_reversion_walk_forward.md", "Markdown"],
    ["VWAP mean reversion shadow samples", "vwap_mean_reversion_shadow_samples.md", "Markdown"],
    ["VWAP mean reversion forward observations", "vwap_mean_reversion_forward_observations.md", "Markdown"],
    ["VWAP mean reversion paper-watch gate", "vwap_mean_reversion_paper_watch_gate.md", "Markdown"],
    ["Opening range failure", "opening_range_failure.md", "Markdown"],
    ["Strategy evidence accumulator", "strategy_evidence_accumulator.md", "Markdown"],
    ["Research confidence", "universe_expansion/research_confidence.md", "Markdown"],
    ["Promotion review", "promotion_review.md", "Markdown"],
    ["Controlled variants", "controlled_variant_review.md", "Markdown"],
    ["Walk forward", "walk_forward_review.md", "Markdown"],
    ["Regime review", "regime_review.md", "Markdown"],
    ["Strategy audit", "strategy_overlap_audit.md", "Markdown"],
    ["Opening range test", "opening_range_relaxation_review.md", "Markdown"],
    ["Deep research", "deeper_research/research_confidence.md", "Markdown"],
    ["Deep promotion", "deeper_research/promotion_review.md", "Markdown"],
    ["Deep controlled", "deeper_research/controlled_variant_review.md", "Markdown"],
    ["Deep walk forward", "deeper_research/walk_forward_review.md", "Markdown"],
    ["Deep regime", "deeper_research/regime_review.md", "Markdown"],
    ["Readiness", "readiness_check.md", "Markdown"],
  ];

  $("file-links").innerHTML = files
    .map(
      ([label, file, kind]) => `
        <a href="/logs/${file}" target="_blank" rel="noreferrer">
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(kind)}</span>
        </a>
      `,
    )
    .join("");
}

function escapeHtml(value) {
  return text(value, "").replace(/[&<>"']/g, (character) => {
    const escapes = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return escapes[character];
  });
}

function inlineMarkdown(value) {
  let output = escapeHtml(value);
  output = output.replace(/`([^`]+)`/g, "<code>$1</code>");
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return output;
}

function markdownTable(lines, startIndex) {
  const header = lines[startIndex]
    .trim()
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
  let index = startIndex + 2;
  const body = [];
  while (index < lines.length && lines[index].trim().startsWith("|")) {
    body.push(
      lines[index]
        .trim()
        .slice(1, -1)
        .split("|")
        .map((cell) => cell.trim()),
    );
    index += 1;
  }

  const head = `<thead><tr>${header.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead>`;
  const rows = body
    .map((row) => `<tr>${row.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`)
    .join("");
  return { html: `<div class="table-wrap"><table>${head}<tbody>${rows}</tbody></table></div>`, nextIndex: index };
}

function markdownToHtml(markdown) {
  const lines = text(markdown, "").split("\n");
  const html = [];
  let inCode = false;
  let codeLines = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (line.trim().startsWith("```")) {
      if (inCode) {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (line.trim().startsWith("|") && index + 1 < lines.length && lines[index + 1].includes("---")) {
      const table = markdownTable(lines, index);
      html.push(table.html);
      index = table.nextIndex - 1;
      continue;
    }

    if (line.startsWith("# ")) {
      html.push(`<h1>${inlineMarkdown(line.slice(2))}</h1>`);
    } else if (line.startsWith("## ")) {
      html.push(`<h2>${inlineMarkdown(line.slice(3))}</h2>`);
    } else if (line.startsWith("### ")) {
      html.push(`<h3>${inlineMarkdown(line.slice(4))}</h3>`);
    } else if (line.startsWith("- ")) {
      html.push(`<p>${inlineMarkdown(line)}</p>`);
    } else if (line.trim() === "") {
      html.push("");
    } else {
      html.push(`<p>${inlineMarkdown(line)}</p>`);
    }
  }

  return html.join("\n");
}

async function loadReport(name) {
  const response = await fetch(`/api/report?name=${encodeURIComponent(name)}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Report request failed: ${response.status}`);
  }
  return response.json();
}

async function showReport(name) {
  const reportSelect = $("report-select");
  if (reportSelect && reportSelect.value !== name) {
    reportSelect.value = name;
  }

  $("report-title").textContent = "Loading...";
  $("report-filename").textContent = name;
  $("report-content").textContent = "Loading report...";

  try {
    const report = await loadReport(name);
    $("report-filename").textContent = report.filename;
    $("report-title").textContent = reports.find(([key]) => key === name)?.[1] || report.name;
    $("report-content").innerHTML = markdownToHtml(report.content);
  } catch (error) {
    $("report-title").textContent = "Report unavailable";
    $("report-content").textContent = error.message;
  }
}

function renderReportTabs() {
  const reportLabels = {};
  for (const [key, label] of reports) {
    reportLabels[key] = label;
  }
  const usedReports = new Set([].concat(...reportGroups.map((group) => group.reports)));
  const ungroupedReports = reports.map(([name]) => name).filter((name) => !usedReports.has(name));
  const groups = ungroupedReports.length
    ? [...reportGroups, { label: "Other", reports: ungroupedReports }]
    : reportGroups;

  $("report-tabs").innerHTML = `
    <label for="report-select">Report</label>
    <select id="report-select">
      ${groups
        .map(
          (group) => `
            <optgroup label="${escapeHtml(group.label)}">
              ${group.reports
                .filter((name) => reportLabels[name])
                .map((name) => `<option value="${name}">${escapeHtml(reportLabels[name])}</option>`)
                .join("")}
            </optgroup>
          `
        )
        .join("")}
    </select>
  `;
  $("report-select").addEventListener("change", (event) => showReport(event.target.value));
}

function updateAppRoute() {
  let activeHash = window.location.hash && window.location.hash !== "#" ? window.location.hash : "#home";
  const routeAliases = {
    "#state": "#system",
    "#app-health": "#system",
    "#workflow": "#system",
    "#app-scaffold": "#system",
    "#research-confidence": "#research",
    "#promotion-review": "#research",
    "#forward-evidence": "#research",
  };
  if (routeAliases[activeHash]) {
    window.location.hash = routeAliases[activeHash];
    return;
  }
  const routePages = {
    "#home": {
      bodyClass: "home-route",
      sections: ["command-center", "backtest-performance", "session-readiness"],
    },
    "#trading-workspace": { bodyClass: "trading-workspace-route", sections: ["trading-workspace"] },
    "#near-miss-analytics": { bodyClass: "near-miss-analytics-route", sections: ["near-miss-analytics"] },
    "#investment-narrative": { bodyClass: "investment-narrative-route", sections: ["investment-narrative"] },
    "#research": { bodyClass: "research-route", sections: ["research-confidence", "promotion-review", "forward-evidence"] },
    "#strategy-vault": { bodyClass: "strategy-vault-route", sections: ["strategy-vault"] },
    "#system": { bodyClass: "system-route", sections: ["state", "state-metrics", "app-health", "workflow", "app-scaffold"] },
    "#sample-queue": { bodyClass: "sample-queue-route", sections: ["sample-queue"] },
    "#candidates": { bodyClass: "candidates-route", sections: ["candidates"] },
    "#trade-logger": { bodyClass: "trade-logger-route", sections: ["trade-logger"] },
    "#paper-visualization": { bodyClass: "paper-visualization-route", sections: ["paper-visualization"] },
    "#health": { bodyClass: "setup-health-route", sections: ["health"] },
    "#practice-replay": { bodyClass: "practice-replay-route", sections: ["practice-replay"] },
    "#reports": { bodyClass: "reports-route", sections: ["reports"] },
  };
  const selectedPage = routePages[activeHash] || routePages["#home"];
  const selectedSections = new Set(selectedPage.sections);
  const routePageList = Object.keys(routePages).map((key) => routePages[key]);
  const allRouteClasses = routePageList.map((page) => page.bodyClass);
  const allRouteSections = new Set([].concat(...routePageList.map((page) => page.sections)));

  for (const routeClass of allRouteClasses) {
    document.body.classList.toggle(routeClass, routeClass === selectedPage.bodyClass);
  }

  for (const sectionId of allRouteSections) {
    const section = $(sectionId);
    if (section) section.hidden = !selectedSections.has(sectionId);
  }

  const topbar = document.querySelector(".topbar");
  if (topbar) topbar.hidden = activeHash !== "#home";

  if (!routePages[activeHash]) {
    window.location.hash = "#home";
    return;
  }

  for (const link of document.querySelectorAll(".sidebar nav a")) {
    link.classList.toggle("active", link.getAttribute("href") === activeHash);
  }

  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
}

function renderState(state) {
  currentState = state;
  const phase = $("phase-pill");
  if (phase) {
    phase.textContent = titleCase(state.project_phase);
    phase.className = state.data_freshness?.data_status === "fresh_for_today" ? "pill" : "pill warn";
  }

  setText("verdict", state.readiness_verdict);
  setText(
    "safety-line",
    `Live trading: ${state.safety?.live_trading_enabled} / Broker execution: ${state.safety?.broker_order_execution_enabled}`,
  );

  setText("market-status", titleCase(state.market?.today_status));
  setText("next-session", `Next session: ${state.market?.next_market_session || "--"}`);
  setText("data-status", titleCase(state.data_freshness?.data_status));
  setText("latest-session", `Latest scanner session: ${state.data_freshness?.latest_scanner_session || "--"}`);
  setText("paper-gate", `${state.paper_progress?.first_gate_remaining ?? "--"} left`);
  setText("paper-progress", `${state.paper_progress?.allowed_completed_trades ?? "--"} allowed completed trades`);
  setText("health-count", `${state.setup_health?.attention_count ?? "--"} attention`);
  setText("health-summary", JSON.stringify(state.setup_health?.status_counts || {}));
  const vault = state.strategy_vault || {};
  const vaultRegime = vault.regime || {};
  const selector = vault.selector || {};
  setText(
    "strategy-vault-status",
    selector.paper_watch_strategy
      ? `Paper: ${selector.paper_watch_strategy}`
      : selector.research_strategy
        ? `Research: ${selector.research_strategy}`
        : titleCase(vaultRegime.market_regime || "missing"),
  );
  setText(
    "strategy-vault-detail",
    selector.allowed_action || vault.next_action || "Run the strategy vault report to classify the market regime.",
  );
  setText("premarket-status", titleCase(state.premarket_verification?.status || "not_run"));
  setText(
    "premarket-detail",
    state.premarket_verification?.modified_et
      ? `Probe: ${titleCase(state.premarket_verification.probe_status)} / Checked: ${state.premarket_verification.modified_et}`
      : "Run the local pre-market check before the session.",
  );
  setText("data-reliability-status", titleCase(state.data_reliability?.status || "unknown"));
  setText("data-reliability-detail", state.data_reliability?.headline || "Checking automation and refresh health.");

  safeRender("Command center", () => renderCommandCenter(state));
  safeRender("Backtest performance", () => renderBacktestPerformance(state));
  safeRender("Research confidence", () => renderResearchConfidence(state));
  safeRender("Promotion review", () => renderPromotionReview(state));
  safeRender("Session readiness", () => renderSessionReadiness(state));
  safeRender("Strategy vault", () => renderStrategyVault(state));
  safeRender("Workflow", () => renderWorkflow(state));
  safeRender("Badges", () => renderBadges(state));
  safeRender("App health", () => renderAppHealth(state));
  safeRender("Guardrails", () => renderGuardrails(state));
  if (!terminalInitialized) {
    const currentCard = state.current_candidates?.cards?.[0];
    terminalSymbol = currentCard?.symbol || terminalSymbol;
    terminalInitialized = true;
  }
  safeRender("Trading workspace", () => loadTradingWorkspace());
  safeRender("Sample queue", () => renderSampleQueue(state));
  safeRender("Almost-ready breakout", () => renderAlmostReadyBreakout(state));
  safeRender("Candidates", () => renderCandidates(state));
  safeRender("Candidate alerts", () => monitorCandidateAlerts(state));
  safeRender("Open paper trades", () => loadOpenPaperTrades());
  safeRender("Forward evidence", () => renderForwardEvidence(state));
  safeRender("Near misses", () => loadNearMissAnalytics());
  safeRender("Paper visualization", () => renderPaperVisualization(state));
  safeRender("Setup health", () => renderHealth(state));
  safeRender("Replay", () => renderReplay(state));
  safeRender("Files", () => renderFiles(state));
  safeRender("Help bubbles", () => hydrateHelpBubbles());
  alertStateInitialized = true;
}

async function loadState() {
  const response = await fetch(stateUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`System state request failed: ${response.status}`);
  }
  return response.json();
}

async function runRefreshStatusAction() {
  const button = $("run-refresh-status");
  const message = $("refresh-action-message");
  button.disabled = true;
  message.className = "action-message running";
  message.textContent = "Updating readiness reports only...";

  try {
    const response = await fetch(refreshStatusActionUrl, { method: "POST", cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Status update failed: ${response.status}`);
    }

    renderState(payload.state);
    message.className = "action-message success";
    message.textContent = payload.message;
    await showReport("refresh_status");
  } catch (error) {
    message.className = "action-message failure";
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function runWebullRefreshAction() {
  const button = $("run-webull-refresh");
  const message = $("webull-refresh-message");
  button.disabled = true;
  message.className = "action-message running";
  message.textContent = "Refreshing Webull market-data CSVs and rebuilding reports...";

  try {
    const response = await fetch(refreshWebullDataActionUrl, { method: "POST", cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Webull refresh failed: ${response.status}`);
    }

    renderState(payload.state);
    message.className = "action-message success";
    message.textContent = payload.message;
    await showReport("refresh_status");
  } catch (error) {
    message.className = "action-message failure";
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function runPremarketCheckAction() {
  const button = $("run-premarket-check");
  const message = $("premarket-action-message");
  button.disabled = true;
  message.className = "action-message running";
  message.textContent = "Running local pre-market verification...";

  try {
    const response = await fetch(premarketCheckActionUrl, { method: "POST", cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Pre-market check failed: ${response.status}`);
    }

    renderState(payload.state);
    message.className = "action-message success";
    message.textContent = payload.message;
    await showReport("premarket");
  } catch (error) {
    message.className = "action-message failure";
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function runPaperSessionAction(url, runningText) {
  const buttons = [
    $("run-paper-session-preview"),
    $("confirm-paper-entry"),
    $("confirm-paper-exits"),
  ];
  const message = $("paper-session-action-message");
  for (const button of buttons) {
    button.disabled = true;
  }
  message.className = "action-message running";
  message.textContent = runningText;

  try {
    const response = await fetch(url, { method: "POST", cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Paper session action failed: ${response.status}`);
    }

    renderState(payload.state);
    message.className = "action-message success";
    message.textContent = payload.message;
    await showReport("paper_session");
  } catch (error) {
    message.className = "action-message failure";
    message.textContent = error.message;
  } finally {
    for (const button of buttons) {
      button.disabled = false;
    }
  }
}

async function refresh() {
  if (stateRefreshInFlight) return;
  stateRefreshInFlight = true;
  $("refresh-button").disabled = true;
  updateAutoRefreshStatus("Checking latest app state...");
  try {
    const state = await loadState();
    renderState(state);
    updateAutoRefreshStatus(
      `Last checked ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}. App state generated ${state.app_health?.generated_at_et || state.generated_at_et || "unknown"}.`,
    );
  } catch (error) {
    setText("verdict", error.message);
    setText("safety-line", "Run python run_system_state.py, then refresh this app.");
    updateAutoRefreshStatus(`Auto-refresh failed: ${error.message}`);
  } finally {
    $("refresh-button").disabled = false;
    stateRefreshInFlight = false;
  }
}

$("refresh-button").addEventListener("click", refresh);
$("enable-alerts").addEventListener("click", async () => {
  alertsEnabled = true;
  for (const kind of ["entry", "exit"]) {
    const audio = alertAudio(kind);
    if (!audio) continue;
    try {
      audio.volume = 0.8;
      await audio.load?.();
    } catch {
      // Loading can fail while placeholder audio files are still absent.
    }
  }
  updateNotificationPanel("armed", "Alerts enabled", "Entry and exit alert sounds are armed for this dashboard session.");
});
$("command-primary-action").addEventListener("click", () => {
  const button = $("command-primary-action");
  if (button.dataset.action === "refresh-webull") {
    runWebullRefreshAction();
    return;
  }
  if (button.dataset.action === "premarket") {
    runPremarketCheckAction();
    return;
  }
  if (button.dataset.target) {
    window.location.hash = button.dataset.target;
  }
});
$("run-refresh-status").addEventListener("click", runRefreshStatusAction);
$("run-webull-refresh").addEventListener("click", runWebullRefreshAction);
$("run-premarket-check").addEventListener("click", runPremarketCheckAction);
$("run-paper-session-preview").addEventListener("click", () =>
  runPaperSessionAction(paperSessionPreviewActionUrl, "Running local paper preview cycle..."),
);
$("terminal-chart").addEventListener("click", () => {
  window.open($("terminal-expand-chart").href, "_blank", "noopener");
});
$("confirm-paper-entry").addEventListener("click", () =>
  runPaperSessionAction(paperSessionConfirmEntryActionUrl, "Confirming eligible local paper entries..."),
);
$("confirm-paper-exits").addEventListener("click", () =>
  runPaperSessionAction(paperSessionConfirmExitsActionUrl, "Confirming completed local paper exits..."),
);
$("replay-prev").addEventListener("click", () => {
  moveWithinReplaySession(-1);
});
$("replay-next").addEventListener("click", () => {
  moveWithinReplaySession(1);
});
$("replay-reveal").addEventListener("click", () => {
  if (!replayCards.length) return;
  saveCurrentReplayNote();
  const card = replayCards[replayIndex];
  const entry = replayJournalEntry(card);
  if (!entry.decision || (!replayPracticeFinished && !replayLatestChart?.management_complete)) return;
  if (!replayPracticeFinished) {
    recordManagementAction("held_to_historical_exit", {
      marked_price: replayLatestChart?.current_price ?? null,
      unrealized_r: replayLatestChart?.current_r ?? null,
    });
  }
  entry.outcome_reviewed = true;
  entry.reviewed_at = new Date().toISOString();
  replayJournal[replayCardKey(card)] = entry;
  saveReplayJournal();
  replayOutcomeRevealed = true;
  renderReplayFilterOptions();
  updateReplayJournalSummary();
  renderReplayCard();
});
$("replay-start-management").addEventListener("click", () => {
  const card = replayCards[replayIndex];
  if (!card) return;
  saveCurrentReplayNote();
  const entry = replayJournalEntry(card);
  if (!entry.decision || replayOutcomeRevealed) return;
  entry.management_actions = [{ action: "start", step: 0, recorded_at: new Date().toISOString() }];
  delete entry.practice_exit_action;
  delete entry.practice_exit_price;
  delete entry.practice_exit_r;
  replayJournal[replayCardKey(card)] = entry;
  saveReplayJournal();
  replayManagementStep = 0;
  replayLatestChart = null;
  replayPracticeFinished = false;
  renderReplayCard();
});
$("replay-hold").addEventListener("click", () => {
  if (replayManagementStep === null || replayOutcomeRevealed || replayPracticeFinished) return;
  recordManagementAction("hold", {
    marked_price: replayLatestChart?.current_price ?? null,
    unrealized_r: replayLatestChart?.current_r ?? null,
  });
  replayManagementStep += 1;
  replayLatestChart = null;
  renderReplayCard();
});
$("replay-exit-here").addEventListener("click", () => {
  const card = replayCards[replayIndex];
  if (!card || !replayLatestChart?.step || replayOutcomeRevealed || replayPracticeFinished) return;
  const entry = replayJournalEntry(card);
  entry.practice_exit_action = "exit_here";
  entry.practice_exit_price = replayLatestChart.current_price;
  entry.practice_exit_r = replayLatestChart.current_r;
  replayJournal[replayCardKey(card)] = entry;
  recordManagementAction("exit_here", {
    marked_price: replayLatestChart.current_price,
    practice_r: replayLatestChart.current_r,
  });
  replayPracticeFinished = true;
  saveReplayJournal();
  renderReplayCard();
});
$("replay-stop-followed").addEventListener("click", () => {
  const card = replayCards[replayIndex];
  if (!card || !replayStopReached(card, replayLatestChart) || replayOutcomeRevealed || replayPracticeFinished) return;
  const entry = replayJournalEntry(card);
  entry.practice_exit_action = "stop_followed";
  entry.practice_exit_price = card.stop;
  entry.practice_exit_r = -1;
  replayJournal[replayCardKey(card)] = entry;
  recordManagementAction("stop_followed", { marked_price: card.stop, practice_r: -1 });
  replayPracticeFinished = true;
  saveReplayJournal();
  renderReplayCard();
});
for (const button of document.querySelectorAll(".replay-decision-buttons button")) {
  button.addEventListener("click", () => {
    const card = replayCards[replayIndex];
    if (!card) return;
    saveCurrentReplayNote();
    const entry = replayJournalEntry(card);
    if (entry.outcome_reviewed) return;
    entry.decision = button.dataset.decision;
    entry.decided_at = new Date().toISOString();
    replayJournal[replayCardKey(card)] = entry;
    const saved = saveReplayJournal();
    updateReplayJournalSummary();
    renderReplayCard();
    $("replay-save-status").textContent = saved
      ? "Decision saved locally. Add a note or reveal the outcome."
      : "Decision available for this page only; browser storage is unavailable.";
  });
}
$("replay-save-note").addEventListener("click", () => {
  saveCurrentReplayNote(true);
});
for (const id of [
  "replay-filter-symbol",
  "replay-filter-setup",
  "replay-filter-grade",
  "replay-filter-result",
  "replay-filter-exit-reason",
]) {
  $(id).addEventListener("change", syncReplayFiltersFromControls);
}
for (const button of document.querySelectorAll(".replay-preset-actions button")) {
  button.addEventListener("click", () => setReplayPreset(button.dataset.replayPreset));
}
$("trade-logger-form").addEventListener("submit", submitTradeLogger);
$("trade-log-refresh").addEventListener("click", loadOpenPaperTrades);
$("trade-log-row").addEventListener("change", syncTradeLoggerForm);
$("pre-entry-reviewed").addEventListener("change", () => {
  if (!activePreEntryKey) return;
  if ($("pre-entry-reviewed").checked) {
    preEntryReviewedKeys.add(activePreEntryKey);
  } else {
    preEntryReviewedKeys.delete(activePreEntryKey);
  }
  loadTradingWorkspace();
});
$("ticket-paper-preview").addEventListener("click", () =>
  runPaperSessionAction(paperSessionPreviewActionUrl, "Running local paper preview cycle..."),
);
$("backtest-recalculate-account").addEventListener("click", () => {
  if (selectedBacktestIndex === null) return;
  loadBacktestTrades(selectedBacktestIndex);
});
for (const id of ["backtest-starting-equity", "backtest-risk-pct"]) {
  $(id).addEventListener("change", () => {
    if (selectedBacktestIndex === null) return;
    loadBacktestTrades(selectedBacktestIndex);
  });
}
$("portfolio-recalculate-account").addEventListener("click", loadBacktestPortfolioSimulation);
for (const id of ["portfolio-starting-equity", "portfolio-risk-pct", "portfolio-risk-model"]) {
  $(id).addEventListener("change", loadBacktestPortfolioSimulation);
}
for (const id of ["portfolio-history-symbol", "portfolio-history-year", "portfolio-history-month", "portfolio-history-result", "portfolio-history-sort"]) {
  $(id).addEventListener("change", () => renderPortfolioTradeHistory());
}
$("portfolio-history-search").addEventListener("input", () => renderPortfolioTradeHistory());
$("portfolio-history-clear").addEventListener("click", () => {
  $("portfolio-history-symbol").value = "";
  $("portfolio-history-year").value = "";
  $("portfolio-history-month").value = "";
  $("portfolio-history-result").value = "";
  $("portfolio-history-sort").value = "newest";
  $("portfolio-history-search").value = "";
  renderPortfolioTradeHistory();
});
$("paper-account-recalculate-account").addEventListener("click", () => renderForwardPaperAccount(latestPaperProgress || {}));
for (const id of ["paper-account-starting-equity", "paper-account-risk-pct"]) {
  $(id).addEventListener("change", () => renderForwardPaperAccount(latestPaperProgress || {}));
}
renderReportTabs();
hydrateHelpBubbles();
showReport("dashboard");
updateAppRoute();
window.addEventListener("hashchange", updateAppRoute);
refresh();
loadBacktestPortfolioSimulation();
window.setInterval(refresh, autoRefreshMs);
