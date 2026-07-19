import datetime
import time
from evoquant.storage import SQLiteStore
from evoquant.providers.baostock import BaostockProvider
from evoquant.services.instruments import InstrumentMaster
from evoquant.domain import Market, utc_now

store = SQLiteStore("var/evoquant.db")
provider = BaostockProvider()
instruments = InstrumentMaster(store).list_by_market(Market.CN)
symbols = [item.symbol for item in instruments if item.tradable]
total = len(symbols)
print(f"Loaded {total} CN symbols. Running smart incremental sync via Baostock...")

# 设为最近 3 年 (365 * 3 天)
global_start = datetime.date.today() - datetime.timedelta(days=365 * 3)
end = datetime.date.today()

# 增量落盘辅助函数
def store_bars(store, bars):
    now_str = utc_now().isoformat()
    with store.connection() as conn:
        conn.executemany(
            """
            INSERT INTO market_bars (
                symbol, market, session, open, high, low, close, volume,
                amount, adjusted, suspended, limit_up, limit_down, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, market, session) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                amount = excluded.amount,
                adjusted = excluded.adjusted,
                suspended = excluded.suspended,
                limit_up = excluded.limit_up,
                limit_down = excluded.limit_down,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            [
                (
                    bar.symbol,
                    bar.market.value,
                    bar.session.isoformat() if isinstance(bar.session, datetime.date) else str(bar.session),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.amount,
                    1 if bar.adjusted else 0,
                    1 if bar.suspended else 0,
                    1 if bar.limit_up else 0,
                    1 if bar.limit_down else 0,
                    bar.source,
                    now_str
                )
                for bar in bars
            ]
        )

# 查阅单只股票最新行情日期的辅助函数
def get_latest_session(conn, symbol):
    row = conn.execute(
        "SELECT MAX(session) AS latest_session FROM market_bars WHERE market = 'CN' AND symbol = ?",
        (symbol,)
    ).fetchone()
    value = row["latest_session"] if row else None
    return datetime.date.fromisoformat(value) if value else None

# 每 50 个 symbols 一组进行增量拉取和立即入库
batch_size = 50

with store.connection() as conn:
    for i in range(0, total, batch_size):
        batch = symbols[i : i + batch_size]
        
        # 1. 对该 batch 内每个个股进行增量判断，挑出确实需要同步的 symbols
        active_batch = []
        oldest_start = None
        
        for symbol in batch:
            latest = get_latest_session(conn, symbol)
            # 如果已有行情距离今天小于等于 2 天（考虑到周末休市），认定已是最新，跳过下载
            if latest and (datetime.date.today() - latest).days <= 2:
                continue
            active_batch.append(symbol)
            start_date = latest + datetime.timedelta(days=1) if latest else global_start
            if oldest_start is None or start_date < oldest_start:
                oldest_start = start_date
        
        # 2. 如果这 50 个个股全都是最新行情，直接 0 毫秒整体跳过，完全不产生网络请求
        if not active_batch:
            print(f"[{i + len(batch)}/{total}] All {len(batch)} symbols are already up to date. Skipped.")
            continue
            
        # 3. 发起网络增量拉取
        t0 = time.time()
        try:
            bars = provider.sync_bars(active_batch, Market.CN, oldest_start, end)
            if bars:
                store_bars(store, bars)
            elapsed = time.time() - t0
            print(f"[{i + len(batch)}/{total}] Synced and saved {len(active_batch)} symbols (requested from {oldest_start}) in {elapsed:.1f}s.")
        except Exception as e:
            print(f"Failed batch sync for CN symbols {active_batch[0]}-{active_batch[-1]}: {e}")

print("Robust full market CN 3-year bar sync completed!")
