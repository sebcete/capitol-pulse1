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
SOURCE_URL = 'https://macrowombat.com/data/congress-trades.json'
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



def load_senate():
    """Use the public, versioned Senate event table. No invented or amended duplicates."""
    import pyarrow.parquet as pq
    out = []
    for year in (TODAY.year - 1, TODAY.year):
        link = (f'https://huggingface.co/datasets/austin-starks/congressional-stock-trades/'
                f'resolve/main/data/political_trade_events/{year}-00000-of-00001.parquet')
        response = SESSION.get(link, timeout=40)
        response.raise_for_status()
        tab = pq.read_table(io.BytesIO(response.content), columns=[
            'eventId','version','chamber','displayName','owner','action','transactionDate',
            'ticker','assetDescription','assetTypeLabel','amountLow','amountHigh',
            'availableAt','supersededAt','sourceUrl'])
        for row in tab.to_pylist():
            if str(row.get('chamber') or '').lower() != 'senate' or row.get('supersededAt') is not None:
                continue
            sym = clean_symbol(row.get('ticker'))
            action = str(row.get('action') or '').lower()
            # Exclude options, bonds and funds whose underlying price is not the purchased asset.
            a_type = str(row.get('assetTypeLabel') or '').lower()
            if any(x in a_type for x in ('option','bond','fund','derivative')):
                continue
            tx = parse_date(row.get('transactionDate'))
            available = parse_date(row.get('availableAt'))
            name = str(row.get('displayName') or '').strip()
            if not (sym and tx and available and name and tx <= available <= TODAY and action in ('purchase','sale')):
                continue
            lo, hi = safe_number(row.get('amountLow')), safe_number(row.get('amountHigh'))
            label = f'${lo:,.0f} - ${hi:,.0f}' if lo is not None and hi is not None else 'Unspecified amount'
            out.append({
                'id': 's'+str(row.get('eventId') or len(out)),
                'member': name,'chamber':'Senate','state':'','ticker':sym,
                'asset': re.sub(r'\s+', ' ', str(row.get('assetDescription') or sym))[:125],
                'owner':str(row.get('owner') or 'not specified').replace('_',' '),
                'type':'buy' if action == 'purchase' else 'sell',
                'tradeDate':tx.isoformat(),'filedDate':available.isoformat(),
                'amountMin':lo,'amountMax':hi,'amountLabel':label,
                'filing':str(row.get('sourceUrl') or '')})
    print(f'Parsed {len(out)} current Senate rows from public point-in-time events', flush=True)
    return out


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
        except Exception:
            pass
    try:
        feed = get_json(SOURCE_URL, 50)
        trades = parse_trades(feed)
    except Exception as ex:
        raise RuntimeError(f'Disclosure feed unavailable: {ex}; preserving last working snapshot')
    if not trades or len(trades) < 50:
        raise RuntimeError('Too few valid disclosed transactions; preserving last working snapshot')
    senate_loaded = False
    try:
        senate_trades = load_senate()
        if senate_trades:
            trades.extend(senate_trades)
            senate_loaded = True
    except Exception as ex:
        print(f'WARN Senate source unavailable; House data still usable: {ex}', flush=True)
    trades.sort(key=lambda x:(x['filedDate'],x['tradeDate']),reverse=True)
    cutoff = TODAY - timedelta(days=190)
    recent = [t for t in trades if parse_date(t['filedDate']) >= cutoff]
    # Rank and display recent activity; limit price fetches to today's most relevant stocks.
    symbols = []
    for t in recent:
        if t['type'] == 'buy' and t['ticker'] not in symbols:
            symbols.append(t['ticker'])
    symbols = symbols[:120]
    old_bars = prior.get('prices', {})
    if not isinstance(old_bars, dict):
        old_bars = {}
    prices = {k:v for k,v in old_bars.items() if isinstance(v,list)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(yahoo_history, symbol):symbol for symbol in symbols}
        for fut in as_completed(futures):
            ticker, new = fut.result()
            if new:
                prices[ticker] = new
    # Never mix old price and today's feed without visible bar dates.
    prices = {sym:bars for sym,bars in prices.items() if sym in symbols and bars}
    price_info = enrich(recent, prices)
    newest_filing = max(t['filedDate'] for t in trades)
    payload = {
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'latestFilingDate': newest_filing,
        'sourceAsOf': str(feed.get('asOf') or ''),
        'sourceName': 'MacroWombat House + Austin Starks Senate event data' if senate_loaded else 'MacroWombat / U.S. House Clerk filings',
        'sourceUrl': SOURCE_URL,
        'senateSource': 'https://huggingface.co/datasets/austin-starks/congressional-stock-trades' if senate_loaded else None,
        'priceSource': 'Yahoo Finance daily historical close (adjusted where available)',
        'method': 'Equal-weight hypothetical buys, entered at first available close strictly after filing date. No fees, spreads, taxes, dividends unless reflected by adjusted close, or interim exits. Not actual member holdings or returns.',
        'trades': recent[:1800],
        'prices': prices,
        'coverage': {
            'feedRows': len(trades),
            'recentRows': len(recent),
            'pricedSymbols': len(price_info),
            'consideredSymbols': len(symbols),
            'chambers': sorted(set(t['chamber'] for t in recent))
        }
    }
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    tmp = TARGET.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    tmp.replace(TARGET)
    print(f'OK {len(recent)} trades, {len(price_info)} priced symbols, last filing {newest_filing}, source {payload["sourceAsOf"]}')

if __name__ == '__main__':
    try:
        build()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
