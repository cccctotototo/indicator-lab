import process from "node:process";
import { PineTS, aggregateCandles } from "pinets";

const LONG_NAMES = [
  "improvedlongsignal",
  "ailongsignal",
  "longsignal",
  "long_signal",
  "buysignal",
  "buy_signal",
  "bullsignal",
  "bull_signal",
  "bullishsignal",
  "golong",
  "enterlong",
];

const SHORT_NAMES = [
  "improvedshortsignal",
  "aishortsignal",
  "shortsignal",
  "short_signal",
  "sellsignal",
  "sell_signal",
  "bearsignal",
  "bear_signal",
  "bearishsignal",
  "goshort",
  "entershort",
];

const LONG_WORDS = [
  "long",
  "buy",
  "bull",
  "做多",
  "多單",
  "買進",
  "買入",
  "labelup",
  "belowbar",
  "arrowup",
];

const SHORT_WORDS = [
  "short",
  "sell",
  "bear",
  "做空",
  "空單",
  "賣出",
  "labeldown",
  "abovebar",
  "arrowdown",
];

function readStdin() {
  return new Promise((resolve, reject) => {
    let body = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      body += chunk;
    });
    process.stdin.on("end", () => resolve(body));
    process.stdin.on("error", reject);
  });
}

function declaredVariables(source) {
  const variables = new Map();
  const pattern =
    /(?:^|\n)\s*(?:varip\s+|var\s+)?(?:bool\s+|float\s+|int\s+|string\s+)?([A-Za-z_]\w*)\s*(?::=|=)/g;
  for (const match of source.matchAll(pattern)) {
    variables.set(match[1].toLowerCase(), match[1]);
  }
  return variables;
}

function firstDeclared(variables, names) {
  for (const name of names) {
    if (variables.has(name)) {
      return variables.get(name);
    }
  }
  return null;
}

function extractCalls(source, callName) {
  const calls = [];
  const pattern = new RegExp(`\\b${callName.replace(".", "\\.")}\\s*\\(`, "g");
  let match;
  while ((match = pattern.exec(source)) !== null) {
    const open = source.indexOf("(", match.index);
    let depth = 0;
    let quote = null;
    let escaped = false;
    for (let index = open; index < source.length; index += 1) {
      const char = source[index];
      if (quote !== null) {
        if (escaped) {
          escaped = false;
        } else if (char === "\\") {
          escaped = true;
        } else if (char === quote) {
          quote = null;
        }
        continue;
      }
      if (char === '"' || char === "'") {
        quote = char;
      } else if (char === "(") {
        depth += 1;
      } else if (char === ")") {
        depth -= 1;
        if (depth === 0) {
          calls.push(source.slice(match.index, index + 1));
          pattern.lastIndex = index + 1;
          break;
        }
      }
    }
  }
  return calls;
}

function splitTopLevelArguments(call) {
  const open = call.indexOf("(");
  const body = call.slice(open + 1, -1);
  const parts = [];
  let start = 0;
  let depth = 0;
  let quote = null;
  let escaped = false;
  for (let index = 0; index < body.length; index += 1) {
    const char = body[index];
    if (quote !== null) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === quote) {
        quote = null;
      }
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
    } else if (char === "(" || char === "[" || char === "{") {
      depth += 1;
    } else if (char === ")" || char === "]" || char === "}") {
      depth -= 1;
    } else if (char === "," && depth === 0) {
      parts.push(body.slice(start, index).trim());
      start = index + 1;
    }
  }
  parts.push(body.slice(start).trim());
  return parts.filter(Boolean);
}

function directionOf(text) {
  const normalized = text.toLowerCase();
  const longScore = LONG_WORDS.reduce(
    (score, word) => score + (normalized.includes(word) ? 1 : 0),
    0,
  );
  const shortScore = SHORT_WORDS.reduce(
    (score, word) => score + (normalized.includes(word) ? 1 : 0),
    0,
  );
  if (longScore > shortScore) {
    return "long";
  }
  if (shortScore > longScore) {
    return "short";
  }
  return null;
}

