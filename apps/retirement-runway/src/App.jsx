import { useMemo, useState, useEffect, useRef } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';


const INK = "#0D1B2A";
const PANEL = "#132844";
const PANEL_2 = "#0F2138";
const GRID = "#25415E";
const PARCHMENT = "#ECE6D6";
const MUTED = "#8FA3B8";
const BRASS = "#C9A24B";
const TEAL = "#5FA8A0";
const RUST = "#C77B5F";

// Ceiling for compounding loops below — with aggressive enough inputs (high return, high raise,
// many years), unclamped compounding can overflow past Number.MAX_VALUE to Infinity, which then
// crashes recharts' tick calculation (and unmounts the whole app, since there's no error boundary
// around the chart). $1 quadrillion is far past any realistic scenario, so clamping here only
// affects already-nonsensical inputs, not real projections.
const MAX_BALANCE = 1e12;

// Ceiling for any loop bounded by user-typed ages/years. Several fields (retirement age,
// horizon age, current age) directly size a simulation loop with no upper bound — an extra
// typed digit (or a value typed transiently while another field is being edited) can turn a
// ~65-iteration loop into a multi-billion-iteration one, freezing the tab synchronously long
// enough to look like a crash. 200 years covers every realistic scenario with huge headroom.
const MAX_YEARS = 200;

// Versioned so a future change to the profile shape can't collide with an old saved blob.
const AUTOSAVE_KEY = "retirement-runway:autosave-v1";

const RETIRE_CHIPS = [55, 60, 65];
const TREATMENTS = ["Roth (after-tax)", "Traditional (pre-tax)", "Triple tax-advantaged", "Taxable"];
const ACCOUNT_TYPES = [
  { key: "401k", label: "401k / 403b / 457", limit: 24500 },
  { key: "ira", label: "IRA (Roth or Traditional)", limit: 7500 },
  { key: "hsa", label: "HSA", limit: null }, // resolved via hsaCoverage below
  { key: "other", label: "Taxable / other (no limit)", limit: null },
];

const DEFAULT_ACCOUNTS = [
  { id: "a1", label: "401k", monthly: 0, treatment: "Roth (after-tax)", type: "401k" },
];

const DEFAULT_EXPENSES = [
  { id: "e1", label: "Groceries", monthly: 0 },
  { id: "e2", label: "Eating out", monthly: 0 },
  { id: "e3", label: "Fun / entertainment", monthly: 0 },
  { id: "e4", label: "Utilities", monthly: 0 },
  { id: "e5", label: "Property tax", monthly: 0 },
  { id: "e6", label: "Home insurance", monthly: 0 },
  { id: "e7", label: "Travel", monthly: 0 },
  { id: "e8", label: "Home maintenance", monthly: 0 },
  { id: "e9", label: "Auto", monthly: 0 },
  { id: "e10", label: "Personal / misc", monthly: 0 },
];

function fmtMoney(n, compact = false) {
  if (!isFinite(n)) return "$0";
  const v = Math.round(n);
  if (compact && Math.abs(v) >= 1000) return "$" + (v / 1000).toLocaleString(undefined, { maximumFractionDigits: 0 }) + "k";
  return "$" + v.toLocaleString();
}
function fmtPct(n) { return `${n.toFixed(2)}%`; }
function toReal(nominalPct, inflationPct) { return ((1 + nominalPct / 100) / (1 + inflationPct / 100) - 1) * 100; }
function toNominal(realPct, inflationPct) { return ((1 + realPct / 100) * (1 + inflationPct / 100) - 1) * 100; }

// monthly compounding: contributions arrive monthly, rate applied monthly — matches how
// real accounts (and most other calculators) actually work, rather than one lump sum per year
// monthly compounding: contributions arrive monthly, rate applied monthly — matches how
// real accounts (and most other calculators) actually work, rather than one lump sum per year.
// Raises can "mature" (slow down) after a set number of years, salary can be capped, and
// contributions can optionally stop entirely at a chosen year (a manual coast scenario).
function simulateRaiseSchedule({
  currentBalance, salary, raisePct, matureRaisePct = null, raiseSlowdownYears = null, salaryCap = null,
  startContribution, raiseAllocationPct, realPreReturn, years, stopContributingYear = Infinity,
}) {
  years = Math.min(Math.max(Math.trunc(years) || 0, 0), MAX_YEARS);
  const monthlyRate = realPreReturn / 100 / 12;
  let balance = currentBalance;
  let sal = salary;
  let annualContribution = startContribution;
  const points = [{ t: 0, balance }];
  for (let y = 0; y < years; y++) {
    const monthlyContribution = (y < stopContributingYear ? annualContribution : 0) / 12;
    for (let m = 0; m < 12; m++) {
      balance = Math.min(balance * (1 + monthlyRate) + monthlyContribution, MAX_BALANCE);
    }
    const effectiveRaisePct = raiseSlowdownYears !== null && y >= raiseSlowdownYears ? matureRaisePct : raisePct;
    const raiseAmt = sal * (effectiveRaisePct / 100);
    if (y < stopContributingYear) annualContribution += raiseAmt * (raiseAllocationPct / 100);
    sal += raiseAmt;
    if (salaryCap && salaryCap > 0) sal = Math.min(sal, salaryCap);
    points.push({ t: y + 1, balance });
  }
  return { finalBalance: balance, points };
}

function simulateFlatSchedule({ currentBalance, flatAnnual, realPreReturn, years }) {
  years = Math.min(Math.max(Math.trunc(years) || 0, 0), MAX_YEARS);
  const monthlyRate = realPreReturn / 100 / 12;
  let balance = currentBalance;
  const monthlyContribution = flatAnnual / 12;
  for (let y = 0; y < years; y++) {
    for (let m = 0; m < 12; m++) balance = Math.min(balance * (1 + monthlyRate) + monthlyContribution, MAX_BALANCE);
  }
  return balance;
}

function solveForTarget(fn, lo, hi, target, iterations = 60) {
  let a = lo, b = hi;
  if (fn(a) >= target) return a;
  if (fn(b) <= target) return b;
  for (let i = 0; i < iterations; i++) {
    const mid = (a + b) / 2;
    if (fn(mid) < target) a = mid; else b = mid;
  }
  return (a + b) / 2;
}

// Research-based "retirement spending smile" (Blanchett 2014; Stein's go-go/slow-go/no-go phases):
// real spending holds steady through the active "go-go" years, declines through the "slow-go" years
// as activity naturally drops, bottoms out around the mid-80s, then ticks back up as healthcare/care
// costs rise in the "no-go" years. Age bands are fixed (research indexes by age, not years retired).
function spendingSmileFactor(age) {
  if (age < 75) return 1.0; // go-go
  if (age <= 84) return 1.0 - 0.025 * (age - 74); // slow-go: ~2.5%/yr real decline, ~25% trough by 84
  return Math.min(0.75 + 0.01 * (age - 84), 0.9); // no-go: ticks back up, healthcare-driven, capped
}

// single trajectory: withdraw a % of current (start-of-year) balance, paid out monthly, rest grows monthly
function simulateDrawdown({ portfolioAtRetirement, retireAge, horizonAge, realPostReturn, withdrawalRate, useSmile }) {
  const monthlyRate = realPostReturn / 100 / 12;
  let val = portfolioAtRetirement;
  const rows = [];
  const span = Math.min(Math.max(Math.trunc(horizonAge) - Math.trunc(retireAge), -1), MAX_YEARS);
  const lastAge = retireAge + span;
  for (let age = retireAge; age <= lastAge; age++) {
    rows.push({ age, balance: Math.max(val, 0) });
    const smile = useSmile ? spendingSmileFactor(age) : 1;
    const monthlyWithdrawal = (val * (withdrawalRate / 100) * smile) / 12;
    for (let m = 0; m < 12; m++) {
      val = Math.min(val * (1 + monthlyRate) - monthlyWithdrawal, MAX_BALANCE);
    }
  }
  return { rows, annualIncome: portfolioAtRetirement * (withdrawalRate / 100) };
}

let idCounter = 1000;

// Simplified Social Security estimate using the actual SSA bend-point formula (2026 figures).
// Approximates AIME from the projected salary path, capped at the taxable wage base, zero-filling
// any of the 35 computation years not actually worked (realistic for early retirees).
const SS_TAXABLE_MAX = 184500; // 2026
const SS_BEND_1 = 1286; // 2026
const SS_BEND_2 = 7749; // 2026
const SS_FRA = 67;

function estimateSocialSecurity({ currentAge, retireAge, salary, raisePct, claimAge, priorWorkingYears, priorAvgSalary }) {
  const futureWorkingYearsRaw = Math.max(retireAge - currentAge, 0);
  const futureYearsUsed = Math.min(futureWorkingYearsRaw, 35);
  const remainingSlots = Math.max(35 - futureYearsUsed, 0);
  const priorYearsUsed = Math.min(Math.max(priorWorkingYears, 0), remainingSlots);

  let sal = salary;
  let futureSum = 0;
  for (let y = 0; y < futureYearsUsed; y++) {
    futureSum += Math.min(sal, SS_TAXABLE_MAX);
    sal *= 1 + raisePct / 100;
  }
  const priorSum = priorYearsUsed * Math.min(Math.max(priorAvgSalary, 0), SS_TAXABLE_MAX);

  const workingYears = futureYearsUsed + priorYearsUsed;
  const aime = (futureSum + priorSum) / 420; // 35 years * 12 months, zero-fills any years short of 35
  const pia =
    0.9 * Math.min(aime, SS_BEND_1) +
    0.32 * Math.max(0, Math.min(aime, SS_BEND_2) - SS_BEND_1) +
    0.15 * Math.max(0, aime - SS_BEND_2);

  const monthsFromFRA = (claimAge - SS_FRA) * 12;
  let factor;
  if (monthsFromFRA >= 0) {
    factor = 1 + Math.min(monthsFromFRA, 36) * (2 / 3 / 100); // up to 8%/yr delayed credit to 70
  } else {
    const monthsEarly = -monthsFromFRA;
    const first36 = Math.min(monthsEarly, 36) * (5 / 9 / 100);
    const rest = Math.max(0, monthsEarly - 36) * (5 / 12 / 100);
    factor = 1 - (first36 + rest);
  }
  return { monthlyBenefit: pia * factor, aime, pia, workingYears };
}

