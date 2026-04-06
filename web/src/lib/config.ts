/** Trading bot configuration. */

export interface TradingConfig {
  capital: { total: number; perTrade: number; maxConcurrent: number; maxDailyTrades: number };
  signals: { rsiPeriod: number; emaFast: number; emaSlow: number; orbMinutes: number; volumeSpikeMultiplier: number; vwapVolumeMultiplier: number; minScore: number };
  exits: { targetPct: number; stoplossPct: number; trailingTriggerPct: number; squareoffTime: string };
  safety: { noTradeBefore: string; noTradeAfter: string; maxVix: number; maxGapPct: number; maxDailyLoss: number };
  universe: { minVolumeCr: number; atrPctMin: number; atrPctMax: number; lookbackDays: number };
}

export const DEFAULT_CONFIG: TradingConfig = {
  capital: { total: 100000, perTrade: 45000, maxConcurrent: 2, maxDailyTrades: 4 },
  signals: { rsiPeriod: 14, emaFast: 9, emaSlow: 21, orbMinutes: 15, volumeSpikeMultiplier: 2.0, vwapVolumeMultiplier: 1.5, minScore: 3 },
  exits: { targetPct: 1.2, stoplossPct: 0.6, trailingTriggerPct: 0.7, squareoffTime: "15:15" },
  safety: { noTradeBefore: "09:20", noTradeAfter: "14:30", maxVix: 18.0, maxGapPct: 1.0, maxDailyLoss: 2000 },
  universe: { minVolumeCr: 50, atrPctMin: 1.5, atrPctMax: 3.0, lookbackDays: 20 },
};

export const NIFTY_200_TOP = [
  "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
  "BHARTIARTL","KOTAKBANK","LT","AXISBANK","BAJFINANCE","ASIANPAINT","MARUTI",
  "HCLTECH","SUNPHARMA","TITAN","ULTRACEMCO","WIPRO","NTPC","POWERGRID",
  "ONGC","TATAMOTORS","M&M","ADANIENT","ADANIPORTS","COALINDIA","JSWSTEEL",
  "TATASTEEL","TECHM","BAJAJFINSV","INDUSINDBK","NESTLEIND","GRASIM",
  "DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","EICHERMOT","BRITANNIA",
  "HEROMOTOCO","DABUR","TRENT","TATACONSUM","BAJAJ-AUTO","BPCL","IOC",
  "SBILIFE","HDFCLIFE","HAL","BEL","TATAPOWER","ZOMATO","DLF",
  "INDIGO","VEDL","HINDALCO","JINDALSTEL","IRCTC",
];