function conditionFromCall(call) {
  const args = splitTopLevelArguments(call);
  if (!args.length) {
    return null;
  }
  const first = args[0];
  const named = first.match(/^(?:condition|series)\s*=\s*([\s\S]+)$/);
  return (named ? named[1] : first).trim();
}

function inferredExpressions(source, explicitLong, explicitShort) {
  const variables = declaredVariables(source);
  let longExpression = explicitLong?.trim() || firstDeclared(variables, LONG_NAMES);
  let shortExpression = explicitShort?.trim() || firstDeclared(variables, SHORT_NAMES);
  const inferred = { long: [], short: [] };

  for (const callName of ["alertcondition", "plotshape", "plotchar"]) {
    for (const call of extractCalls(source, callName)) {
      const direction = directionOf(call);
      const condition = conditionFromCall(call);
      if (direction && condition) {
        inferred[direction].push(condition);
      }
    }
  }

  if (!longExpression && inferred.long.length) {
    longExpression =
      inferred.long.length === 1
        ? inferred.long[0]
        : inferred.long.map((value) => `(${value})`).join(" or ");
  }
  if (!shortExpression && inferred.short.length) {
    shortExpression =
      inferred.short.length === 1
        ? inferred.short[0]
        : inferred.short.map((value) => `(${value})`).join(" or ");
  }
  return { longExpression, shortExpression };
}

function instrumentSource(source, explicitLong, explicitShort) {
  if (!/\bindicator\s*\(/.test(source)) {
    throw new Error("PineTS 指標模式只接受 indicator()，不接受 strategy()。");
  }
  const { longExpression, shortExpression } = inferredExpressions(
    source,
    explicitLong,
    explicitShort,
  );
  if (!longExpression || !shortExpression) {
    const missing = [
      !longExpression ? "做多" : null,
      !shortExpression ? "做空" : null,
    ]
      .filter(Boolean)
      .join("、");
    throw new Error(
      `PineTS 可以執行此指標，但無法自動判定${missing}訊號。` +
        "請在指標中命名 longSignal／shortSignal，或提供做多與做空條件名稱。",
    );
  }
  const suffix = `

// Indicator Lab PineTS signal bridge
plot((${longExpression}) ? 1 : 0, "__IL_LONG__")
plot((${shortExpression}) ? 1 : 0, "__IL_SHORT__")
`;
  return {
    source: `${source.trimEnd()}\n${suffix}`,
    longExpression,
    shortExpression,
  };
}

function normalizeBars(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error("缺少 K 線資料。");
  }
  return rows.map((row) => ({
    openTime: Number(row.openTime),
    open: Number(row.open),
    high: Number(row.high),
    low: Number(row.low),
    close: Number(row.close),
    volume: Number(row.volume ?? 0),
    closeTime: Number(row.closeTime),
    quoteAssetVolume: Number(row.quoteAssetVolume ?? 0),
    numberOfTrades: Number(row.numberOfTrades ?? 0),
    takerBuyBaseAssetVolume: Number(row.takerBuyBaseAssetVolume ?? 0),
    takerBuyQuoteAssetVolume: Number(row.takerBuyQuoteAssetVolume ?? 0),
    ignore: 0,
  }));
}

function normalizeTimeframe(value) {
  const raw = String(value ?? "").trim();
  const aliases = {
    "1": "1m",
    "3": "3m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "45": "45m",
    "60": "1h",
    "120": "2h",
    "180": "3h",
    "240": "4h",
    D: "1d",
    W: "1w",
    M: "1M",
  };
  return aliases[raw] ?? raw;
}

class LocalProvider {
  constructor(bars, request) {
    this.bars = bars;
    this.ticker = String(request.ticker ?? "LOCAL");
    this.timeframe = normalizeTimeframe(request.timeframe ?? "15m");
    this.timezone = String(request.exchangeTimezone ?? "Etc/UTC");
    this.mintick = Number(request.mintick ?? 0.01);
  }