function RetirementRunwayV4() {
  const [currentAge, setCurrentAge] = useState(30);
  const [uiMode, setUiMode] = useState("basic"); // "basic" | "advanced"
  const [retireAge, setRetireAge] = useState(65);
  const [horizonAge, setHorizonAge] = useState(90);
  const [currentBalance, setCurrentBalance] = useState(0);
  const [salary, setSalary] = useState(75000);
  const [raisePct, setRaisePct] = useState(3);
  const [raiseAllocationPct, setRaiseAllocationPct] = useState(0);
  const [useRaiseSlowdown, setUseRaiseSlowdown] = useState(false);
  const [raiseSlowdownYears, setRaiseSlowdownYears] = useState(15);
  const [matureRaisePct, setMatureRaisePct] = useState(3);
  const [useSalaryCap, setUseSalaryCap] = useState(false);
  const [salaryCap, setSalaryCap] = useState(250000);
  const [useStopContributing, setUseStopContributing] = useState(false);
  const [stopContributingAge, setStopContributingAge] = useState(50);

  const [returnMode, setReturnMode] = useState("nominal");
  const [inflation, setInflation] = useState(3);
  const [preReturnInput, setPreReturnInput] = useState(10);
  const [postReturnInput, setPostReturnInput] = useState(8);
  const [showNominalDollars, setShowNominalDollars] = useState(false);
  const [withdrawalRate, setWithdrawalRate] = useState(4);

  const [targetMode, setTargetMode] = useState("expense");
  const [fixedTarget, setFixedTarget] = useState(2000000);

  const [accounts, setAccounts] = useState(DEFAULT_ACCOUNTS);
  const [expenses, setExpenses] = useState(DEFAULT_EXPENSES);
  const [healthcarePre65, setHealthcarePre65] = useState(0);
  const [healthcarePost65, setHealthcarePost65] = useState(0);

  const [currentMarginalRate, setCurrentMarginalRate] = useState(12);
  const [retirementMarginalRate, setRetirementMarginalRate] = useState(12);

  const [includeSS, setIncludeSS] = useState(false);
  const [ssClaimAge, setSsClaimAge] = useState(67);
  const [ssOverrideMonthly, setSsOverrideMonthly] = useState(null); // null = auto-estimate
  const [priorWorkingYears, setPriorWorkingYears] = useState(0);
  const [priorAvgSalary, setPriorAvgSalary] = useState(salary);
  const [hsaCoverage, setHsaCoverage] = useState("family");
  const [useSpendingSmile, setUseSpendingSmile] = useState(false);
  const [capGainsRate, setCapGainsRate] = useState(15);
  const [taxableGainsFraction, setTaxableGainsFraction] = useState(50);
  const [stateTaxRate, setStateTaxRate] = useState(0);
  const [ssTaxablePct, setSsTaxablePct] = useState(85);

  // Persistence: fully self-contained, no account or backend calls of any kind. Two layers:
  // a debounced localStorage autosave (this browser only, survives refresh/crash, no action
  // needed) and an explicit shareable link (works across devices/browsers, only updates when
  // you tap "Copy shareable link" below). A link in the URL always wins over the local save.
  const hydrated = useRef(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const saveTimer = useRef(null);

  const applyProfile = (p) => {
    if (p.currentAge !== undefined) setCurrentAge(p.currentAge);
    if (p.uiMode !== undefined) setUiMode(p.uiMode);
    if (p.retireAge !== undefined) setRetireAge(p.retireAge);
    if (p.horizonAge !== undefined) setHorizonAge(p.horizonAge);
    if (p.currentBalance !== undefined) setCurrentBalance(p.currentBalance);
    if (p.salary !== undefined) setSalary(p.salary);
    if (p.raisePct !== undefined) setRaisePct(p.raisePct);
    if (p.raiseAllocationPct !== undefined) setRaiseAllocationPct(p.raiseAllocationPct);
    if (p.useRaiseSlowdown !== undefined) setUseRaiseSlowdown(p.useRaiseSlowdown);
    if (p.raiseSlowdownYears !== undefined) setRaiseSlowdownYears(p.raiseSlowdownYears);
    if (p.matureRaisePct !== undefined) setMatureRaisePct(p.matureRaisePct);
    if (p.useSalaryCap !== undefined) setUseSalaryCap(p.useSalaryCap);
    if (p.salaryCap !== undefined) setSalaryCap(p.salaryCap);
    if (p.useStopContributing !== undefined) setUseStopContributing(p.useStopContributing);
    if (p.stopContributingAge !== undefined) setStopContributingAge(p.stopContributingAge);
    if (p.returnMode !== undefined) setReturnMode(p.returnMode);
    if (p.inflation !== undefined) setInflation(p.inflation);
    if (p.preReturnInput !== undefined) setPreReturnInput(p.preReturnInput);
    if (p.postReturnInput !== undefined) setPostReturnInput(p.postReturnInput);
    if (p.showNominalDollars !== undefined) setShowNominalDollars(p.showNominalDollars);
    if (p.withdrawalRate !== undefined) setWithdrawalRate(p.withdrawalRate);
    if (p.targetMode !== undefined) setTargetMode(p.targetMode);
    if (p.fixedTarget !== undefined) setFixedTarget(p.fixedTarget);
    if (p.accounts !== undefined) setAccounts(p.accounts);
    if (p.expenses !== undefined) setExpenses(p.expenses);
    if (p.healthcarePre65 !== undefined) setHealthcarePre65(p.healthcarePre65);
    if (p.healthcarePost65 !== undefined) setHealthcarePost65(p.healthcarePost65);
    if (p.currentMarginalRate !== undefined) setCurrentMarginalRate(p.currentMarginalRate);
    if (p.retirementMarginalRate !== undefined) setRetirementMarginalRate(p.retirementMarginalRate);
    if (p.includeSS !== undefined) setIncludeSS(p.includeSS);
    if (p.ssClaimAge !== undefined) setSsClaimAge(p.ssClaimAge);
    if (p.ssOverrideMonthly !== undefined) setSsOverrideMonthly(p.ssOverrideMonthly);
    if (p.priorWorkingYears !== undefined) setPriorWorkingYears(p.priorWorkingYears);
    if (p.priorAvgSalary !== undefined) setPriorAvgSalary(p.priorAvgSalary);
    if (p.hsaCoverage !== undefined) setHsaCoverage(p.hsaCoverage);
    if (p.useSpendingSmile !== undefined) setUseSpendingSmile(p.useSpendingSmile);
    if (p.capGainsRate !== undefined) setCapGainsRate(p.capGainsRate);
    if (p.taxableGainsFraction !== undefined) setTaxableGainsFraction(p.taxableGainsFraction);
    if (p.stateTaxRate !== undefined) setStateTaxRate(p.stateTaxRate);
    if (p.ssTaxablePct !== undefined) setSsTaxablePct(p.ssTaxablePct);
  };

  const encodeProfile = (obj) => {
    try {
      return btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
    } catch (e) {
      return null;
    }
  };
  const decodeProfile = (str) => {
    return JSON.parse(decodeURIComponent(escape(atob(str))));
  };

  const buildShareUrl = () => {
    const encoded = encodeProfile(profileSnapshot);
    if (!encoded) return null;
    const url = new URL(window.location.href);
    url.searchParams.set("d", encoded);
    return url.toString();
  };

  const [shareUrlDisplay, setShareUrlDisplay] = useState(null);

  const copyShareLink = async () => {
    const url = buildShareUrl();
    if (!url) return;
    setShareUrlDisplay(url); // always show it — don't depend on clipboard permissions working
    try {
      await navigator.clipboard.writeText(url);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch (e) {
      // clipboard blocked (common in sandboxed previews) — the visible box below still works
    }
  };

  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const d = params.get("d");
      if (d) {
        applyProfile(decodeProfile(d)); // a shareable link with state baked in — takes priority
      } else {
        const saved = localStorage.getItem(AUTOSAVE_KEY);
        if (saved) applyProfile(JSON.parse(saved)); // no link — fall back to this browser's last save
      }
    } catch (e) {
      // bad link or corrupted local save — start fresh
    }
    hydrated.current = true;
  }, []);

  const profileSnapshot = {
    currentAge, uiMode, retireAge, horizonAge, currentBalance, salary, raisePct, raiseAllocationPct,
    useRaiseSlowdown, raiseSlowdownYears, matureRaisePct, useSalaryCap, salaryCap, useStopContributing, stopContributingAge,
    returnMode, inflation, preReturnInput, postReturnInput, showNominalDollars, withdrawalRate,
    targetMode, fixedTarget, accounts, expenses, healthcarePre65, healthcarePost65,
    currentMarginalRate, retirementMarginalRate, includeSS, ssClaimAge, ssOverrideMonthly,
    priorWorkingYears, priorAvgSalary, hsaCoverage, useSpendingSmile, capGainsRate,
    taxableGainsFraction, stateTaxRate, ssTaxablePct,
  };

  // Autosave to localStorage, debounced so rapid typing doesn't hit disk on every keystroke.
  // Deliberately not the URL — silently rewriting the address bar on every keystroke turned out
  // to conflict with how the published page is hosted (it triggered blank-page reloads and lost
  // edits). The URL only changes when you explicitly hit "Copy shareable link" below.
  useEffect(() => {
    if (!hydrated.current) return; // don't clobber a saved profile with defaults before hydration runs
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      try {
        localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(profileSnapshot));
      } catch (e) {
        // storage unavailable/full (e.g. private browsing) — silently skip, same as the
        // clipboard fallback above
      }
    }, 400);
    return () => clearTimeout(saveTimer.current);
  }, [profileSnapshot]);

  const years = Math.max(Number(retireAge) - Number(currentAge), 0);


  const realPreReturn = returnMode === "real" ? Number(preReturnInput) : toReal(Number(preReturnInput), Number(inflation));
  const realPostReturn = returnMode === "real" ? Number(postReturnInput) : toReal(Number(postReturnInput), Number(inflation));
  const nominalPreDisplay = returnMode === "nominal" ? Number(preReturnInput) : toNominal(Number(preReturnInput), Number(inflation));
  const nominalPostDisplay = returnMode === "nominal" ? Number(postReturnInput) : toNominal(Number(postReturnInput), Number(inflation));

  const currentAnnualContribution = accounts.reduce((s, a) => s + Number(a.monthly || 0), 0) * 12;
  const currentMonthlyContribution = currentAnnualContribution / 12;

  const expenseMonthlyBase = expenses.reduce((s, e) => s + Number(e.monthly || 0), 0);
  const expensePre65 = (expenseMonthlyBase + Number(healthcarePre65)) * 12;
  const expensePost65 = (expenseMonthlyBase + Number(healthcarePost65)) * 12;

  const careerParams = {
    matureRaisePct: useRaiseSlowdown ? Number(matureRaisePct) : null,
    raiseSlowdownYears: useRaiseSlowdown ? Number(raiseSlowdownYears) : null,
    salaryCap: useSalaryCap ? Number(salaryCap) : null,
  };
  const stopContributingYear = useStopContributing ? Math.max(Number(stopContributingAge) - Number(currentAge), 0) : Infinity;

  const schedule = useMemo(
    () => simulateRaiseSchedule({
      currentBalance: Number(currentBalance), salary: Number(salary), raisePct: Number(raisePct),
      startContribution: currentAnnualContribution, raiseAllocationPct: Number(raiseAllocationPct), realPreReturn, years,
      ...careerParams, stopContributingYear,
    }),
    [currentBalance, salary, raisePct, currentAnnualContribution, raiseAllocationPct, realPreReturn, years, useRaiseSlowdown, raiseSlowdownYears, matureRaisePct, useSalaryCap, salaryCap, stopContributingYear]
  );

  const target = targetMode === "fixed" ? Number(fixedTarget) : expensePre65 / (Math.max(Number(withdrawalRate), 0.1) / 100);

  const draw = useMemo(
    () => simulateDrawdown({
      portfolioAtRetirement: schedule.finalBalance, retireAge: Number(retireAge), horizonAge: Number(horizonAge),
      realPostReturn, withdrawalRate: Number(withdrawalRate), useSmile: useSpendingSmile,
    }),
    [schedule.finalBalance, retireAge, horizonAge, realPostReturn, withdrawalRate, useSpendingSmile]
  );

  const requiredRaiseAllocation = useMemo(() => {
    const fn = (pct) => simulateRaiseSchedule({
      currentBalance: Number(currentBalance), salary: Number(salary), raisePct: Number(raisePct),
      startContribution: currentAnnualContribution, raiseAllocationPct: pct, realPreReturn, years,
      ...careerParams, stopContributingYear,
    }).finalBalance;
    return solveForTarget(fn, 0, 100, target);
  }, [currentBalance, salary, raisePct, currentAnnualContribution, realPreReturn, years, target, useRaiseSlowdown, raiseSlowdownYears, matureRaisePct, useSalaryCap, salaryCap, stopContributingYear]);

  const requiredFlatMonthly = useMemo(() => {
    const fn = (flatMonthly) => simulateFlatSchedule({ currentBalance: Number(currentBalance), flatAnnual: flatMonthly * 12, realPreReturn, years });
    return solveForTarget(fn, 0, 30000, target);
  }, [currentBalance, realPreReturn, years, target]);

  const dv = (val, age) => {
    if (!showNominalDollars) return val;
    const factor = Math.pow(1 + Number(inflation) / 100, Math.max(age - Number(currentAge), 0));
    return val * factor;
  };

  const chartData = useMemo(() => {
    const map = new Map();
    schedule.points.forEach((p) => map.set(Number(currentAge) + p.t, { age: Number(currentAge) + p.t, balance: p.balance }));
    draw.rows.forEach((p) => map.set(p.age, { age: p.age, balance: p.balance }));
    return Array.from(map.values()).sort((a, b) => a.age - b.age).map((p) => ({
      age: p.age,
      balance: Math.round(dv(p.balance, p.age)),
      target: Math.round(dv(target, p.age)),
    }));
  }, [schedule, draw, currentAge, showNominalDollars, inflation, target]);

  const ageComparison = useMemo(() => {
    return RETIRE_CHIPS.map((age) => {
      const yrs = Math.max(age - Number(currentAge), 0);
      const s = simulateRaiseSchedule({
        currentBalance: Number(currentBalance), salary: Number(salary), raisePct: Number(raisePct),
        startContribution: currentAnnualContribution, raiseAllocationPct: Number(raiseAllocationPct), realPreReturn, years: yrs,
        ...careerParams, stopContributingYear,
      });
      return { age, balance: s.finalBalance, gap: s.finalBalance - target };
    });
  }, [currentAge, currentBalance, salary, raisePct, currentAnnualContribution, raiseAllocationPct, realPreReturn, target, useRaiseSlowdown, raiseSlowdownYears, matureRaisePct, useSalaryCap, salaryCap, stopContributingYear]);

  const gap = schedule.finalBalance - target;
  const rothAdvantagePct = ((1 - Number(currentMarginalRate) / 100) / (1 - Number(retirementMarginalRate) / 100) - 1) * 100;

  const breakEvenRate = realPostReturn;
  const rateDelta = Number(withdrawalRate) - breakEvenRate;

  // Social Security
  const ssEstimate = useMemo(
    () => estimateSocialSecurity({
      currentAge: Number(currentAge), retireAge: Number(retireAge), salary: Number(salary),
      raisePct: Number(raisePct), claimAge: Number(ssClaimAge),
      priorWorkingYears: Number(priorWorkingYears), priorAvgSalary: Number(priorAvgSalary),
    }),
    [currentAge, retireAge, salary, raisePct, ssClaimAge, priorWorkingYears, priorAvgSalary]
  );
  const ssMonthly = ssOverrideMonthly !== null ? Number(ssOverrideMonthly) : ssEstimate.monthlyBenefit;

  // withdrawal income: annual + monthly at retirement, and sampled every 5 years through the drawdown
  const withdrawalAtRetirement = schedule.finalBalance * (Number(withdrawalRate) / 100) * (useSpendingSmile ? spendingSmileFactor(Number(retireAge)) : 1);
  const withdrawalTable = useMemo(() => {
    return draw.rows
      .filter((r) => (r.age - Number(retireAge)) % 5 === 0)
      .map((r) => ({
        age: r.age,
        balance: r.balance,
        annualWithdrawal: r.balance * (Number(withdrawalRate) / 100) * (useSpendingSmile ? spendingSmileFactor(r.age) : 1),
        ssAnnual: includeSS && r.age >= Number(ssClaimAge) ? ssMonthly * 12 : 0,
      }));
  }, [draw, retireAge, withdrawalRate, includeSS, ssClaimAge, ssMonthly, useSpendingSmile]);

  // FIRE / Coast FIRE
  const fiNumber = target; // same "25x-style" number, using the chosen withdrawal rate instead of hardcoding 4%
  const yearsToRetire = years;

  const coastFiNumber = fiNumber / Math.pow(1 + realPreReturn / 100, yearsToRetire);
  const alreadyCoastFI = Number(currentBalance) >= coastFiNumber;

  const earliestFireAge = useMemo(() => {
    // clamped to 0: a very negative typed currentAge would otherwise start this loop far below
    // zero and iterate hundreds of millions of times before reaching the fixed 80 upper bound.
    const startAge = Math.max(Number(currentAge) + 1, 0);
    for (let age = startAge; age <= 80; age++) {
      const s = simulateRaiseSchedule({
        currentBalance: Number(currentBalance), salary: Number(salary), raisePct: Number(raisePct),
        startContribution: currentAnnualContribution, raiseAllocationPct: Number(raiseAllocationPct), realPreReturn, years: age - Number(currentAge),
        ...careerParams, stopContributingYear,
      });
      if (s.finalBalance >= fiNumber) return age;
    }
    return null;
  }, [currentAge, currentBalance, salary, raisePct, currentAnnualContribution, raiseAllocationPct, realPreReturn, fiNumber, useRaiseSlowdown, raiseSlowdownYears, matureRaisePct, useSalaryCap, salaryCap, stopContributingYear]);

  const coastFireAge = useMemo(() => {
    // total trip count clamped to MAX_YEARS regardless of how extreme currentAge/retireAge are
    // individually — an unbounded typed retireAge would otherwise iterate this loop (each step
    // itself running a full simulation) an arbitrarily large number of times.
    const startAge = Number(currentAge);
    const span = Math.min(Math.max(Math.trunc(Number(retireAge)) - Math.trunc(startAge), -1), MAX_YEARS);
    const endAge = startAge + span;
    for (let age = startAge; age <= endAge; age++) {
      const s = simulateRaiseSchedule({
        currentBalance: Number(currentBalance), salary: Number(salary), raisePct: Number(raisePct),
        startContribution: currentAnnualContribution, raiseAllocationPct: Number(raiseAllocationPct), realPreReturn, years: age - Number(currentAge),
        ...careerParams, stopContributingYear,
      });
      const coastedToRetirement = s.finalBalance * Math.pow(1 + realPreReturn / 100, Number(retireAge) - age);
      if (coastedToRetirement >= target) return age;
    }
    return null;
  }, [currentAge, retireAge, currentBalance, salary, raisePct, currentAnnualContribution, raiseAllocationPct, realPreReturn, target, useRaiseSlowdown, raiseSlowdownYears, matureRaisePct, useSalaryCap, salaryCap, stopContributingYear]);

  // Withdrawal order: group accounts by tax treatment present, suggest a standard sequence
  const withdrawalOrderGroups = useMemo(() => {
    const has = (t) => accounts.some((a) => a.treatment === t);
    const order = [];
    if (has("Taxable")) order.push({ label: "Taxable brokerage", why: "Lowest tax cost first (often long-term capital gains rates), and it lets everything else keep compounding." });
    if (has("Traditional (pre-tax)")) order.push({ label: "Traditional accounts", why: "Draw enough to fill up your lower tax brackets each year, before jumping to a higher one." });
    if (has("Triple tax-advantaged")) order.push({ label: "HSA", why: "Reimburse medical costs tax-free any time; after 65 it behaves like a Traditional account for non-medical spending." });
    if (has("Roth (after-tax)")) order.push({ label: "Roth accounts", why: "Draw last — tax-free growth compounds longest, and it's the most flexible bucket for a legacy or big one-off expense." });
    return order;
  }, [accounts]);
  const hasTraditional = accounts.some((a) => a.treatment === "Traditional (pre-tax)");

  // Account tax-treatment mix, approximated from current contribution proportions —
  // the calculator only tracks one blended portfolio balance, not per-account balances,
  // so this assumes the mix of money going in roughly matches the mix coming out.
  const accountMix = useMemo(() => {
    const total = accounts.reduce((s, a) => s + Number(a.monthly || 0), 0) || 1;
    const pct = (treatment) => accounts.filter((a) => a.treatment === treatment).reduce((s, a) => s + Number(a.monthly || 0), 0) / total;
    return {
      roth: pct("Roth (after-tax)"),
      traditional: pct("Traditional (pre-tax)"),
      hsa: pct("Triple tax-advantaged"),
      taxable: pct("Taxable"),
    };
  }, [accounts]);

  const afterTaxBreakdown = useMemo(() => {
    const gross = withdrawalAtRetirement;
    const rothAmt = gross * accountMix.roth;
    const traditionalAmt = gross * accountMix.traditional;
    const hsaAmt = gross * accountMix.hsa;
    const taxableAmt = gross * accountMix.taxable;

    const ordinaryRate = Number(retirementMarginalRate) / 100 + Number(stateTaxRate) / 100;
    const capGainsCombined = Number(capGainsRate) / 100 + Number(stateTaxRate) / 100;

    const traditionalTax = traditionalAmt * ordinaryRate;
    const taxableTax = taxableAmt * (Number(taxableGainsFraction) / 100) * capGainsCombined;
    const ssGross = includeSS ? ssMonthly * 12 : 0;
    const ssTax = ssGross * (Number(ssTaxablePct) / 100) * ordinaryRate;

    const totalTax = traditionalTax + taxableTax + ssTax;
    const totalGrossWithSS = gross + ssGross;
    const netAfterTax = totalGrossWithSS - totalTax;

    return { rothAmt, traditionalAmt, hsaAmt, taxableAmt, traditionalTax, taxableTax, ssGross, ssTax, totalTax, totalGrossWithSS, netAfterTax };
  }, [withdrawalAtRetirement, accountMix, retirementMarginalRate, stateTaxRate, capGainsRate, taxableGainsFraction, includeSS, ssMonthly, ssTaxablePct]);

  // Sequence-of-returns risk: same average return, different order — compare constant vs bad-years-first vs bad-years-last
  const [badYearsCount, setBadYearsCount] = useState(5);
  const [badYearReturn, setBadYearReturn] = useState(-10);
  const sequenceComparison = useMemo(() => {
    // clamped to [0, MAX_YEARS]: a negative n would send Array(n) below a negative length and
    // throw (e.g. retireAge transiently exceeding horizonAge mid-edit); an uncapped upper bound
    // (e.g. a huge typed horizonAge) would instead build multi-hundred-million-element arrays
    // below and iterate over them, freezing the tab without ever throwing.
    const n = Math.min(Math.max(Number(horizonAge) - Number(retireAge) + 1, 0), MAX_YEARS);
    const bn = Math.min(Math.max(Number(badYearsCount), 0), n);
    const avg = realPostReturn;
    const bad = Number(badYearReturn);
    // solve the "catch-up" rate for the remaining years so the geometric average matches the baseline
    const catchUp = n > bn
      ? (Math.pow(1 + avg / 100, n) / Math.pow(1 + bad / 100, bn) - 1) > -1
        ? (Math.pow(Math.pow(1 + avg / 100, n) / Math.pow(1 + bad / 100, bn), 1 / (n - bn)) - 1) * 100
        : -99
      : avg;

    const runSequence = (rates) => {
      let val = schedule.finalBalance;
      // fixed dollar withdrawal (set at retirement, held constant) — this is what actually exposes
      // sequence risk. A withdrawal rate applied to the *current* balance each year is immune to
      // reordering, since multiplying the same set of growth factors in any order gives the same product.
      const fixedAnnualWithdrawal = schedule.finalBalance * (Number(withdrawalRate) / 100);
      const monthlyWithdrawal = fixedAnnualWithdrawal / 12;
      for (let i = 0; i < rates.length; i++) {
        const monthlyRate = rates[i] / 100 / 12;
        for (let m = 0; m < 12; m++) {
          val = val * (1 + monthlyRate) - monthlyWithdrawal;
          if (val < 0) val = 0;
          if (val > MAX_BALANCE) val = MAX_BALANCE;
        }
      }
      return Math.max(val, 0);
    };

    const badRates = Array(bn).fill(bad).concat(Array(n - bn).fill(catchUp));
    const goodRates = Array(n - bn).fill(catchUp).concat(Array(bn).fill(bad));
    const flatRates = Array(n).fill(avg);

    return {
      badFirst: runSequence(badRates),
      badLast: runSequence(goodRates),
      constant: runSequence(flatRates),
      catchUpRate: catchUp,
    };
  }, [horizonAge, retireAge, realPostReturn, badYearsCount, badYearReturn, schedule.finalBalance, withdrawalRate]);

  // Contribution limit checks
  const contributionLimitChecks = useMemo(() => {
    return accounts.map((a) => {
      const typeInfo = ACCOUNT_TYPES.find((t) => t.key === a.type) || ACCOUNT_TYPES[3];
      const limit = a.type === "hsa" ? (hsaCoverage === "family" ? 8750 : 4400) : typeInfo.limit;
      const annual = Number(a.monthly || 0) * 12;
      return { ...a, limit, annual, overLimit: limit !== null && annual > limit };
    });
  }, [accounts, hsaCoverage]);

  const updateAccount = (id, field, val) => setAccounts((prev) => prev.map((a) => (a.id === id ? { ...a, [field]: val } : a)));
  const addAccount = () => setAccounts((prev) => [...prev, { id: `acc${idCounter++}`, label: "New account", monthly: 0, treatment: "Roth (after-tax)", type: "other" }]);

  const resetToBlank = () => {
    if (!window.confirm("Clear all inputs and start fresh? This can't be undone.")) return;
    setCurrentAge(30); setRetireAge(65); setHorizonAge(90); setCurrentBalance(0); setSalary(75000);
    setRaisePct(3); setRaiseAllocationPct(0); setUseRaiseSlowdown(false); setUseSalaryCap(false); setUseStopContributing(false);
    setReturnMode("nominal"); setInflation(3); setPreReturnInput(10); setPostReturnInput(8); setShowNominalDollars(false);
    setWithdrawalRate(4); setTargetMode("expense"); setFixedTarget(2000000);
    setAccounts([{ id: "blank1", label: "My 401k", monthly: 0, treatment: "Roth (after-tax)", type: "401k" }]);
    setExpenses(DEFAULT_EXPENSES.map((e) => ({ ...e, monthly: 0 })));
    setHealthcarePre65(0); setHealthcarePost65(0);
    setCurrentMarginalRate(12); setRetirementMarginalRate(12);
    setIncludeSS(false); setSsClaimAge(67); setSsOverrideMonthly(null); setPriorWorkingYears(0); setPriorAvgSalary(75000);
    setUseSpendingSmile(false); setCapGainsRate(15); setTaxableGainsFraction(50); setStateTaxRate(0); setSsTaxablePct(85);
    setUiMode("basic");
    // not touching the URL here either — same reasoning as above. If you want to share the
    // blank state, hit "Copy shareable link" afterward to generate a fresh one on demand.
  };
  const removeAccount = (id) => setAccounts((prev) => prev.filter((a) => a.id !== id));

  const updateExpense = (id, field, val) => setExpenses((prev) => prev.map((e) => (e.id === id ? { ...e, [field]: val } : e)));
  const addExpense = () => setExpenses((prev) => [...prev, { id: `exp${idCounter++}`, label: "New category", monthly: 0 }]);
  const removeExpense = (id) => setExpenses((prev) => prev.filter((e) => e.id !== id));

  const [expanded, setExpanded] = useState({
    budget: false, fire: false, tax: false, glossary: false, ss: false, order: false, sequence: false, limits: false, smile: false, afterTax: false,
    ageHorizon: true, salaryRaise: true, accountsPanel: true, returns: true, targetPortfolio: true, intro: true,
  });
  const toggle = (key) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div style={{ minHeight: "100vh", background: INK, color: PARCHMENT, fontFamily: "'Inter', sans-serif" }}>
      <style>{`
        .rr-serif { font-family: 'Fraunces', serif; }
        .rr-mono { font-family: 'IBM Plex Mono', monospace; }
        input[type="number"], input[type="text"], select {
          background: ${PANEL_2}; border: 1px solid ${GRID}; color: ${PARCHMENT};
          border-radius: 3px; padding: 7px 9px; font-family: 'IBM Plex Mono', monospace;
          font-size: 13px; width: 100%; box-sizing: border-box;
        }
        select { font-family: 'Inter', sans-serif; font-size: 12px; }
        input:focus, select:focus { outline: none; border-color: ${BRASS}; }
        .rr-chip { border: 1px solid ${GRID}; background: transparent; color: ${MUTED}; padding: 7px 14px; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 13px; cursor: pointer; }
        .rr-chip:hover { border-color: ${BRASS}; color: ${PARCHMENT}; }
        .rr-chip.active { background: ${BRASS}; border-color: ${BRASS}; color: ${INK}; font-weight: 600; }
        .rr-field-label { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: ${MUTED}; margin-bottom: 5px; display: block; }
        .rr-toggle { border: 1px solid ${GRID}; background: transparent; color: ${MUTED}; padding: 8px 12px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; cursor: pointer; }
        .rr-toggle.active { background: ${TEAL}; border-color: ${TEAL}; color: ${INK}; font-weight: 600; }
        .rr-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid ${GRID}; align-items: center; }
        .rr-row:last-child { border-bottom: none; }
        .rr-section-label { font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: .1em; color: ${MUTED}; margin-bottom: 12px; }
        .rr-collapsible-header {
          font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: .1em; color: ${MUTED};
          margin-bottom: 12px; cursor: pointer; display: flex; align-items: center; justify-content: space-between;
          background: transparent; border: none; width: 100%; padding: 0; text-align: left;
        }
        .rr-collapsible-header:hover { color: ${BRASS}; }
        .rr-caret { font-size: 10px; transition: transform 0.15s ease; }
        .rr-x-btn { background: transparent; border: 1px solid ${GRID}; color: ${RUST}; border-radius: 3px; width: 24px; height: 24px; cursor: pointer; font-size: 13px; line-height: 1; flex-shrink: 0; }
        .rr-x-btn:hover { border-color: ${RUST}; }
        .rr-add-btn { background: transparent; border: 1px dashed ${GRID}; color: ${MUTED}; border-radius: 3px; padding: 8px; width: 100%; cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
        .rr-add-btn:hover { border-color: ${BRASS}; color: ${BRASS}; }
        .rr-expense-row { display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 1px solid ${GRID}; }
        .rr-expense-row:last-child { border-bottom: none; }
        @media (max-width: 780px) { .rr-grid { grid-template-columns: 1fr !important; } }
        .rr-print-summary { display: none; }
        @media print {
          .no-print { display: none !important; }
          .rr-print-summary { display: block !important; background: white !important; color: black !important; }
          .rr-print-summary * { background: white !important; color: black !important; border-color: #ccc !important; }
          .rr-print-summary .rr-brass { color: #7a5c1e !important; font-weight: 700; }
          .rr-print-summary .rr-teal { color: #1f6e64 !important; font-weight: 700; }
        }
      `}</style>

      <div className="no-print">
      <div style={{ borderBottom: `1px solid ${GRID}`, padding: "28px 24px 24px", background: `linear-gradient(180deg, ${PANEL_2} 0%, ${INK} 100%)` }}>
        <div className="no-print" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px", marginBottom: "10px" }}>
          <div className="rr-mono" style={{ fontSize: "11px", letterSpacing: "0.14em", color: BRASS }}>
            RETIREMENT MODEL — LEDGER NO. 04 · SIMPLIFIED
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <div style={{ display: "flex" }}>
              <button className={`rr-toggle ${uiMode === "basic" ? "active" : ""}`} style={{ borderRight: "none", fontSize: "11px", padding: "6px 10px" }} onClick={() => setUiMode("basic")}>Basic</button>
              <button className={`rr-toggle ${uiMode === "advanced" ? "active" : ""}`} style={{ fontSize: "11px", padding: "6px 10px" }} onClick={() => setUiMode("advanced")}>Advanced</button>
            </div>
            <button className="rr-toggle" style={{ fontSize: "11px", padding: "6px 10px" }} onClick={copyShareLink}>
              {linkCopied ? "✓ Link copied!" : "🔗 Copy shareable link"}
            </button>
            <button className="rr-toggle" style={{ fontSize: "11px", padding: "6px 10px" }} onClick={() => window.print()}>📄 Export summary</button>
            <button className="rr-toggle" style={{ fontSize: "11px", padding: "6px 10px", color: RUST, borderColor: RUST }} onClick={resetToBlank}>Start fresh</button>
          </div>
        </div>

        {shareUrlDisplay && (
          <div style={{ border: `1px solid ${BRASS}`, borderRadius: "4px", padding: "10px", marginBottom: "14px", background: PANEL_2, display: "flex", gap: "8px", alignItems: "center" }}>
            <input
              readOnly
              value={shareUrlDisplay}
              onFocus={(e) => e.target.select()}
              className="rr-mono"
              style={{ flex: 1, fontSize: "11px" }}
            />
            <button className="rr-toggle" style={{ fontSize: "11px", padding: "6px 10px", flexShrink: 0 }} onClick={() => setShareUrlDisplay(null)}>Close</button>
          </div>
        )}
        {shareUrlDisplay && (
          <div style={{ fontSize: "11px", color: MUTED, marginTop: "-8px", marginBottom: "14px" }}>
            Tap the link above to select it, then copy manually (⌘/Ctrl+C) — works even if automatic copy is blocked.
          </div>
        )}
        <h1 className="rr-serif" style={{ fontSize: "30px", fontWeight: 600, margin: "0 0 6px 0" }}>
          Retirement Runway
        </h1>
        <p style={{ color: MUTED, fontSize: "14px", margin: 0, maxWidth: "560px" }}>
          One line: your portfolio, growing, then drawing at your chosen withdrawal rate through retirement.
          {uiMode === "basic" && " Basic mode shows the essentials — switch to Advanced for the full toolkit."}
        </p>
        <p className="rr-mono" style={{ color: MUTED, fontSize: "11px", margin: "10px 0 0 0", maxWidth: "560px", lineHeight: 1.6 }}>
          No account needed: your numbers autosave in this browser as you go, so a refresh won't lose them. To pick up
          on another device, or send this to someone, tap "Copy shareable link" — it bakes your current inputs into a
          link you can bookmark or send. Made more edits? Copy a fresh link to capture those too.
        </p>

        <div style={{ marginTop: "22px", display: "flex", gap: "40px", flexWrap: "wrap" }}>
          <div>
            <div className="rr-field-label">Projected at age {retireAge}</div>
            <div className="rr-serif" style={{ fontSize: "36px", fontWeight: 700, color: BRASS, borderBottom: `2px solid ${BRASS}`, display: "inline-block", paddingBottom: "3px", lineHeight: 1 }}>
              {fmtMoney(dv(schedule.finalBalance, Number(retireAge)))}
            </div>
          </div>
          <div>
            <div className="rr-field-label">Target</div>
            <div className="rr-serif" style={{ fontSize: "36px", fontWeight: 700, color: TEAL, borderBottom: `2px solid ${TEAL}`, display: "inline-block", paddingBottom: "3px", lineHeight: 1 }}>
              {fmtMoney(dv(target, Number(retireAge)))}
            </div>
          </div>
          <div>
            <div className="rr-field-label">Gap</div>
            <div className="rr-serif" style={{ fontSize: "36px", fontWeight: 700, color: gap >= 0 ? TEAL : RUST, lineHeight: 1 }}>
              {gap >= 0 ? "+" : ""}{fmtMoney(dv(gap, Number(retireAge)))}
            </div>
          </div>
        </div>
      </div>

      <div className="no-print" style={{ padding: "18px 24px", borderBottom: `1px solid ${GRID}`, background: PANEL }}>
        <button className="rr-collapsible-header" onClick={() => toggle("intro")} style={{ marginBottom: expanded.intro ? "14px" : "0" }}>
          <span>WHAT IS THIS? — TERMS EXPLAINED</span>
          <span className="rr-caret" style={{ transform: expanded.intro ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
        </button>
        {expanded.intro && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "10px 24px" }}>
            {[
              ["Real vs. Nominal", "Real = adjusted for inflation (today's buying power). Nominal = the actual dollar number you'd see, inflation and all."],
              ["Withdrawal rate", "The % of your portfolio you take out each year once retired."],
              ["Break-even rate", "The withdrawal rate that keeps your portfolio flat — matches your investment return exactly."],
              ["Target portfolio", "The amount you're aiming to have saved by retirement."],
              ["Gap", "Projected balance minus target — positive means you're on pace, negative means a shortfall."],
              ["FIRE", "Financial Independence, Retire Early — the age you first reach your full target."],
              ["Coast FIRE", "The age you could stop contributing entirely and still hit your target through growth alone."],
              ["Today's $ vs. Future $", "Today's $ = what it's worth right now. Future $ = the literal number on your statement later, after inflation."],
            ].map(([term, def]) => (
              <div key={term}>
                <div style={{ fontSize: "13px", fontWeight: 600, color: BRASS, marginBottom: "2px" }}>{term}</div>
                <div style={{ fontSize: "12px", color: MUTED, lineHeight: 1.5 }}>{def}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rr-grid" style={{ display: "grid", gridTemplateColumns: "380px 1fr", gap: 0 }}>
        <div style={{ padding: "24px", borderRight: `1px solid ${GRID}`, background: PANEL }}>
          <button className="rr-collapsible-header" onClick={() => toggle("ageHorizon")}>
            <span>AGE &amp; HORIZON</span>
            <span className="rr-caret" style={{ transform: expanded.ageHorizon ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
          </button>
          {!expanded.ageHorizon && (
            <div style={{ fontSize: "11px", color: MUTED, marginBottom: "14px" }} className="rr-mono">
              Age {currentAge} → retire {retireAge} → plan to {horizonAge}
            </div>
          )}
          {expanded.ageHorizon && (
          <>
          <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
            <div style={{ flex: 1 }}><span className="rr-field-label">Current age</span><input type="number" value={currentAge} onChange={(e) => setCurrentAge(e.target.value)} /></div>
            <div style={{ flex: 1 }}><span className="rr-field-label">Plan until</span><input type="number" value={horizonAge} onChange={(e) => setHorizonAge(e.target.value)} /></div>
          </div>
          <div style={{ marginBottom: "20px" }}>
            <span className="rr-field-label">Retirement age</span>
            <div style={{ display: "flex", gap: "6px", marginBottom: "8px" }}>
              {RETIRE_CHIPS.map((age) => (<button key={age} className={`rr-chip ${Number(retireAge) === age ? "active" : ""}`} onClick={() => setRetireAge(age)}>{age}</button>))}
            </div>
            <input type="number" value={retireAge} onChange={(e) => setRetireAge(e.target.value)} placeholder="Custom age" />
          </div>
          </>
          )}

          <button className="rr-collapsible-header" onClick={() => toggle("salaryRaise")}>
            <span>SALARY &amp; RAISE ALLOCATION</span>
            <span className="rr-caret" style={{ transform: expanded.salaryRaise ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
          </button>
          {!expanded.salaryRaise && (
            <div style={{ fontSize: "11px", color: MUTED, marginBottom: "14px" }} className="rr-mono">
              {fmtMoney(Number(salary))} salary · +{raisePct}%/yr raises · {raiseAllocationPct}% of each → retirement
            </div>
          )}
          {expanded.salaryRaise && (
          <>
          <div style={{ marginBottom: "14px" }}>
            <span className="rr-field-label">Current gross salary</span>
            <input type="number" value={salary} onChange={(e) => setSalary(e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
            <div style={{ flex: 1 }}><span className="rr-field-label">Annual raise %</span><input type="number" step="0.1" value={raisePct} onChange={(e) => setRaisePct(e.target.value)} /></div>
            <div style={{ flex: 1 }}><span className="rr-field-label">% of raise → retirement</span><input type="number" step="1" value={raiseAllocationPct} onChange={(e) => setRaiseAllocationPct(e.target.value)} /></div>
          </div>
          <div style={{ marginBottom: "18px" }}>
            <span className="rr-field-label">Current retirement + brokerage balance</span>
            <input type="number" value={currentBalance} onChange={(e) => setCurrentBalance(e.target.value)} />
          </div>

          {uiMode === "advanced" && (
          <>
          <div style={{ borderTop: `1px solid ${GRID}`, paddingTop: "14px", marginBottom: "6px" }}>
            <div style={{ fontSize: "11px", color: MUTED, marginBottom: "10px", lineHeight: 1.6 }}>
              A flat 5%/yr raise for 30+ years straight is optimistic — real careers usually front-load
              growth (promotions, job changes) then plateau. These optional switches model that.
            </div>
          </div>

          <button className={`rr-toggle ${useRaiseSlowdown ? "active" : ""}`} style={{ width: "100%", marginBottom: "8px" }} onClick={() => setUseRaiseSlowdown(!useRaiseSlowdown)}>
            {useRaiseSlowdown ? "Raises slow down ✓" : "Raises stay flat forever — tap to add a slowdown"}
          </button>
          {useRaiseSlowdown && (
            <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
              <div style={{ flex: 1 }}><span className="rr-field-label">Slow down after N years</span><input type="number" value={raiseSlowdownYears} onChange={(e) => setRaiseSlowdownYears(e.target.value)} /></div>
              <div style={{ flex: 1 }}><span className="rr-field-label">Mature raise %/yr after</span><input type="number" step="0.1" value={matureRaisePct} onChange={(e) => setMatureRaisePct(e.target.value)} /></div>
            </div>
          )}

          <button className={`rr-toggle ${useSalaryCap ? "active" : ""}`} style={{ width: "100%", marginBottom: "8px" }} onClick={() => setUseSalaryCap(!useSalaryCap)}>
            {useSalaryCap ? "Salary cap ✓" : "No salary ceiling — tap to cap it"}
          </button>
          {useSalaryCap && (
            <div style={{ marginBottom: "14px" }}>
              <span className="rr-field-label">Salary never exceeds</span>
              <input type="number" value={salaryCap} onChange={(e) => setSalaryCap(e.target.value)} />
            </div>
          )}

          <button className={`rr-toggle ${useStopContributing ? "active" : ""}`} style={{ width: "100%", marginBottom: "8px" }} onClick={() => setUseStopContributing(!useStopContributing)}>
            {useStopContributing ? "Contributions stop early ✓" : "Contribute until retirement — tap to test stopping early"}
          </button>
          {useStopContributing && (
            <>
              <div style={{ marginBottom: "10px" }}>
                <span className="rr-field-label">Stop contributing at age</span>
                <input type="number" value={stopContributingAge} onChange={(e) => setStopContributingAge(e.target.value)} />
              </div>
              <div style={{ fontSize: "11px", color: MUTED, marginBottom: "14px", lineHeight: 1.6 }}>
                This is a manual "what if I stopped at exactly this age" test — compare it against the
                auto-computed Coast FIRE age in the Early Retirement section below, which solves for the
                <em> earliest</em> age you could stop and still hit your target.
              </div>
            </>
          )}
          </>
          )}
          </>
          )}

          <button className="rr-collapsible-header" onClick={() => toggle("accountsPanel")}>
            <span>YOUR ACCOUNTS</span>
            <span className="rr-caret" style={{ transform: expanded.accountsPanel ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
          </button>
          <div style={{ fontSize: "11px", color: MUTED, marginBottom: expanded.accountsPanel ? "10px" : "0" }} className="rr-mono">
            Total: {fmtMoney(currentMonthlyContribution)}/mo · {fmtPct((currentAnnualContribution / Number(salary)) * 100)} of gross
          </div>
          {expanded.accountsPanel && (
          <>
          {accounts.map((a) => (
            <div key={a.id} style={{ border: `1px solid ${GRID}`, borderRadius: "4px", padding: "10px", marginBottom: "8px" }}>
              <div style={{ display: "flex", gap: "6px", marginBottom: "6px" }}>
                <input type="text" value={a.label} onChange={(e) => updateAccount(a.id, "label", e.target.value)} style={{ flex: 1, fontFamily: "Inter", fontSize: "12px" }} />
                <button className="rr-x-btn" onClick={() => removeAccount(a.id)}>×</button>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="rr-mono" style={{ fontSize: "12px", color: MUTED }}>$</span>
                <input type="number" value={a.monthly} onChange={(e) => updateAccount(a.id, "monthly", Number(e.target.value))} />
                <span className="rr-mono" style={{ fontSize: "11px", color: MUTED }}>/mo</span>
              </div>
              <select value={a.treatment} onChange={(e) => updateAccount(a.id, "treatment", e.target.value)} style={{ marginTop: "6px" }}>
                {TREATMENTS.map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
              <select value={a.type} onChange={(e) => updateAccount(a.id, "type", e.target.value)} style={{ marginTop: "6px" }}>
                {ACCOUNT_TYPES.map((t) => (<option key={t.key} value={t.key}>{t.label}</option>))}
              </select>
            </div>
          ))}
          <button className="rr-add-btn" onClick={addAccount}>+ add account</button>
          </>
          )}
        </div>

        <div style={{ padding: "24px" }}>
          <button className="rr-collapsible-header" onClick={() => toggle("returns")}>
            <span>RETURNS &amp; INFLATION</span>
            <span className="rr-caret" style={{ transform: expanded.returns ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
          </button>
          {!expanded.returns && (
            <div style={{ fontSize: "11px", color: MUTED, marginBottom: "16px" }} className="rr-mono">
              {fmtPct(realPreReturn)} real pre-retire · {fmtPct(realPostReturn)} real post-retire · {withdrawalRate}% withdrawal rate
            </div>
          )}
          {expanded.returns && (
          <>
          {uiMode === "advanced" && (
          <div style={{ display: "flex", marginBottom: "10px" }}>
            <button className={`rr-toggle ${returnMode === "nominal" ? "active" : ""}`} style={{ flex: 1, borderRight: "none" }} onClick={() => setReturnMode("nominal")}>Enter as nominal</button>
            <button className={`rr-toggle ${returnMode === "real" ? "active" : ""}`} style={{ flex: 1 }} onClick={() => setReturnMode("real")}>Enter as real</button>
          </div>
          )}
          <div style={{ display: "flex", gap: "10px", marginBottom: "6px" }}>
            <div style={{ flex: 1 }}><span className="rr-field-label">Pre-retire return % ({returnMode})</span><input type="number" step="0.1" value={preReturnInput} onChange={(e) => setPreReturnInput(e.target.value)} /></div>
            <div style={{ flex: 1 }}><span className="rr-field-label">Post-retire return % ({returnMode})</span><input type="number" step="0.1" value={postReturnInput} onChange={(e) => setPostReturnInput(e.target.value)} /></div>
            <div style={{ flex: 1 }}><span className="rr-field-label">Inflation %</span><input type="number" step="0.1" value={inflation} onChange={(e) => setInflation(e.target.value)} /></div>
          </div>
          <div style={{ fontSize: "11px", color: MUTED, marginBottom: "10px", lineHeight: 1.6 }}>
            Default 10% pre-retire ≈ S&P 500's long-run nominal average (all-stock, growth phase).
            Default 8% post-retire ≈ a 60/40 stock-bond mix — a common shift toward capital preservation
            once you're drawing income, trading some growth for lower volatility year to year.
          </div>
          {uiMode === "advanced" && (
          <div className="rr-mono" style={{ fontSize: "12px", color: MUTED, marginBottom: "16px" }}>
            Used in the math: {fmtPct(realPreReturn)} real pre-retire, {fmtPct(realPostReturn)} real post-retire
            {returnMode === "real" && ` (≈ ${fmtPct(nominalPreDisplay)} / ${fmtPct(nominalPostDisplay)} nominal)`}
          </div>
          )}

          <div style={{ marginBottom: "10px" }}>
            <span className="rr-field-label">Withdrawal rate in retirement %</span>
            <input type="number" step="0.1" value={withdrawalRate} onChange={(e) => setWithdrawalRate(e.target.value)} />
          </div>
          <div style={{
            border: `1px solid ${Math.abs(rateDelta) < 0.15 ? BRASS : rateDelta > 0 ? RUST : TEAL}`,
            borderRadius: "4px", padding: "12px", marginBottom: "20px", background: PANEL_2,
          }}>
            <div className="rr-mono" style={{ fontSize: "13px", color: Math.abs(rateDelta) < 0.15 ? BRASS : rateDelta > 0 ? RUST : TEAL, fontWeight: 600, marginBottom: "4px" }}>
              {Math.abs(rateDelta) < 0.15
                ? `≈ break-even (${fmtPct(breakEvenRate)})`
                : rateDelta > 0
                ? `${fmtPct(rateDelta)} above break-even (${fmtPct(breakEvenRate)})`
                : `${fmtPct(-rateDelta)} below break-even (${fmtPct(breakEvenRate)})`}
            </div>
            <div style={{ fontSize: "12px", color: MUTED, lineHeight: 1.5 }}>
              {Math.abs(rateDelta) < 0.15
                ? "Your withdrawal roughly matches your real return — principal stays flat in today's dollars."
                : rateDelta > 0
                ? "You're withdrawing faster than your real return — principal slowly declines in today's dollars."
                : "You're withdrawing less than your real return — principal keeps growing in today's dollars."}
            </div>
          </div>

          {uiMode === "advanced" && (
          <div style={{ display: "flex", gap: "10px", marginBottom: "20px" }}>
            <div style={{ flex: 1 }}>
              <span className="rr-field-label">Show dollars as</span>
              <div style={{ display: "flex" }}>
                <button className={`rr-toggle ${!showNominalDollars ? "active" : ""}`} style={{ flex: 1, borderRight: "none" }} onClick={() => setShowNominalDollars(false)}>Today's $</button>
                <button className={`rr-toggle ${showNominalDollars ? "active" : ""}`} style={{ flex: 1 }} onClick={() => setShowNominalDollars(true)}>Future $</button>
              </div>
            </div>
          </div>
          )}
          </>
          )}

          <button className="rr-collapsible-header" onClick={() => toggle("targetPortfolio")}>
            <span>TARGET PORTFOLIO</span>
            <span className="rr-caret" style={{ transform: expanded.targetPortfolio ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
          </button>
          {!expanded.targetPortfolio && (
            <div style={{ fontSize: "11px", color: MUTED, marginBottom: "16px" }} className="rr-mono">
              {targetMode === "expense" ? "From expense budget" : "Fixed"} · {fmtMoney(target)}
            </div>
          )}
          {expanded.targetPortfolio && (
          <>
          <div style={{ display: "flex", marginBottom: "10px" }}>
            <button className={`rr-toggle ${targetMode === "expense" ? "active" : ""}`} style={{ flex: 1, borderRight: "none" }} onClick={() => setTargetMode("expense")}>From expenses</button>
            <button className={`rr-toggle ${targetMode === "fixed" ? "active" : ""}`} style={{ flex: 1 }} onClick={() => setTargetMode("fixed")}>Fixed target</button>
          </div>
          {targetMode === "fixed" && (
            <div style={{ marginBottom: "20px" }}><span className="rr-field-label">Fixed portfolio target</span><input type="number" value={fixedTarget} onChange={(e) => setFixedTarget(e.target.value)} /></div>
          )}
          </>
          )}

          <div className="rr-section-label">PROJECTION — AGE {currentAge} TO {horizonAge}</div>
          <div style={{ width: "100%", height: 300 }}>
            <ResponsiveContainer>
              <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="age" stroke={MUTED} tick={{ fontFamily: "IBM Plex Mono", fontSize: 11, fill: MUTED }} tickLine={false} />
                <YAxis stroke={MUTED} tick={{ fontFamily: "IBM Plex Mono", fontSize: 11, fill: MUTED }} tickFormatter={(v) => fmtMoney(v, true)} tickLine={false} width={56} />
                <Tooltip contentStyle={{ background: PANEL_2, border: `1px solid ${GRID}`, borderRadius: "4px", fontFamily: "IBM Plex Mono", fontSize: "12px" }} labelFormatter={(age) => `Age ${age}`} formatter={(v, name) => [fmtMoney(v), name === "balance" ? "Portfolio" : "Target"]} />
                <ReferenceLine x={Number(retireAge)} stroke={PARCHMENT} strokeDasharray="3 3" label={{ value: "Retire", position: "insideTopLeft", fill: MUTED, fontSize: 11, fontFamily: "IBM Plex Mono" }} />
                <ReferenceLine x={65} stroke={RUST} strokeDasharray="2 2" label={{ value: "Medicare", position: "insideBottomLeft", fill: RUST, fontSize: 10, fontFamily: "IBM Plex Mono" }} />
                <Line type="monotone" dataKey="target" stroke={MUTED} strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
                <Line type="monotone" dataKey="balance" stroke={BRASS} strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div style={{ display: "flex", gap: "18px", fontSize: "12px", color: MUTED, marginTop: "4px" }} className="rr-mono">
            <span><span style={{ color: BRASS }}>■</span> Portfolio</span>
            <span><span style={{ color: MUTED }}>┄</span> Target</span>
          </div>

          <div style={{ marginTop: "30px" }}>
            <div className="rr-section-label">WITHDRAWAL INCOME (PRE-TAX)</div>
            {uiMode === "advanced" && (
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "14px" }}>
              <button className={`rr-toggle ${useSpendingSmile ? "active" : ""}`} style={{ flex: 1 }} onClick={() => setUseSpendingSmile(!useSpendingSmile)}>
                {useSpendingSmile ? "Spending glide path: ON ✓" : "Flat spending — tap to apply research-based glide path"}
              </button>
            </div>
            )}
            <div style={{ display: "flex", gap: "16px", marginBottom: "14px" }}>
              <div style={{ flex: 1, border: `1px solid ${BRASS}`, borderRadius: "4px", padding: "12px" }}>
                <div className="rr-field-label" style={{ marginBottom: "2px" }}>Annual, at retirement</div>
                <div className="rr-serif" style={{ fontSize: "22px", fontWeight: 700, color: BRASS }}>{fmtMoney(dv(withdrawalAtRetirement, Number(retireAge)))}/yr</div>
              </div>
              <div style={{ flex: 1, border: `1px solid ${BRASS}`, borderRadius: "4px", padding: "12px" }}>
                <div className="rr-field-label" style={{ marginBottom: "2px" }}>Monthly, at retirement</div>
                <div className="rr-serif" style={{ fontSize: "22px", fontWeight: 700, color: BRASS }}>{fmtMoney(dv(withdrawalAtRetirement, Number(retireAge)) / 12)}/mo</div>
              </div>
            </div>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", overflow: "hidden" }}>
              <div className="rr-row rr-mono" style={{ background: PANEL_2, fontSize: "11px", color: MUTED, textTransform: "uppercase", padding: "10px 12px" }}>
                <span style={{ flex: 1 }}>Age</span><span style={{ flex: 2, textAlign: "right" }}>Balance</span><span style={{ flex: 2, textAlign: "right" }}>Withdrawal/yr</span>
                {includeSS && <span style={{ flex: 2, textAlign: "right" }}>Est. SS/yr</span>}
                <span style={{ flex: 2, textAlign: "right" }}>Total/mo</span>
              </div>
              {withdrawalTable.map((r) => (
                <div key={r.age} className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}>
                  <span style={{ flex: 1 }}>{r.age}</span>
                  <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(r.balance, r.age))}</span>
                  <span style={{ flex: 2, textAlign: "right", color: BRASS }}>{fmtMoney(dv(r.annualWithdrawal, r.age))}</span>
                  {includeSS && <span style={{ flex: 2, textAlign: "right", color: TEAL }}>{fmtMoney(dv(r.ssAnnual, r.age))}</span>}
                  <span style={{ flex: 2, textAlign: "right", color: MUTED }}>{fmtMoney(dv(r.annualWithdrawal + r.ssAnnual, r.age) / 12)}</span>
                </div>
              ))}
            </div>
            <div style={{ fontSize: "11px", color: MUTED, marginTop: "8px" }}>
              These are <strong style={{ color: PARCHMENT }}>pre-tax (gross)</strong> withdrawal amounts — see "After-Tax
              Withdrawals" below for what actually lands in your pocket. Withdrawal = your chosen rate × that year's
              balance{useSpendingSmile ? ", scaled by the spending glide path below" : ""}, so it moves with the portfolio.
            </div>
          </div>

          <div style={{ marginTop: "30px" }}>
            <div className="rr-section-label">COMPARE RETIREMENT AGES</div>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", overflow: "hidden" }}>
              <div className="rr-row rr-mono" style={{ background: PANEL_2, fontSize: "11px", color: MUTED, textTransform: "uppercase", padding: "10px 12px" }}>
                <span style={{ flex: 1 }}>Age</span><span style={{ flex: 2, textAlign: "right" }}>Projected</span><span style={{ flex: 2, textAlign: "right" }}>Vs target</span>
              </div>
              {ageComparison.map((r) => (
                <div key={r.age} className="rr-row rr-mono" style={{ fontSize: "13px", padding: "10px 12px" }}>
                  <span style={{ flex: 1, color: r.age === Number(retireAge) ? BRASS : PARCHMENT, fontWeight: r.age === Number(retireAge) ? 600 : 400 }}>{r.age}</span>
                  <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(r.balance, r.age))}</span>
                  <span style={{ flex: 2, textAlign: "right", color: r.gap >= 0 ? TEAL : RUST }}>{r.gap >= 0 ? "+" : ""}{fmtMoney(dv(r.gap, r.age))}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ marginTop: "30px" }}>
            <div className="rr-section-label">GAP ANALYSIS</div>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", overflow: "hidden" }}>
              <div className="rr-row" style={{ padding: "12px" }}>
                <span style={{ fontSize: "13px" }}>Required % of each raise → retirement, to hit target</span>
                <span className="rr-mono" style={{ fontSize: "14px", fontWeight: 600, color: requiredRaiseAllocation <= Number(raiseAllocationPct) ? TEAL : RUST }}>{fmtPct(requiredRaiseAllocation)}</span>
              </div>
              <div className="rr-row" style={{ padding: "12px" }}>
                <span style={{ fontSize: "13px" }}>Your current allocation</span>
                <span className="rr-mono" style={{ fontSize: "14px" }}>{fmtPct(Number(raiseAllocationPct))}</span>
              </div>
              <div className="rr-row" style={{ padding: "12px" }}>
                <span style={{ fontSize: "13px" }}>Required flat monthly (no raise growth) to hit target</span>
                <span className="rr-mono" style={{ fontSize: "14px", fontWeight: 600, color: requiredFlatMonthly <= currentMonthlyContribution ? TEAL : RUST }}>{fmtMoney(requiredFlatMonthly)}/mo</span>
              </div>
              <div className="rr-row" style={{ padding: "12px" }}>
                <span style={{ fontSize: "13px" }}>Your current monthly contribution</span>
                <span className="rr-mono" style={{ fontSize: "14px" }}>{fmtMoney(currentMonthlyContribution)}/mo</span>
              </div>
            </div>
          </div>

          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("ss")}>
              <span>SOCIAL SECURITY (OPTIONAL)</span>
              <span className="rr-caret" style={{ transform: expanded.ss ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.ss && (
            <>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "14px" }}>
              <button className={`rr-toggle ${includeSS ? "active" : ""}`} style={{ flex: 1 }} onClick={() => setIncludeSS(!includeSS)}>
                {includeSS ? "Included in totals ✓" : "Not included — tap to add"}
              </button>
            </div>
            {includeSS && (
              <>
                <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
                  <div style={{ flex: 1 }}>
                    <span className="rr-field-label">Years already worked before now</span>
                    <input type="number" min="0" max="35" value={priorWorkingYears} onChange={(e) => setPriorWorkingYears(e.target.value)} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <span className="rr-field-label">Avg. salary those years</span>
                    <input type="number" value={priorAvgSalary} onChange={(e) => setPriorAvgSalary(e.target.value)} />
                  </div>
                </div>
                <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
                  <div style={{ flex: 1 }}>
                    <span className="rr-field-label">Claim age (62–70, FRA 67)</span>
                    <input type="number" min="62" max="70" value={ssClaimAge} onChange={(e) => setSsClaimAge(e.target.value)} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <span className="rr-field-label">Override monthly $ (blank = auto)</span>
                    <input
                      type="number"
                      value={ssOverrideMonthly === null ? "" : ssOverrideMonthly}
                      placeholder="auto-estimate"
                      onChange={(e) => setSsOverrideMonthly(e.target.value === "" ? null : Number(e.target.value))}
                    />
                  </div>
                </div>
                <div style={{ border: `1px solid ${TEAL}`, borderRadius: "4px", padding: "12px", marginBottom: "10px", background: PANEL_2 }}>
                  <div className="rr-field-label">{ssOverrideMonthly !== null ? "Your override" : "Auto-estimated benefit"}</div>
                  <div className="rr-serif" style={{ fontSize: "24px", fontWeight: 700, color: TEAL }}>{fmtMoney(ssMonthly)}/mo</div>
                  <div style={{ fontSize: "11px", color: MUTED, marginTop: "6px", lineHeight: 1.6 }}>
                    {ssOverrideMonthly === null && (
                      <>Based on {ssEstimate.workingYears} working year{ssEstimate.workingYears === 1 ? "" : "s"} of covered
                      salary (out of the 35 SSA averages — {ssEstimate.workingYears < 35 ? `${35 - ssEstimate.workingYears} zero-earning years pull this down` : "a full 35, no zeros"}),
                      capped at the taxable wage base, run through the actual 2026 bend-point formula, then adjusted for claiming at {ssClaimAge} vs. full retirement age 67.</>
                    )}
                  </div>
                </div>
                <div style={{ fontSize: "11px", color: MUTED, lineHeight: 1.6 }}>
                  This is a simplified estimate, not a substitute for your actual Social Security statement (check yours at
                  ssa.gov) — it doesn't account for years already worked before today, spousal benefits, or future changes
                  to the program. It's included in the "Total/mo" column above starting at your claim age.
                </div>
              </>
            )}
            </>
            )}
          </div>
          )}

          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("afterTax")}>
              <span>AFTER-TAX WITHDRAWALS</span>
              <span className="rr-caret" style={{ transform: expanded.afterTax ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.afterTax && (
            <>
            <div style={{ fontSize: "12px", color: MUTED, marginBottom: "14px", lineHeight: 1.6 }}>
              The "Withdrawal Income" figures above are <strong style={{ color: PARCHMENT }}>pre-tax (gross)</strong> — what
              comes out of the portfolio, not what lands in your pocket. What you actually keep depends on which account
              it comes from: Roth withdrawals are tax-free, HSA is tax-free for medical costs, Traditional withdrawals are
              taxed as ordinary income, and taxable-brokerage withdrawals owe capital gains tax only on the gain portion,
              not the whole amount.
            </div>
            <div style={{ fontSize: "11px", color: MUTED, marginBottom: "14px", fontStyle: "italic" }}>
              This estimate assumes your withdrawal mix matches your current contribution mix across account types (this
              tool tracks one blended portfolio balance, not separate balances per account) — a reasonable approximation,
              not a precise projection.
            </div>
            <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
              <div style={{ flex: 1 }}>
                <span className="rr-field-label">Capital gains rate %</span>
                <input type="number" step="0.5" value={capGainsRate} onChange={(e) => setCapGainsRate(e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <span className="rr-field-label">% of taxable balance that's gains</span>
                <input type="number" step="5" value={taxableGainsFraction} onChange={(e) => setTaxableGainsFraction(e.target.value)} />
              </div>
            </div>
            <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
              <div style={{ flex: 1 }}>
                <span className="rr-field-label">State tax rate % (0 for TX, FL, etc.)</span>
                <input type="number" step="0.5" value={stateTaxRate} onChange={(e) => setStateTaxRate(e.target.value)} />
              </div>
              {includeSS && (
                <div style={{ flex: 1 }}>
                  <span className="rr-field-label">% of Social Security taxable</span>
                  <input type="number" step="5" value={ssTaxablePct} onChange={(e) => setSsTaxablePct(e.target.value)} />
                </div>
              )}
            </div>

            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", overflow: "hidden", marginBottom: "10px" }}>
              <div className="rr-row rr-mono" style={{ background: PANEL_2, fontSize: "11px", color: MUTED, textTransform: "uppercase", padding: "10px 12px" }}>
                <span style={{ flex: 2 }}>Source</span><span style={{ flex: 2, textAlign: "right" }}>Gross/yr</span><span style={{ flex: 2, textAlign: "right" }}>Tax/yr</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}>
                <span style={{ flex: 2 }}>Roth ({fmtPct(accountMix.roth * 100)})</span>
                <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(afterTaxBreakdown.rothAmt, Number(retireAge)))}</span>
                <span style={{ flex: 2, textAlign: "right", color: TEAL }}>$0</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}>
                <span style={{ flex: 2 }}>Traditional ({fmtPct(accountMix.traditional * 100)})</span>
                <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(afterTaxBreakdown.traditionalAmt, Number(retireAge)))}</span>
                <span style={{ flex: 2, textAlign: "right", color: RUST }}>{fmtMoney(dv(afterTaxBreakdown.traditionalTax, Number(retireAge)))}</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}>
                <span style={{ flex: 2 }}>HSA ({fmtPct(accountMix.hsa * 100)}, medical use)</span>
                <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(afterTaxBreakdown.hsaAmt, Number(retireAge)))}</span>
                <span style={{ flex: 2, textAlign: "right", color: TEAL }}>$0</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}>
                <span style={{ flex: 2 }}>Taxable ({fmtPct(accountMix.taxable * 100)})</span>
                <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(afterTaxBreakdown.taxableAmt, Number(retireAge)))}</span>
                <span style={{ flex: 2, textAlign: "right", color: RUST }}>{fmtMoney(dv(afterTaxBreakdown.taxableTax, Number(retireAge)))}</span>
              </div>
              {includeSS && (
                <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}>
                  <span style={{ flex: 2 }}>Social Security</span>
                  <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(afterTaxBreakdown.ssGross, Number(retireAge)))}</span>
                  <span style={{ flex: 2, textAlign: "right", color: RUST }}>{fmtMoney(dv(afterTaxBreakdown.ssTax, Number(retireAge)))}</span>
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: "16px" }}>
              <div style={{ flex: 1, border: `1px solid ${RUST}`, borderRadius: "4px", padding: "12px" }}>
                <div className="rr-field-label">Total tax</div>
                <div className="rr-serif" style={{ fontSize: "20px", fontWeight: 700, color: RUST }}>{fmtMoney(dv(afterTaxBreakdown.totalTax, Number(retireAge)))}/yr</div>
              </div>
              <div style={{ flex: 1, border: `1px solid ${TEAL}`, borderRadius: "4px", padding: "12px" }}>
                <div className="rr-field-label">Net after-tax</div>
                <div className="rr-serif" style={{ fontSize: "20px", fontWeight: 700, color: TEAL }}>{fmtMoney(dv(afterTaxBreakdown.netAfterTax, Number(retireAge)))}/yr</div>
                <div style={{ fontSize: "11px", color: MUTED, marginTop: "2px" }}>{fmtMoney(dv(afterTaxBreakdown.netAfterTax, Number(retireAge)) / 12)}/mo</div>
              </div>
            </div>
            <div style={{ fontSize: "11px", color: MUTED, marginTop: "12px", lineHeight: 1.6 }}>
              Simplified estimate, not tax advice — real brackets, standard deductions, ACA subsidy cliffs (if retiring
              before 65), NIIT, and year-to-year account-mix choices all move this in practice.
            </div>
            </>
            )}
          </div>
          )}

          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("smile")}>
              <span>SPENDING GLIDE PATH — RESEARCH-BASED</span>
              <span className="rr-caret" style={{ transform: expanded.smile ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.smile && (
            <>
            <div style={{ fontSize: "12px", color: MUTED, marginBottom: "14px", lineHeight: 1.6 }}>
              Retirees typically don't spend a flat inflation-adjusted amount every year. Researcher David Blanchett
              (Morningstar/Prudential) studied real retiree spending and found a "retirement spending smile": real
              spending holds roughly steady through the active early years, declines through the mid-retirement years as
              activity naturally drops, bottoms out in the mid-80s (Blanchett's data showed around a 25% real decline
              from the starting level), then ticks back up later as healthcare and care costs rise. Financial planner
              Michael Stein's shorthand names for these phases stuck: <strong style={{ color: PARCHMENT }}>go-go</strong> (active,
              typically up to around 75), <strong style={{ color: PARCHMENT }}>slow-go</strong> (roughly 75–84), and{" "}
              <strong style={{ color: PARCHMENT }}>no-go</strong> (85+, healthcare-heavy). Bureau of Labor Statistics
              household spending data shows a similar pattern — average spending for 65–74 households runs meaningfully
              higher than for 75+ households.
            </div>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", overflow: "hidden", marginBottom: "10px" }}>
              <div className="rr-row rr-mono" style={{ background: PANEL_2, fontSize: "11px", color: MUTED, textTransform: "uppercase", padding: "10px 12px" }}>
                <span style={{ flex: 2 }}>Phase</span><span style={{ flex: 1 }}>Ages</span><span style={{ flex: 1, textAlign: "right" }}>% of go-go spending</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}><span style={{ flex: 2 }}>Go-go</span><span style={{ flex: 1 }}>Retire–74</span><span style={{ flex: 1, textAlign: "right" }}>100%</span></div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}><span style={{ flex: 2 }}>Slow-go</span><span style={{ flex: 1 }}>75–84</span><span style={{ flex: 1, textAlign: "right" }}>declines to ~75%</span></div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}><span style={{ flex: 2 }}>No-go</span><span style={{ flex: 1 }}>85+</span><span style={{ flex: 1, textAlign: "right" }}>rises toward ~90%</span></div>
            </div>
            <div style={{ fontSize: "11px", color: MUTED, lineHeight: 1.6 }}>
              Toggle "Spending glide path" on above to apply this curve to your withdrawal — it lowers what's pulled from
              the portfolio in the slow-go years, which is one reason many retirees end up over-saving relative to a
              flat-spending model like the plain 4% rule. This is a population-average pattern, not a guarantee for any
              one person — your own health, hobbies, and travel plans could easily look different.
            </div>
            </>
            )}
          </div>
          )}
          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("fire")}>
              <span>EARLY RETIREMENT — FIRE &amp; COAST FIRE</span>
              <span className="rr-caret" style={{ transform: expanded.fire ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.fire && (
            <>
            <div style={{ fontSize: "12px", color: MUTED, marginBottom: "14px", lineHeight: 1.6 }}>
              <strong style={{ color: PARCHMENT }}>FIRE</strong> (Financial Independence, Retire Early) means hitting
              your full target — {fmtMoney(target)} — however early that happens, then living off withdrawals from there.
              <strong style={{ color: PARCHMENT }}> Coast FIRE</strong> is different: it's the point where you could stop
              adding new money entirely, and pure compound growth — with zero further contributions — would still carry
              you to your target by your chosen retirement age. You'd still work, but only to cover today's spending,
              not to keep funding retirement.
            </div>

            <div style={{ display: "flex", gap: "16px", marginBottom: "14px" }}>
              <div style={{ flex: 1, border: `1px solid ${GRID}`, borderRadius: "4px", padding: "12px" }}>
                <div className="rr-field-label">Earliest FIRE age (still contributing)</div>
                <div className="rr-serif" style={{ fontSize: "24px", fontWeight: 700, color: BRASS }}>
                  {earliestFireAge ? earliestFireAge : `${horizonAge}+`}
                </div>
                <div style={{ fontSize: "11px", color: MUTED, marginTop: "4px" }}>
                  First age your projected balance clears {fmtMoney(target)}, on your current contribution schedule.
                </div>
              </div>
              <div style={{ flex: 1, border: `1px solid ${GRID}`, borderRadius: "4px", padding: "12px" }}>
                <div className="rr-field-label">Coast FIRE age (for retiring at {retireAge})</div>
                <div className="rr-serif" style={{ fontSize: "24px", fontWeight: 700, color: TEAL }}>
                  {coastFireAge !== null ? coastFireAge : `not by ${retireAge}`}
                </div>
                <div style={{ fontSize: "11px", color: MUTED, marginTop: "4px" }}>
                  Age you could stop contributing and still hit target by {retireAge} on growth alone.
                </div>
              </div>
            </div>

            <div style={{ border: `1px solid ${alreadyCoastFI ? TEAL : GRID}`, borderRadius: "4px", padding: "12px", marginBottom: "10px", background: PANEL_2 }}>
              <div className="rr-mono" style={{ fontSize: "13px", color: alreadyCoastFI ? TEAL : MUTED, fontWeight: 600, marginBottom: "4px" }}>
                {alreadyCoastFI ? "You've already hit Coast FIRE today" : "Not yet at Coast FIRE"}
              </div>
              <div style={{ fontSize: "12px", color: MUTED, lineHeight: 1.6 }}>
                Today's Coast FI number (what you'd need right now, invested, to coast to {fmtMoney(target)} by age {retireAge}
                with zero more contributions) is <span style={{ color: PARCHMENT }}>{fmtMoney(coastFiNumber)}</span>.
                Your current balance is <span style={{ color: PARCHMENT }}>{fmtMoney(Number(currentBalance))}</span>.
              </div>
            </div>

            <div style={{ fontSize: "11px", color: MUTED, lineHeight: 1.7 }}>
              A few other flavors worth knowing: <strong style={{ color: PARCHMENT }}>Lean FIRE</strong> targets a bare-bones
              budget (lower target, earlier finish); <strong style={{ color: PARCHMENT }}>Fat FIRE</strong> targets a more
              lavish one (higher target, later finish) — try both by editing your budget above and re-checking these numbers.
              <strong style={{ color: PARCHMENT }}> Barista FIRE</strong> sits between Coast and full FIRE: you cover part of
              your expenses with light part-time work, so your portfolio only needs to fund the rest — useful if "some work,
              way less pressure" appeals more than either full retirement or full-time coasting. One practical wrinkle for
              retiring before 59½: most of your 401k/IRA balance can't be touched penalty-free that early. Common bridges are
              a Roth IRA's original contributions (withdrawable anytime, tax- and penalty-free), a Roth conversion ladder,
              taxable brokerage funds, or 72(t)/SEPP scheduled withdrawals — worth researching well before you'd actually need them.
            </div>
            </>
            )}
          </div>
          )}

          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("sequence")}>
              <span>MARKET VOLATILITY — SEQUENCE OF RETURNS RISK</span>
              <span className="rr-caret" style={{ transform: expanded.sequence ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.sequence && (
            <>
            <div style={{ fontSize: "12px", color: MUTED, marginBottom: "14px", lineHeight: 1.6 }}>
              Every other number in this tool assumes a smooth, constant return every year. Real markets don't work that
              way — and the <em>order</em> returns arrive in matters enormously once you're withdrawing. A crash in your
              first few retirement years forces you to sell more shares at low prices to cover the same withdrawal,
              permanently denting the portfolio even if the average return over your whole retirement ends up identical.
              A crash late in retirement, after decades of growth, barely matters by comparison. This is called
              sequence-of-returns risk, and it's arguably the biggest real-world threat to a "preserve principal" plan.
            </div>
            <div style={{ fontSize: "11px", color: MUTED, marginTop: "8px", marginBottom: "14px", fontStyle: "italic" }}>
              Note: this comparison holds your withdrawal fixed at the dollar amount set on retirement day (the classic
              "4%-rule" style), unlike the rest of this calculator's rate-of-current-balance approach — that's
              intentional, since a percentage-of-balance withdrawal is naturally immune to reordering and wouldn't show
              sequence risk at all.
            </div>
            <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
              <div style={{ flex: 1 }}>
                <span className="rr-field-label">Bad years at the start</span>
                <input type="number" min="1" value={badYearsCount} onChange={(e) => setBadYearsCount(e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <span className="rr-field-label">Return during bad years %</span>
                <input type="number" value={badYearReturn} onChange={(e) => setBadYearReturn(e.target.value)} />
              </div>
            </div>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", overflow: "hidden", marginBottom: "10px" }}>
              <div className="rr-row rr-mono" style={{ background: PANEL_2, fontSize: "11px", color: MUTED, textTransform: "uppercase", padding: "10px 12px" }}>
                <span style={{ flex: 2 }}>Scenario</span><span style={{ flex: 2, textAlign: "right" }}>Balance at {horizonAge}</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "10px 12px" }}>
                <span style={{ flex: 2 }}>Constant return (baseline)</span>
                <span style={{ flex: 2, textAlign: "right" }}>{fmtMoney(dv(sequenceComparison.constant, Number(horizonAge)))}</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "10px 12px" }}>
                <span style={{ flex: 2, color: RUST }}>Bad years first</span>
                <span style={{ flex: 2, textAlign: "right", color: RUST }}>{fmtMoney(dv(sequenceComparison.badFirst, Number(horizonAge)))}</span>
              </div>
              <div className="rr-row rr-mono" style={{ fontSize: "13px", padding: "10px 12px" }}>
                <span style={{ flex: 2, color: TEAL }}>Bad years last</span>
                <span style={{ flex: 2, textAlign: "right", color: TEAL }}>{fmtMoney(dv(sequenceComparison.badLast, Number(horizonAge)))}</span>
              </div>
            </div>
            <div style={{ fontSize: "11px", color: MUTED, lineHeight: 1.6 }}>
              All three rows use the exact same average return over your full retirement — only the order changes.
              The gap between them is sequence risk in dollar terms. Common ways to soften it: a cash/bond buffer covering
              1–3 years of expenses so you're not forced to sell stocks in a downturn, or trimming withdrawals during
              rough years instead of taking a fixed amount regardless of the market.
            </div>
            </>
            )}
          </div>
          )}

          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("order")}>
              <span>WITHDRAWAL ORDER IN RETIREMENT</span>
              <span className="rr-caret" style={{ transform: expanded.order ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.order && (
            <>
            <div style={{ fontSize: "12px", color: MUTED, marginBottom: "14px", lineHeight: 1.6 }}>
              Which account you draw from first changes how long your money lasts and how much tax you pay along the way.
              Based on the account types you've entered above, here's a common sequence:
            </div>
            {withdrawalOrderGroups.length === 0 ? (
              <div style={{ fontSize: "12px", color: MUTED }}>Add accounts above to see a suggested order.</div>
            ) : (
              withdrawalOrderGroups.map((g, i) => (
                <div key={g.label} style={{ border: `1px solid ${GRID}`, borderRadius: "4px", padding: "12px", marginBottom: "8px", display: "flex", gap: "12px" }}>
                  <div className="rr-serif" style={{ fontSize: "20px", fontWeight: 700, color: BRASS, flexShrink: 0 }}>{i + 1}</div>
                  <div>
                    <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "2px" }}>{g.label}</div>
                    <div style={{ fontSize: "12px", color: MUTED, lineHeight: 1.5 }}>{g.why}</div>
                  </div>
                </div>
              ))
            )}
            <div style={{ fontSize: "11px", color: MUTED, marginTop: "10px", lineHeight: 1.6 }}>
              {hasTraditional
                ? "Note: Traditional accounts force Required Minimum Distributions (RMDs) starting at age 73, whether you need the income or not — worth planning around rather than relying purely on this order."
                : "You're currently all-Roth/taxable/HSA with no Traditional balance, so RMDs (which only apply to Traditional accounts, starting age 73) aren't a concern on your current mix."}
              {" "}This is a general framework, not a fixed rule — your actual best order depends on tax brackets each year, ACA subsidies if retiring before 65, and Roth conversion opportunities in low-income years.
            </div>
            </>
            )}
          </div>
          )}

          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("limits")}>
              <span>CONTRIBUTION LIMIT CHECK</span>
              <span className="rr-caret" style={{ transform: expanded.limits ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.limits && (
            <>
            <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
              <div style={{ flex: 1 }}>
                <span className="rr-field-label">HSA coverage type</span>
                <div style={{ display: "flex" }}>
                  <button className={`rr-toggle ${hsaCoverage === "self" ? "active" : ""}`} style={{ flex: 1, borderRight: "none" }} onClick={() => setHsaCoverage("self")}>Self-only</button>
                  <button className={`rr-toggle ${hsaCoverage === "family" ? "active" : ""}`} style={{ flex: 1 }} onClick={() => setHsaCoverage("family")}>Family</button>
                </div>
              </div>
            </div>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", overflow: "hidden" }}>
              <div className="rr-row rr-mono" style={{ background: PANEL_2, fontSize: "11px", color: MUTED, textTransform: "uppercase", padding: "10px 12px" }}>
                <span style={{ flex: 2 }}>Account</span><span style={{ flex: 2, textAlign: "right" }}>You're at</span><span style={{ flex: 2, textAlign: "right" }}>2026 limit</span>
              </div>
              {contributionLimitChecks.map((a) => (
                <div key={a.id} className="rr-row rr-mono" style={{ fontSize: "13px", padding: "9px 12px" }}>
                  <span style={{ flex: 2 }}>{a.label}</span>
                  <span style={{ flex: 2, textAlign: "right", color: a.overLimit ? RUST : PARCHMENT }}>{fmtMoney(a.annual)}/yr</span>
                  <span style={{ flex: 2, textAlign: "right", color: MUTED }}>{a.limit !== null ? `${fmtMoney(a.limit)}/yr` : "no limit"}</span>
                </div>
              ))}
            </div>
            {contributionLimitChecks.some((a) => a.overLimit) ? (
              <div style={{ fontSize: "12px", color: RUST, marginTop: "10px" }}>
                One or more accounts are set above the 2026 IRS limit — excess 401k/IRA contributions get taxed twice if not corrected before the filing deadline.
              </div>
            ) : (
              <div style={{ fontSize: "12px", color: TEAL, marginTop: "10px" }}>Everything's within the 2026 limits.</div>
            )}
            <div style={{ fontSize: "11px", color: MUTED, marginTop: "10px", lineHeight: 1.6 }}>
              Assign each account a type above (in Your Accounts) for this check to work — 401k, IRA, and HSA share
              limits across Roth/Traditional variants for the same person, so two IRAs listed for the same person (not
              a spouse) would actually share one $7,500 cap in real life, even though they're checked separately here.
              Catch-up contributions for ages 50+ aren't factored in.
            </div>
            </>
            )}
          </div>
          )}

          {targetMode === "expense" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("budget")}>
              <span>ANNUAL BUDGET — EDIT ANY LINE</span>
              <span className="rr-caret" style={{ transform: expanded.budget ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.budget && (
            <>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", padding: "4px 12px" }}>
              {expenses.map((e) => (
                <div key={e.id} className="rr-expense-row">
                  <input type="text" value={e.label} onChange={(ev) => updateExpense(e.id, "label", ev.target.value)} style={{ flex: 1, fontFamily: "Inter", fontSize: "13px", border: "none", background: "transparent", padding: "2px 0" }} />
                  <span className="rr-mono" style={{ fontSize: "12px", color: MUTED }}>$</span>
                  <input type="number" value={e.monthly} onChange={(ev) => updateExpense(e.id, "monthly", Number(ev.target.value))} style={{ width: "84px" }} />
                  <span className="rr-mono" style={{ fontSize: "11px", color: MUTED }}>/mo</span>
                  <button className="rr-x-btn" onClick={() => removeExpense(e.id)}>×</button>
                </div>
              ))}
              <div className="rr-expense-row">
                <span style={{ flex: 1, fontSize: "13px" }}>Healthcare, before Medicare (65)</span>
                <span className="rr-mono" style={{ fontSize: "12px", color: MUTED }}>$</span>
                <input type="number" value={healthcarePre65} onChange={(e) => setHealthcarePre65(Number(e.target.value))} style={{ width: "84px" }} />
                <span className="rr-mono" style={{ fontSize: "11px", color: MUTED }}>/mo</span>
                <span style={{ width: "24px" }} />
              </div>
              <div className="rr-expense-row">
                <span style={{ flex: 1, fontSize: "13px" }}>Healthcare, after Medicare (65+)</span>
                <span className="rr-mono" style={{ fontSize: "12px", color: MUTED }}>$</span>
                <input type="number" value={healthcarePost65} onChange={(e) => setHealthcarePost65(Number(e.target.value))} style={{ width: "84px" }} />
                <span className="rr-mono" style={{ fontSize: "11px", color: MUTED }}>/mo</span>
                <span style={{ width: "24px" }} />
              </div>
            </div>
            <button className="rr-add-btn" style={{ marginTop: "8px" }} onClick={addExpense}>+ add category</button>
            <div style={{ display: "flex", gap: "16px", marginTop: "10px" }} className="rr-mono">
              <div style={{ flex: 1, border: `1px solid ${GRID}`, borderRadius: "4px", padding: "10px 12px" }}>
                <div style={{ fontSize: "11px", color: MUTED }}>Total before 65</div>
                <div style={{ fontSize: "16px", color: BRASS, fontWeight: 600 }}>{fmtMoney(expensePre65)}/yr</div>
              </div>
              <div style={{ flex: 1, border: `1px solid ${GRID}`, borderRadius: "4px", padding: "10px 12px" }}>
                <div style={{ fontSize: "11px", color: MUTED }}>Total 65+</div>
                <div style={{ fontSize: "16px", color: BRASS, fontWeight: 600 }}>{fmtMoney(expensePost65)}/yr</div>
              </div>
            </div>
            </>
            )}
          </div>
          )}

          {uiMode === "advanced" && (
          <div style={{ marginTop: "30px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("tax")}>
              <span>TAX STRATEGY</span>
              <span className="rr-caret" style={{ transform: expanded.tax ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.tax && (
            <>
            <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
              <div style={{ flex: 1 }}><span className="rr-field-label">Your marginal tax rate now %</span><input type="number" step="0.5" value={currentMarginalRate} onChange={(e) => setCurrentMarginalRate(e.target.value)} /></div>
              <div style={{ flex: 1 }}><span className="rr-field-label">Expected rate in retirement %</span><input type="number" step="0.5" value={retirementMarginalRate} onChange={(e) => setRetirementMarginalRate(e.target.value)} /></div>
            </div>
            <div style={{ border: `1px solid ${GRID}`, borderRadius: "4px", padding: "14px" }}>
              <div style={{ fontSize: "13px", marginBottom: "6px" }}>Roth vs. Traditional, for the same take-home pay contributed:</div>
              <div className="rr-serif" style={{ fontSize: "24px", fontWeight: 700, color: rothAdvantagePct >= 0 ? BRASS : TEAL }}>
                {rothAdvantagePct >= 0 ? "Roth ahead by " : "Traditional ahead by "}{fmtPct(Math.abs(rothAdvantagePct))}
              </div>
              <div style={{ fontSize: "12px", color: MUTED, marginTop: "8px", lineHeight: 1.6 }}>
                {rothAdvantagePct === 0
                  ? "At equal rates the two are mathematically the same after-tax — ties usually favor Roth for flexibility."
                  : rothAdvantagePct > 0
                  ? "Your expected retirement rate is higher than today's — paying tax now at the lower rate (Roth) beats paying the higher rate later. HSA stays best regardless — tax-free in, growing, and out for medical costs."
                  : "Your expected retirement rate is lower than today's — paying tax later (Traditional) beats paying today's higher rate. Worth checking for future 401k elections; existing Roth balances are already locked in tax-free and don't need to change."}
              </div>
            </div>
            </>
            )}
          </div>
          )}


          <div style={{ marginTop: "30px", marginBottom: "10px" }}>
            <button className="rr-collapsible-header" onClick={() => toggle("glossary")}>
              <span>RETIREMENT ACCOUNTS, EXPLAINED</span>
              <span className="rr-caret" style={{ transform: expanded.glossary ? "rotate(90deg)" : "rotate(0deg)" }}>▸</span>
            </button>
            {expanded.glossary && (
            <>
            <div style={{ fontSize: "11px", color: MUTED, marginBottom: "14px" }}>2026 IRS limits shown — these adjust most years.</div>

            {[
              { name: "Roth 401k", tax: "Contribute after-tax; grows and withdraws tax-free.", limit: "$24,500/yr ($32,500 if 50+; $35,750 if 60–63), shared with Traditional 401k", best: "Best if you expect a similar or higher tax rate in retirement than today, or want tax-free growth locked in early in your career." },
              { name: "Traditional 401k", tax: "Contribute pre-tax, lowering income now; withdrawals taxed as income later.", limit: "Same $24,500/yr cap, shared with Roth 401k; $72,000 combined employee+employer cap", best: "Best in your peak-earning, highest-tax-bracket years, especially if you expect a lower bracket in retirement." },
              { name: "Roth IRA", tax: "After-tax in, tax-free growth and withdrawals; original contributions can be withdrawn anytime, penalty-free.", limit: "$7,500/yr combined with Traditional IRA ($8,600 if 50+); phases out at higher income (2026: ~$153k–168k single, ~$242k–252k joint)", best: "Especially useful for early-retirement bridges, since contributions (not earnings) are accessible before 59½ with no penalty." },
              { name: "Traditional IRA", tax: "May be pre-tax if you qualify for the deduction; grows tax-deferred, taxed on withdrawal.", limit: "Same $7,500/yr cap, shared with Roth IRA", best: "Useful if you're phased out of a Roth IRA deduction or want an extra pre-tax bucket beyond your 401k." },
              { name: "HSA", tax: "Triple advantage: pre-tax in, tax-free growth, tax-free out for medical expenses (and penalty-free for any purpose after 65, taxed as income like a Traditional account).", limit: "$4,400/yr self-only, $8,750 family (2026); +$1,000 if 55+", best: "The single best-taxed account available if you have a high-deductible health plan — worth maxing before extra Roth/taxable investing." },
              { name: "Taxable brokerage", tax: "No upfront tax break; pay capital gains tax on growth when sold (often at favorable long-term rates).", limit: "No contribution limit", best: "Best once you've maxed the accounts above, or for money you might need before 59½ without penalty — fully flexible, no withdrawal rules." },
              { name: "529 plan", tax: "After-tax in; tax-free growth and withdrawals for qualified education expenses (some states also give a deduction).", limit: "No federal cap; state gift-tax thresholds apply", best: "Purpose-built for kids' education costs — not a general retirement vehicle, but frees up other accounts from having to cover tuition." },
            ].map((a) => (
              <div key={a.name} style={{ border: `1px solid ${GRID}`, borderRadius: "4px", padding: "12px", marginBottom: "8px" }}>
                <div className="rr-serif" style={{ fontSize: "16px", fontWeight: 600, color: BRASS, marginBottom: "4px" }}>{a.name}</div>
                <div style={{ fontSize: "12px", color: PARCHMENT, marginBottom: "4px", lineHeight: 1.5 }}>{a.tax}</div>
                <div className="rr-mono" style={{ fontSize: "11px", color: MUTED, marginBottom: "4px" }}>{a.limit}</div>
                <div style={{ fontSize: "12px", color: TEAL, lineHeight: 1.5 }}>{a.best}</div>
              </div>
            ))}
            <div style={{ fontSize: "11px", color: MUTED, marginTop: "10px", lineHeight: 1.6 }}>
              General order many planners suggest: employer match first (free money), then HSA, then max Roth/Traditional
              IRA, then back to maxing the 401k, then taxable brokerage. Not universal advice — your mix of tax brackets
              now vs. expected in retirement, and how soon you might retire, can reasonably shift that order.
            </div>
            </>
            )}
          </div>
        </div>
      </div>
      </div>

      <div className="rr-print-summary" style={{ padding: "32px", fontFamily: "Georgia, serif" }}>
        <h1 style={{ fontSize: "24px", marginBottom: "4px" }}>Retirement Runway — Summary</h1>
        <div style={{ fontSize: "12px", color: "#666", marginBottom: "20px" }}>Generated {new Date().toLocaleDateString()}</div>

        <h2 style={{ fontSize: "16px", borderBottom: "1px solid #ccc", paddingBottom: "4px" }}>Plan</h2>
        <p style={{ fontSize: "13px", lineHeight: 1.8 }}>
          Current age {currentAge}, retiring at {retireAge}, planning through age {horizonAge}.<br />
          Salary {fmtMoney(Number(salary))}, growing {raisePct}%/yr, with {raiseAllocationPct}% of each raise directed to retirement.<br />
          Current retirement + brokerage balance: {fmtMoney(Number(currentBalance))}. Monthly contribution: {fmtMoney(currentMonthlyContribution)}.<br />
          Assumed returns: {fmtPct(realPreReturn)} real pre-retirement, {fmtPct(realPostReturn)} real post-retirement, {inflation}% inflation.<br />
          Withdrawal rate: {withdrawalRate}%. Target: {targetMode === "expense" ? "based on expense budget" : "fixed"} at {fmtMoney(target)}.
        </p>

        <h2 style={{ fontSize: "16px", borderBottom: "1px solid #ccc", paddingBottom: "4px", marginTop: "20px" }}>Results</h2>
        <table style={{ width: "100%", fontSize: "13px", borderCollapse: "collapse" }}>
          <tbody>
            <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Projected portfolio at retirement</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }} className="rr-brass">{fmtMoney(dv(schedule.finalBalance, Number(retireAge)))}</td></tr>
            <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Target</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }} className="rr-teal">{fmtMoney(dv(target, Number(retireAge)))}</td></tr>
            <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Gap</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{gap >= 0 ? "+" : ""}{fmtMoney(dv(gap, Number(retireAge)))}</td></tr>
            <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Withdrawal income (pre-tax)</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{fmtMoney(dv(withdrawalAtRetirement, Number(retireAge)))}/yr</td></tr>
            <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Withdrawal income (after-tax est.)</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{fmtMoney(dv(afterTaxBreakdown.netAfterTax, Number(retireAge)))}/yr</td></tr>
            {includeSS && (
              <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Est. Social Security (claim age {ssClaimAge})</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{fmtMoney(ssMonthly)}/mo</td></tr>
            )}
            <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Earliest FIRE age</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{earliestFireAge || `${horizonAge}+`}</td></tr>
            <tr><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>Coast FIRE age (for retiring at {retireAge})</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{coastFireAge !== null ? coastFireAge : `not by ${retireAge}`}</td></tr>
          </tbody>
        </table>

        <h2 style={{ fontSize: "16px", borderBottom: "1px solid #ccc", paddingBottom: "4px", marginTop: "20px" }}>Compare Retirement Ages</h2>
        <table style={{ width: "100%", fontSize: "13px", borderCollapse: "collapse" }}>
          <thead><tr><th style={{ textAlign: "left", padding: "6px 0", borderBottom: "1px solid #999" }}>Age</th><th style={{ textAlign: "right", padding: "6px 0", borderBottom: "1px solid #999" }}>Projected</th><th style={{ textAlign: "right", padding: "6px 0", borderBottom: "1px solid #999" }}>Vs target</th></tr></thead>
          <tbody>
            {ageComparison.map((r) => (
              <tr key={r.age}><td style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>{r.age}</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{fmtMoney(dv(r.balance, r.age))}</td><td style={{ padding: "6px 0", borderBottom: "1px solid #eee", textAlign: "right" }}>{r.gap >= 0 ? "+" : ""}{fmtMoney(dv(r.gap, r.age))}</td></tr>
            ))}
          </tbody>
        </table>

        <p style={{ fontSize: "11px", color: "#888", marginTop: "24px", lineHeight: 1.6 }}>
          Illustrative estimate only, not financial advice. Figures shown in {showNominalDollars ? "future (inflation-adjusted)" : "today's"} dollars.
        </p>
      </div>
    </div>
  );
}

export default RetirementRunwayV4;
