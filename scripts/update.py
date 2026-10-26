#!/usr/bin/env python3
"""Build transparent, dated, disclosure-based public stock trade analytics.
No brokerage keys, paid APIs, or invented market returns.
"""
import csv
import io
import json
import os
import re
import sys
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'site' / 'data.json'
SOURCE_URL = 'https://huggingface.co/datasets/austin-starks/congressional-stock-trades'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'CapitolPulsePersonalResearch/1.0 (personal noncommercial tracker; contact via GitHub repository)', 'Accept': 'application/json, text/csv, */*'})
TODAY = datetime.now(timezone.utc).date()


def get_json(url, timeout=30):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00')[:10]).date()
    except (ValueError, TypeError):
        return None


def safe_number(v):
    try:
        n = float(str(v).replace(',', ''))
        return round(n, 2) if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def clean_symbol(sym):
    s = str(sym or '').strip().upper().replace('.', '-')
    return s if re.fullmatch(r'[A-Z]{1,6}(-[A-Z])?', s) else ''


def parse_trades(blob):
    rows = blob.get('rows') if isinstance(blob, dict) else blob
    if not isinstance(rows, list):
        raise RuntimeError('Unexpected disclosure source schema; refusing to publish fabricated or empty results.')
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = clean_symbol(row.get('ticker'))
        name = re.sub(r'^Hon\.\s*', '', str(row.get('member_name') or '').strip(), flags=re.I)
        tx = parse_date(row.get('tx_date'))
        filed = parse_date(row.get('filing_date'))
        typ = str(row.get('tx_type') or '').upper()
        if not (name and sym and tx and filed and typ in ('P', 'S', 'S_PARTIAL') and tx <= filed <= TODAY):
            continue
        # Exact duplicate detection; two identical, separately reported transactions are not always distinguishable.
        key = (name, sym, str(tx), str(filed), typ, str(row.get('amount_min')), str(row.get('amount_max')), row.get('source_pdf'))
        if key in seen:
            continue
        seen.add(key)
        result.append({
            'id': 't' + str(len(result)),
            'member': name,
            'chamber': str(row.get('chamber') or '').title(),
            'state': str(row.get('state_district') or ''),
            'ticker': sym,
            'asset': re.sub(r'\s+', ' ', str(row.get('asset_name') or sym))[:125],
            'owner': str(row.get('owner') or 'not specified').replace('_', ' '),
            'type': 'buy' if typ == 'P' else 'sell',
            'tradeDate': tx.isoformat(),
            'filedDate': filed.isoformat(),
            'amountMin': safe_number(row.get('amount_min')),
            'amountMax': safe_number(row.get('amount_max')),
            'amountLabel': str(row.get('amount_label') or 'Amount bracket unavailable'),
            'filing': str(row.get('source_pdf') or ''),
        })
    result.sort(key=lambda x:(x['filedDate'], x['tradeDate']),reverse=True)
    return result



def load_events():
    """Read current, reconciled House and Senate disclosures, not superseded versions."""
    import pyarrow.parquet as pq
    cols = ['eventId','version','chamber','displayName','memberId','identitySource',
            'owner','action','transactionDate','ticker','assetDescription',
            'assetTypeLabel','amountLow','amountHigh','availableAt','supersededAt','sourceUrl']
    results = []
    seen = set()
    years = []
    for year in (TODAY.year - 1, TODAY.year):
        url = f'{SOURCE_URL}/resolve/main/data/political_trade_events/{year}-00000-of-00001.parquet'
        try:
            response = SESSION.get(url, timeout=90)
            response.raise_for_status()
            table = pq.read_table(io.BytesIO(response.content), columns=cols)
        except Exception as exc:
            if year == TODAY.year:
                raise RuntimeError(f'Current-year public dataset inaccessible: {exc}') from exc
            print(f'WARN older {year} data unavailable: {exc}', flush=True)
            continue
        years.append(year)
        for r in table.to_pylist():
            if str(r.get('identitySource') or '').lower() not in ('legislators','override'):
                continue
            if r.get('supersededAt') is not None:
                continue
            action = str(r.get('action') or '').lower().strip()
            if action not in ('purchase', 'sale', 'sale_partial', 'partial_sale'):
                continue
            category = str(r.get('assetTypeLabel') or '').lower()
            if any(x in category for x in ('option','bond','fund','derivative','crypto')):
                continue
            sym = clean_symbol(r.get('ticker'))
            trade = parse_date(r.get('transactionDate'))
            filed = parse_date(r.get('availableAt'))
            name = str(r.get('displayName') or '').strip()
            if not (sym and trade and filed and name and trade <= filed <= TODAY):
                continue
            eid = str(r.get('eventId') or '')
            unique = (eid, str(r.get('version') or '')) if eid else (name, sym, str(trade), str(filed), action)
            if unique in seen:
                continue
            seen.add(unique)
            lo, hi = safe_number(r.get('amountLow')), safe_number(r.get('amountHigh'))
            label = ('$' + f'{lo:,.0f} – ' + '$' + f'{hi:,.0f}') if lo is not None and hi is not None else 'Not specified'
            results.append({
                'id':eid or ('event-' + str(len(results))),
                'member':name,'chamber':str(r.get('chamber') or '').title(),
                'state':'','ticker':sym,
                'asset':re.sub(r'\s+', ' ', str(r.get('assetDescription') or sym))[:125],
                'owner':str(r.get('owner') or 'not specified').replace('_',' '),
                'type':'buy' if action == 'purchase' else 'sell',
                'tradeDate':trade.isoformat(),'filedDate':filed.isoformat(),
                'amountMin':lo,'amountMax':hi,'amountLabel':label,
                'filing':str(r.get('sourceUrl') or '')})
        print(f'Loaded year {year}, accepted {len(results)} stock transactions so far', flush=True)
    results.sort(key=lambda t:(t['filedDate'],t['tradeDate']), reverse=True)
    if len(results) < 50:
        raise RuntimeError(f'Only {len(results)} valid transactions in {years}; refusing incomplete data')
    return results, years