  configure() {}

  async getMarketData(tickerId, timeframe, limit, startDate, endDate) {
    if (String(tickerId) !== this.ticker) {
      throw new Error(
        `本機行情只有 ${this.ticker}，無法執行 request.security(${tickerId})。`,
      );
    }
    const requested = normalizeTimeframe(timeframe);
    let result =
      requested === this.timeframe
        ? [...this.bars]
        : aggregateCandles(this.bars, requested, this.timeframe);
    if (startDate != null) {
      result = result.filter((bar) => bar.openTime >= Number(startDate));
    }
    if (endDate != null) {
      result = result.filter((bar) => bar.openTime <= Number(endDate));
    }
    if (limit != null && Number(limit) > 0 && result.length > Number(limit)) {
      result = result.slice(-Number(limit));
    }
    return result;
  }

  async getSymbolInfo(tickerId) {
    const pricescale = Math.max(1, Math.round(1 / this.mintick));
    return {
      ticker: String(tickerId),
      tickerid: String(tickerId),
      prefix: "LOCAL",
      root: String(tickerId),
      description: String(tickerId),
      type: "crypto",
      main_tickerid: String(tickerId),
      current_contract: "",
      isin: "",
      basecurrency: "",
      currency: "",
      timezone: this.timezone,
      country: "",
      mintick: this.mintick,
      pricescale,
      minmove: 1,
      pointvalue: 1,
      mincontract: 0,
      session: "24x7",
      volumetype: "base",
      expiration_date: 0,
      employees: 0,
      industry: "",
      sector: "",
      shareholders: 0,
      shares_outstanding_float: 0,
      shares_outstanding_total: 0,
      recommendations_buy: 0,
      recommendations_buy_strong: 0,
      recommendations_date: 0,
      recommendations_hold: 0,
      recommendations_sell: 0,
      recommendations_sell_strong: 0,
      recommendations_total: 0,
      target_price_average: 0,
      target_price_date: 0,
      target_price_estimates: 0,
      target_price_high: 0,
      target_price_low: 0,
      target_price_median: 0,
    };
  }
}

function plotValues(context, title) {
  const plot = context.plots?.[title];
  if (!plot || !Array.isArray(plot.data)) {
    throw new Error(`PineTS 沒有輸出 ${title}。`);
  }
  return plot.data.map((item) => {
    if (item && typeof item === "object" && "value" in item) {
      return Boolean(item.value);
    }
    return Boolean(item);
  });
}

async function main() {
  const raw = await readStdin();
  const request = JSON.parse(raw);
  const bars = normalizeBars(request.bars);
  const instrumented = instrumentSource(
    String(request.source ?? ""),
    request.longExpression,
    request.shortExpression,
  );
  const provider = new LocalProvider(bars, request);
  const pine = new PineTS(
    provider,
    String(request.ticker ?? "LOCAL"),
    String(request.timeframe ?? "15m"),
    bars.length,
  );
  if (request.timezone) {
    pine.setTimezone(String(request.timezone));
  }
  pine.setAlertMode("all");
  const context = await pine.run(instrumented.source, bars.length);
  const longValues = plotValues(context, "__IL_LONG__");
  const shortValues = plotValues(context, "__IL_SHORT__");
  const expected = bars.length;
  const pad = (values) => {
    if (values.length >= expected) {
      return values.slice(values.length - expected);
    }
    return Array(expected - values.length).fill(false).concat(values);
  };
  process.stdout.write(
    JSON.stringify({
      long: pad(longValues),
      short: pad(shortValues),
      longExpression: instrumented.longExpression,
      shortExpression: instrumented.shortExpression,
      warnings: context.warnings ?? [],
      engine: "PineTS",
    }),
  );
}

main().catch((error) => {
  process.stderr.write(
    JSON.stringify({
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : null,
    }),
  );
  process.exitCode = 1;
});
