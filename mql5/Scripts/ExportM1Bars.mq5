//+------------------------------------------------------------------+
//|                                                ExportM1Bars.mq5  |
//|  Exports M1 bars of the chart symbol to MQL5/Files/<sym>_M1.csv  |
//|  Use the CSV with research/backtest.py                           |
//+------------------------------------------------------------------+
#property copyright "khaled"
#property version   "1.00"
#property script_show_inputs

input int InpMonths = 12;   // How many months of M1 history to export

void OnStart()
  {
   datetime to   = TimeCurrent();
   datetime from = to - (datetime)InpMonths * 31 * 24 * 3600;

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int n = CopyRates(_Symbol, PERIOD_M1, from, to, rates);
   if(n <= 0)
     {
      Print("CopyRates failed: ", GetLastError(), ". Scroll the M1 chart back or raise Max bars in chart.");
      return;
     }

   string fname = _Symbol + "_M1.csv";
   int fh = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
     {
      Print("FileOpen failed: ", GetLastError());
      return;
     }
   FileWrite(fh, "time", "open", "high", "low", "close", "tick_volume", "spread_points");
   for(int i = 0; i < n; i++)
      FileWrite(fh,
                TimeToString(rates[i].time, TIME_DATE | TIME_MINUTES),
                DoubleToString(rates[i].open, _Digits),
                DoubleToString(rates[i].high, _Digits),
                DoubleToString(rates[i].low, _Digits),
                DoubleToString(rates[i].close, _Digits),
                (string)rates[i].tick_volume,
                (string)rates[i].spread);
   FileClose(fh);
   PrintFormat("Exported %d M1 bars to MQL5/Files/%s (point = %s)", n, fname, DoubleToString(_Point, _Digits));
  }
//+------------------------------------------------------------------+
