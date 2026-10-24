//+------------------------------------------------------------------+
//|                                              GoldScalperPro.mq5  |
//|  Scalper for XAUUSD on M1 / M3 / M5, two entry modes:            |
//|  - STRETCH (default, best in walk-forward study on M1):          |
//|    fade price stretched > N*ATR from EMA50 with extreme RSI      |
//|  - PULLBACK: pullback to fast EMA inside trend + RSI re-cross    |
//|  - Exit : ATR-based SL, R-multiple TP, optional BE/trail, time   |
//|  - Risk : % risk per trade, daily target lock, daily loss limit, |
//|           hard equity drawdown guard from peak (default 9%)      |
//+------------------------------------------------------------------+
#property copyright "khaled"
#property version   "1.00"

#include <Trade\Trade.mqh>

enum ENUM_GSP_STRATEGY
  {
   STRAT_STRETCH  = 0,   // Stretch mean-reversion
   STRAT_PULLBACK = 1    // Trend pullback
  };

//--- Timeframe & signal
input group "=== Strategy ==="
input ENUM_GSP_STRATEGY InpStrategy    = STRAT_STRETCH; // Entry mode
input double InpStretchAtr             = 4.0;         // STRETCH: distance from slow EMA in ATRs
input double InpStretchRsi             = 25.0;        // STRETCH: buy if RSI < this, sell if RSI > 100 - this
input int    InpMaxHoldBars            = 120;         // Close position after N bars (0 = off)

input group "=== Timeframe & Signal ==="
input ENUM_TIMEFRAMES InpTF            = PERIOD_M1;   // Working timeframe (M1 / M3 / M5)
input ENUM_TIMEFRAMES InpHTF           = PERIOD_M15;  // Higher timeframe trend filter
input int    InpEmaFast                = 20;          // Fast EMA (pullback line)
input int    InpEmaSlow                = 50;          // Slow EMA
input int    InpEmaTrend               = 200;         // Trend EMA
input int    InpHtfEma                 = 50;          // HTF EMA period
input int    InpRsiPeriod              = 7;           // RSI period
input double InpRsiBuyLevel            = 45.0;        // RSI re-cross up level (buy)
input double InpRsiSellLevel           = 55.0;        // RSI re-cross down level (sell)
input int    InpAdxPeriod              = 14;          // ADX period
input double InpAdxMin                 = 20.0;        // Minimum ADX (trend strength)
input int    InpAtrPeriod              = 14;          // ATR period
input double InpPullbackAtr            = 0.30;        // Pullback must touch fast EMA +/- this * ATR

//--- Exits
input group "=== Exits ==="
input double InpSlAtrMult              = 3.0;         // Stop loss = ATR * this
input double InpTpR                    = 0.75;        // Take profit in R (multiple of SL)
input double InpBeTriggerR             = 99.0;        // Move SL to break-even after this many R (99 = off)
input double InpTrailStartR            = 99.0;        // Start ATR trailing after this many R (99 = off)
input double InpTrailAtrMult           = 1.0;         // Trailing distance = ATR * this

//--- Cost filters
input group "=== Spread & Volatility Filters ==="
input double InpMaxSpreadPrice         = 0.35;        // Max allowed spread (price units, gold: 0.35 = 35 cents)
input double InpMinAtrSpreadMult       = 4.0;         // Trade only if ATR >= spread * this

//--- Risk
input group "=== Risk Management ==="
input double InpRiskPct                = 0.50;        // Risk per trade (% of equity)
input double InpDailyTargetPct         = 3.00;        // Daily profit target (% of day-start equity) -> stop for the day
input double InpDailyLossPct           = 3.00;        // Daily loss limit (%) -> close all, stop for the day
input double InpMaxDDPct               = 9.00;        // Hard max drawdown from equity peak (%) -> close all, halt EA
input int    InpMaxTradesPerDay        = 12;          // Max trades per day
input int    InpMaxConsecLosses        = 4;           // Stop for the day after N consecutive losses
input int    InpCooldownBars           = 3;           // Bars to wait after a losing trade
input bool   InpResetDDPeak            = false;       // Reset stored equity peak / halt flag on start

//--- Session
input group "=== Session (server time) ==="
input int    InpStartHour              = 9;           // Start trading hour
input int    InpEndHour                = 16;          // Stop opening trades at this hour
input int    InpFridayCloseHour        = 20;          // Close everything Friday at this hour

input group "=== Misc ==="
input long   InpMagic                  = 26026;       // Magic number
input int    InpSlippagePoints         = 30;          // Max slippage (points)