def yahoo_history(ticker):
    # Yahoo's unauthenticated chart interface may change or throttle. Fail closed when unavailable.
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}'
    q = {'range': '1y', 'interval': '1d', 'events': 'history', 'includeAdjustedClose': 'true'}
    try:
        r = SESSION.get(url, params=q, timeout=12, headers={'User-Agent': 'Mozilla/5.0 (compatible; CapitolPulse/1.0)'})
        r.raise_for_status()
        obj = r.json()['chart']['result'][0]
        times = obj.get('timestamp') or []
        indicators = obj.get('indicators') or {}
        # Adjusted close when provided; otherwise regular close (may not handle splits/dividends).
        adjusted = (indicators.get('adjclose') or [{}])[0].get('adjclose')
        raw_close = (indicators.get('quote') or [{}])[0].get('close') or []
        closes = adjusted if adjusted and len(adjusted) == len(times) else raw_close
        bars = []
        for stamp, price in zip(times, closes):
            price = safe_number(price)
            if price is not None and price > 0:
                date = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
                bars.append([date, price])
        if len(bars) >= 5:
            return ticker, bars[-260:]
    except (requests.RequestException, ValueError, IndexError, KeyError, TypeError) as exc:
        print(f'WARN price {ticker}: {exc}', flush=True)
    return ticker, None


def after_price(series, date):
    # Only a close STRICTLY after the public filing; same-day timing is unknown.
    for day, close in series:
        if day > date:
            return close, day
    return None, None


def enrich(trades, prices):
    latest_prices = {}
    for ticker, bars in prices.items():
        if bars:
            latest_prices[ticker] = {'date': bars[-1][0], 'close': bars[-1][1]}
    for t in trades:
        arr = prices.get(t['ticker'], [])
        t['entryPrice'] = t['lastPrice'] = t['returnPct'] = t['entryDate'] = t['priceDate'] = None
        if not arr or t['type'] != 'buy':
            continue
        start, date = after_price(arr, t['filedDate'])
        if start is None or arr[-1][0] <= date:
            continue
        last = arr[-1][1]
        if not (last and start and last > 0):
            continue
        t['entryPrice'] = start
        t['entryDate'] = date
        t['lastPrice'] = last
        t['priceDate'] = arr[-1][0]
        t['returnPct'] = round(100 * (last / start - 1), 2)
    return latest_prices


def build():
    prior = {}
    if TARGET.exists():
        try:
            prior = json.loads(TARGET.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    try:
        trades, years = load_events()
    except Exception as exc:
        raise RuntimeError(f'Disclosures unavailable: {exc}; preserving last working snapshot') from exc
    cutoff = TODAY - timedelta(days=190)
    recent = [t for t in trades if parse_date(t['filedDate']) >= cutoff]
    if len(recent) < 15:
        raise RuntimeError(f'Only {len(recent)} recent records; preserving previous snapshot')
    symbols = []
    for trade in recent:
        if trade['type'] == 'buy' and trade['ticker'] not in symbols:
            symbols.append(trade['ticker'])
    symbols = symbols[:120]
    old = prior.get('prices', {})
    prices = {k:v for k,v in old.items() if isinstance(v,list)} if isinstance(old,dict) else {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(yahoo_history, symbol):symbol for symbol in symbols}
        for fut in as_completed(futures):
            ticker, new = fut.result()
            if new:
                prices[ticker] = new
    prices = {sym:bars for sym,bars in prices.items() if sym in symbols and bars}
    latest = enrich(recent, prices)
    latest_filing = max(t['filedDate'] for t in recent)
    chambers = sorted(set(t['chamber'] for t in recent))
    payload = {
        'generatedAt':datetime.now(timezone.utc).isoformat(),
        'latestFilingDate':latest_filing,
        'sourceAsOf':str(TODAY),
        'sourceName':'Austin Starks reconciled public House + Senate disclosures',
        'sourceUrl':SOURCE_URL,
        'senateSource':SOURCE_URL if 'Senate' in chambers else None,
        'priceSource':'Yahoo Finance daily historical close (adjusted where available)',
        'method':'Equal-weight simulated buys at first close strictly after public availability date. Excludes costs, taxes, and interim sales; not verified holdings.',
        'trades':recent[:1800],'prices':prices,
        'coverage':{'feedRows':len(trades),'recentRows':len(recent),
                    'pricedSymbols':len(latest),'consideredSymbols':len(symbols),
                    'chambers':chambers,'sourceYears':years},
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    tmp = TARGET.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    tmp.replace(TARGET)
    print(f'OK {len(recent)} recent trades, {len(latest)} priced symbols, latest {latest_filing}, chambers {chambers}', flush=True)


if __name__ == '__main__':
    try:
        build()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