//--- globals
CTrade   trade;
int      hEmaFast, hEmaSlow, hEmaTrend, hHtfEma, hRsi, hAtr, hAdx;
datetime lastBarTime      = 0;
datetime currentDay       = 0;
double   dayStartEquity   = 0.0;
bool     dayLocked        = false;
bool     eaHalted         = false;
int      tradesToday      = 0;
int      consecLosses     = 0;
int      cooldownLeft     = 0;
double   entryRiskDist    = 0.0;   // initial SL distance of the open position
string   gvPeak, gvHalt;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpTF != PERIOD_M1 && InpTF != PERIOD_M3 && InpTF != PERIOD_M5)
      Print("Warning: EA was designed/studied for M1, M3, M5. Current TF = ", EnumToString(InpTF));

   hEmaFast  = iMA(_Symbol, InpTF,  InpEmaFast,  0, MODE_EMA, PRICE_CLOSE);
   hEmaSlow  = iMA(_Symbol, InpTF,  InpEmaSlow,  0, MODE_EMA, PRICE_CLOSE);
   hEmaTrend = iMA(_Symbol, InpTF,  InpEmaTrend, 0, MODE_EMA, PRICE_CLOSE);
   hHtfEma   = iMA(_Symbol, InpHTF, InpHtfEma,   0, MODE_EMA, PRICE_CLOSE);
   hRsi      = iRSI(_Symbol, InpTF, InpRsiPeriod, PRICE_CLOSE);
   hAtr      = iATR(_Symbol, InpTF, InpAtrPeriod);
   hAdx      = iADX(_Symbol, InpTF, InpAdxPeriod);

   if(hEmaFast == INVALID_HANDLE || hEmaSlow == INVALID_HANDLE || hEmaTrend == INVALID_HANDLE ||
      hHtfEma == INVALID_HANDLE || hRsi == INVALID_HANDLE || hAtr == INVALID_HANDLE || hAdx == INVALID_HANDLE)
     {
      Print("Failed to create indicator handles");
      return(INIT_FAILED);
     }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   gvPeak = "GSP_PEAK_" + _Symbol + "_" + IntegerToString(InpMagic);
   gvHalt = "GSP_HALT_" + _Symbol + "_" + IntegerToString(InpMagic);
   if(InpResetDDPeak || MQLInfoInteger(MQL_TESTER))
     {
      GlobalVariableDel(gvPeak);
      GlobalVariableDel(gvHalt);
     }
   if(!GlobalVariableCheck(gvPeak))
      GlobalVariableSet(gvPeak, AccountInfoDouble(ACCOUNT_EQUITY));
   eaHalted = GlobalVariableCheck(gvHalt) && GlobalVariableGet(gvHalt) > 0.5;

   StartNewDay();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(hEmaFast);
   IndicatorRelease(hEmaSlow);
   IndicatorRelease(hEmaTrend);
   IndicatorRelease(hHtfEma);
   IndicatorRelease(hRsi);
   IndicatorRelease(hAtr);
   IndicatorRelease(hAdx);
   Comment("");
  }

//+------------------------------------------------------------------+
datetime DayOf(datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   s.hour = 0; s.min = 0; s.sec = 0;
   return(StructToTime(s));
  }

void StartNewDay()
  {
   currentDay     = DayOf(TimeCurrent());
   dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   dayLocked      = false;
   tradesToday    = 0;
   consecLosses   = 0;
  }

//+------------------------------------------------------------------+
bool HasPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return(true);
     }
   return(false);
  }

void CloseAll()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         trade.PositionClose(ticket);
     }
  }

//+------------------------------------------------------------------+
//| Close positions held for InpMaxHoldBars bars or more             |
//+------------------------------------------------------------------+
void CloseExpired()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      int held = iBarShift(_Symbol, InpTF, (datetime)PositionGetInteger(POSITION_TIME));
      if(held >= InpMaxHoldBars)
         trade.PositionClose(ticket);
     }
  }

//+------------------------------------------------------------------+
//| Risk guards: run on every tick                                   |
//+------------------------------------------------------------------+
void CheckRiskGuards()
  {
   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak = GlobalVariableGet(gvPeak);
   if(eq > peak)
     {
      peak = eq;
      GlobalVariableSet(gvPeak, peak);
     }

   // 1) Hard max drawdown from peak -> halt EA permanently (until reset)
   if(!eaHalted && peak > 0 && (peak - eq) / peak * 100.0 >= InpMaxDDPct)
     {
      CloseAll();
      eaHalted = true;
      GlobalVariableSet(gvHalt, 1.0);
      Print("MAX DRAWDOWN GUARD HIT: equity ", eq, " peak ", peak, ". EA halted.");
     }

   if(dayLocked || dayStartEquity <= 0) return;
   double dayPct = (eq - dayStartEquity) / dayStartEquity * 100.0;

   // 2) Daily target reached -> bank it and stop for the day
   if(dayPct >= InpDailyTargetPct)
     {
      CloseAll();
      dayLocked = true;
      Print("Daily target reached: ", DoubleToString(dayPct, 2), "%. Done for today.");
     }
   // 3) Daily loss limit -> stop for the day
   else if(dayPct <= -InpDailyLossPct)
     {
      CloseAll();
      dayLocked = true;
      Print("Daily loss limit hit: ", DoubleToString(dayPct, 2), "%. Done for today.");
     }
  }

//+------------------------------------------------------------------+
//| Break-even and ATR trailing for the open position                |
//+------------------------------------------------------------------+
void ManagePosition(double atr)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;

      long   type  = PositionGetInteger(POSITION_TYPE);
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double risk  = entryRiskDist > 0 ? entryRiskDist : MathAbs(open - sl);
      if(risk <= 0) continue;

      double stopLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
      double newSl = sl;

      if(type == POSITION_TYPE_BUY)
        {
         double profitR = (bid - open) / risk;
         if(profitR >= InpBeTriggerR)
            newSl = MathMax(newSl, open + (ask - bid));            // cover spread
         if(profitR >= InpTrailStartR && atr > 0)
            newSl = MathMax(newSl, bid - atr * InpTrailAtrMult);
         newSl = NormalizeDouble(newSl, _Digits);
         if(newSl > sl + _Point && bid - newSl > stopLevel)
            trade.PositionModify(ticket, newSl, tp);
        }
      else
        {
         double profitR = (open - ask) / risk;
         if(profitR >= InpBeTriggerR)
            newSl = (sl == 0) ? open - (ask - bid) : MathMin(newSl, open - (ask - bid));
         if(profitR >= InpTrailStartR && atr > 0)
            newSl = (newSl == 0) ? ask + atr * InpTrailAtrMult : MathMin(newSl, ask + atr * InpTrailAtrMult);
         newSl = NormalizeDouble(newSl, _Digits);
         if((sl == 0 || newSl < sl - _Point) && newSl - ask > stopLevel)
            trade.PositionModify(ticket, newSl, tp);
        }
     }
  }

//+------------------------------------------------------------------+
//| Position size from risk % and SL distance                        |
//+------------------------------------------------------------------+
double LotsForRisk(double slDist)
  {
   double eq        = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = eq * InpRiskPct / 100.0;
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0) tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tickSize <= 0 || tickValue <= 0 || slDist <= 0) return(0.0);

   double lossPerLot = slDist / tickSize * tickValue;
   double lots       = riskMoney / lossPerLot;

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots / step) * step;
   if(lots < vmin) return(0.0);           // cannot respect risk with min lot -> skip trade
   return(MathMin(lots, vmax));
  }

//+------------------------------------------------------------------+
bool CopyOne(int handle, int buffer, int shift, int count, double &arr[])
  {
   ArraySetAsSeries(arr, true);
   return(CopyBuffer(handle, buffer, shift, count, arr) == count);
  }

//+------------------------------------------------------------------+
//| Track result of closed trades (consecutive losses / cooldown)    |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic) return;
   if(HistoryDealGetString(trans.deal, DEAL_SYMBOL) != _Symbol) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   double pnl = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
              + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
              + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   if(pnl < 0)
     {
      consecLosses++;
      cooldownLeft = InpCooldownBars;
     }
   else
      consecLosses = 0;
   entryRiskDist = 0.0;
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(DayOf(TimeCurrent()) != currentDay)
      StartNewDay();

   CheckRiskGuards();

   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);
   if(now.day_of_week == 5 && now.hour >= InpFridayCloseHour && HasPosition())
      CloseAll();

   double atrArr[];
   if(!CopyOne(hAtr, 0, 1, 1, atrArr)) return;
   double atr = atrArr[0];

   if(HasPosition())
      ManagePosition(atr);

   // act on new bar only
   datetime barTime = iTime(_Symbol, InpTF, 0);
   if(barTime == lastBarTime) return;
   lastBarTime = barTime;
   if(cooldownLeft > 0) cooldownLeft--;
   if(InpMaxHoldBars > 0)
      CloseExpired();

   string status = StringFormat("GoldScalperPro | TF %s | Day P/L %.2f%% | Trades %d | %s",
                                EnumToString(InpTF),
                                dayStartEquity > 0 ? (AccountInfoDouble(ACCOUNT_EQUITY) - dayStartEquity) / dayStartEquity * 100.0 : 0.0,
                                tradesToday,
                                eaHalted ? "HALTED (max DD)" : (dayLocked ? "Locked for today" : "Active"));
   Comment(status);

   // ---- entry gates
   if(eaHalted || dayLocked) return;
   if(HasPosition()) return;
   if(tradesToday >= InpMaxTradesPerDay) return;
   if(consecLosses >= InpMaxConsecLosses) return;
   if(cooldownLeft > 0) return;
   if(now.hour < InpStartHour || now.hour >= InpEndHour) return;
   if(now.day_of_week == 5 && now.hour >= InpFridayCloseHour - 1) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double spread = ask - bid;
   if(spread > InpMaxSpreadPrice) return;
   if(atr < spread * InpMinAtrSpreadMult) return;

   // ---- indicator values on closed bars (index 0 = bar 1, index 1 = bar 2)
   double emaF[], emaS[], emaT[], htf[], rsi[], adx[];
   if(!CopyOne(hEmaFast, 0, 1, 2, emaF)) return;
   if(!CopyOne(hEmaSlow, 0, 1, 2, emaS)) return;
   if(!CopyOne(hEmaTrend, 0, 1, 2, emaT)) return;
   if(!CopyOne(hHtfEma, 0, 1, 1, htf)) return;
   if(!CopyOne(hRsi, 0, 1, 2, rsi)) return;
   if(!CopyOne(hAdx, 0, 1, 1, adx)) return;   // buffer 0 = main ADX line

   double o1 = iOpen(_Symbol, InpTF, 1);
   double h1 = iHigh(_Symbol, InpTF, 1);
   double l1 = iLow(_Symbol, InpTF, 1);
   double c1 = iClose(_Symbol, InpTF, 1);
   double htfClose = iClose(_Symbol, InpHTF, 1);

   bool buySig = false, sellSig = false;
   if(InpStrategy == STRAT_STRETCH)
     {
      double z = (c1 - emaS[0]) / atr;                            // distance from slow EMA in ATRs
      buySig  = z < -InpStretchAtr && rsi[0] < InpStretchRsi;
      sellSig = z >  InpStretchAtr && rsi[0] > 100.0 - InpStretchRsi;
     }
   else
     {
      if(adx[0] < InpAdxMin) return;

      bool upTrend   = emaF[0] > emaS[0] && emaS[0] > emaT[0] && c1 > emaT[0] && htfClose > htf[0];
      bool downTrend = emaF[0] < emaS[0] && emaS[0] < emaT[0] && c1 < emaT[0] && htfClose < htf[0];

      buySig  = upTrend
                && l1 <= emaF[0] + atr * InpPullbackAtr           // pulled back to fast EMA
                && c1 > o1 && c1 > emaF[0]                        // bullish rejection candle
                && rsi[1] < InpRsiBuyLevel && rsi[0] >= InpRsiBuyLevel;
      sellSig = downTrend
                && h1 >= emaF[0] - atr * InpPullbackAtr
                && c1 < o1 && c1 < emaF[0]
                && rsi[1] > InpRsiSellLevel && rsi[0] <= InpRsiSellLevel;
     }

   if(!buySig && !sellSig) return;

   double slDist = atr * InpSlAtrMult;
   double lots   = LotsForRisk(slDist + spread);
   if(lots <= 0) return;

   bool ok = false;
   if(buySig)
     {
      double sl = NormalizeDouble(ask - slDist, _Digits);
      double tp = NormalizeDouble(ask + slDist * InpTpR, _Digits);
      ok = trade.Buy(lots, _Symbol, ask, sl, tp, "GSP buy");
     }
   else
     {
      double sl = NormalizeDouble(bid + slDist, _Digits);
      double tp = NormalizeDouble(bid - slDist * InpTpR, _Digits);
      ok = trade.Sell(lots, _Symbol, bid, sl, tp, "GSP sell");
     }

   if(ok && (trade.ResultRetcode() == TRADE_RETCODE_DONE || trade.ResultRetcode() == TRADE_RETCODE_PLACED))
     {
      tradesToday++;
      entryRiskDist = slDist;
     }
   else
      Print("Order failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
  }
//+------------------------------------------------------------------+
