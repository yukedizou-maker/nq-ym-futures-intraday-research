# ============================================================
# YM Opening Strategy V2 - 12 rules + conflicts + dynamic 9% margin sizing
# Paste this whole cell AFTER your parquet-download cell in Colab.
# ============================================================

import os, sys, math, json, shutil, warnings, subprocess
warnings.filterwarnings('ignore')

# ---------- 0) CONFIG ----------
DATA_PATH = '/content/YM_databento/YM_1MIN_2011_2026.parquet'
OUT_DIR   = '/content/YM_V2_margin30_backtest'

INITIAL_CAPITAL = 50_000.0

# Contract settings. Keep YM for the full-size contract.
# To test MYM with the same price series, change CONTRACT_NAME='MYM' and POINT_VALUE=0.5,
# and also set COMMISSION_PER_SIDE to your actual MYM all-in commission/fees.
CONTRACT_NAME = 'YM'
POINT_VALUE = 5.0                  # YM = $5 per index point per contract
COMMISSION_PER_SIDE = 2.50        # CHANGE to your real all-in commission/fees per side
SLIPPAGE_POINTS = 1.0             # adverse slippage on entry AND exit, in index points

# Dynamic margin sizing:
# theoretical margin = notional value * 9%
# maximum margin budget = current account equity * 30%
MARGIN_RATE = 0.09                 # 9% of notional value per contract
MARGIN_BUDGET_PCT = 0.30           # use at most 30% of CURRENT equity as margin
USE_SCORE_TO_SCALE_MARGIN = False  # False = every accepted signal may use the full 30% budget
FULL_MARGIN_SCORE = 20             # only used if USE_SCORE_TO_SCALE_MARGIN=True
MAX_CONTRACTS = None               # e.g. 10 to hard-cap size; None = no extra cap

MIN_NET_SCORE = 5                 # long_score-short_score smaller than this => no trade
RESONANCE_MIN_SCORE = 18          # resonance mode requires >=2 same-side rules OR this score
AUTO_DOWNLOAD_ZIP = True

WEIGHTS = {
    'J':15, 'E':13, 'N5':12, 'A':11, 'M':10, 'C':10,
    'B':8, 'F':7, 'D':5, 'G':4, 'I':3, 'K':2,
}

RULE_META = {
    'A':  {'side':'LONG',  'entry':'09:30', 'exit':'10:00'},
    'B':  {'side':'SHORT', 'entry':'09:30', 'exit':'10:00'},
    'C':  {'side':'SHORT', 'entry':'09:30', 'exit':'10:00'},
    'D':  {'side':'LONG',  'entry':'09:30', 'exit':'10:00'},
    'E':  {'side':'LONG',  'entry':'09:45', 'exit':'10:30'},
    'F':  {'side':'LONG',  'entry':'09:45', 'exit':'10:30'},
    'G':  {'side':'SHORT', 'entry':'09:45', 'exit':'10:30'},
    'I':  {'side':'SHORT', 'entry':'09:30', 'exit':'10:00'},
    'J':  {'side':'SHORT', 'entry':'09:30', 'exit':'10:00'},
    'K':  {'side':'LONG',  'entry':'09:45', 'exit':'10:30'},
    'M':  {'side':'LONG',  'entry':'09:30', 'exit':'10:00'},
    'N5': {'side':'LONG',  'entry':'09:45', 'exit':'10:30'},
}

# Expected trigger counts from our previous 2011-2026 research.
# These are a sanity check that feature construction is consistent.
EXPECTED_COUNTS = {
    'A':193, 'B':233, 'C':60, 'D':191, 'E':223, 'F':140,
    'G':60, 'I':179, 'J':149, 'K':149, 'M':294, 'N5':254,
}

# Conflict cleanup. Only the larger / clearer intersections are hard-coded.
# NO_TRADE: remove BOTH rules if the pair is present.
NO_TRADE_PAIRS = {
    frozenset(('B','N5')),  # both negative on the intersection
    frozenset(('B','E')),   # both negative on the intersection
    frozenset(('E','J')),   # both negative on the intersection
}
# WINNER_PAIRS: remove the weaker rule if both are present.
WINNER_PAIRS = {
    frozenset(('D','I')): 'D',
    frozenset(('B','M')): 'M',
    frozenset(('B','K')): 'B',
    frozenset(('A','J')): 'A',
    frozenset(('A','G')): 'A',
    frozenset(('I','K')): 'I',
    # smaller intersections below; keep as V1 conflict logic from prior research
    frozenset(('G','N5')): 'G',
    frozenset(('C','N5')): 'C',
    frozenset(('F','J')): 'F',
    frozenset(('J','K')): 'J',
    frozenset(('C','M')): 'C',
    frozenset(('C','E')): 'E',
    frozenset(('G','M')): 'M',
}

os.makedirs(OUT_DIR, exist_ok=True)

# ---------- 1) IMPORTS / PARQUET ENGINE ----------
try:
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
except Exception:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'numpy', 'pandas', 'matplotlib'])
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt

try:
    import pyarrow  # noqa
except Exception:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'pyarrow'])

if not os.path.exists(DATA_PATH):
    raise FileNotFoundError(
        f'找不到数据文件: {DATA_PATH}\n'
        'Colab 重连/重启后 /content 会被清空。请先重新运行前面的 Databento 下载/合并代码。'
    )

print('='*80)
print('YM V2 组合策略回测：9%理论保证金 + 最多30%账户权益做保证金')
print('数据:', DATA_PATH)
print('输出:', OUT_DIR)
print('='*80)

# ---------- 2) LOAD + NORMALIZE COLUMNS ----------
print('\n[1/8] 读取 1分钟 Parquet...')
df = pd.read_parquet(DATA_PATH)
print(f'原始: {len(df):,} rows, {len(df.columns)} columns')

# If timestamp is index, expose it.
if isinstance(df.index, pd.DatetimeIndex):
    idx_name = df.index.name or 'timestamp_index'
    if idx_name in df.columns:
        idx_name = 'timestamp_index'
    df = df.reset_index().rename(columns={df.index.name or 'index': idx_name})

# Case-insensitive map
lower_map = {str(c).lower(): c for c in df.columns}

def find_col(cands, required=True):
    for c in cands:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    if required:
        raise KeyError(f'找不到列 {cands}; 实际列为: {list(df.columns)}')
    return None

# Prefer the explicitly-created ET column if present.
ts_col = find_col(['timestamp_et','ts_event','timestamp','datetime','time','date_time','timestamp_index'])
o_col  = find_col(['open'])
h_col  = find_col(['high'])
l_col  = find_col(['low'])
c_col  = find_col(['close'])
inst_col = find_col(['instrument_id','instrument','contract_id'], required=False)

use_cols = [ts_col, o_col, h_col, l_col, c_col] + ([inst_col] if inst_col else [])
df = df[use_cols].copy()
df.columns = ['_ts','open','high','low','close'] + (['instrument_id'] if inst_col else [])

for c in ['open','high','low','close']:
    df[c] = pd.to_numeric(df[c], errors='coerce')

ts = pd.to_datetime(df['_ts'], errors='coerce')

# Normalize to America/New_York.
# timestamp_et => assume ET if naive; ts_event etc => assume UTC if naive.
try:
    tz_now = ts.dt.tz
except Exception:
    tz_now = None

if tz_now is None:
    if 'et' in str(ts_col).lower():
        ts = ts.dt.tz_localize('America/New_York', ambiguous='infer', nonexistent='shift_forward')
    else:
        ts = ts.dt.tz_localize('UTC').dt.tz_convert('America/New_York')
else:
    ts = ts.dt.tz_convert('America/New_York')

df['_ts'] = ts
if 'instrument_id' not in df.columns:
    df['instrument_id'] = 1

df = df.dropna(subset=['_ts','open','high','low','close']).sort_values('_ts').reset_index(drop=True)

# Minute-of-day and CME research trade-date:
# 18:00-23:59 belongs to the NEXT calendar trade date.
mins = (df['_ts'].dt.hour * 60 + df['_ts'].dt.minute).astype('int16')
base_date = df['_ts'].dt.tz_localize(None).dt.normalize()
df['_minute'] = mins
df['_trade_date'] = base_date + pd.to_timedelta((mins >= 18*60).astype('int8'), unit='D')

print('时间范围 ET:', df['_ts'].iloc[0], '->', df['_ts'].iloc[-1])

# ---------- 3) BUILD DAILY FEATURES ----------
def lin_r2(y):
    y = np.asarray(y, dtype='float64')
    n = len(y)
    if n < 3 or np.nanstd(y) == 0:
        return np.nan
    x = np.arange(n, dtype='float64')
    r = np.corrcoef(x, y)[0,1]
    return float(r*r) if np.isfinite(r) else np.nan

def one_day_features(td, g):
    g = g.sort_values('_ts')
    m = g['_minute'].to_numpy()
    op = g['open'].to_numpy(dtype='float64')
    hi = g['high'].to_numpy(dtype='float64')
    lo = g['low'].to_numpy(dtype='float64')
    cl = g['close'].to_numpy(dtype='float64')
    inst = g['instrument_id'].to_numpy()

    def idx_window(start_min, end_min):
        return np.flatnonzero((m >= start_min) & (m < end_min))

    def session_ret(start_min, end_min):
        ix = idx_window(start_min, end_min)
        if len(ix) == 0:
            return np.nan
        return cl[ix[-1]] / op[ix[0]] - 1.0

    def open_at(minute):
        ix = np.flatnonzero(m == minute)
        return float(op[ix[0]]) if len(ix) else np.nan

    ov_ix = np.flatnonzero((m >= 18*60) | (m < 9*60+30))
    rth_ix = idx_window(9*60+30, 16*60)

    if len(ov_ix):
        ov_open = float(op[ov_ix[0]])
        ov_close = float(cl[ov_ix[-1]])
        ov_hi = float(np.max(hi[ov_ix]))
        ov_lo = float(np.min(lo[ov_ix]))
        ov_ret = ov_close/ov_open - 1.0
        ov_range = (ov_hi-ov_lo)/ov_open if ov_open else np.nan
        ov_closepos = (ov_close-ov_lo)/(ov_hi-ov_lo) if ov_hi > ov_lo else 0.5
        ov_r2 = lin_r2(cl[ov_ix])
    else:
        ov_open=ov_close=ov_hi=ov_lo=ov_ret=ov_range=ov_closepos=ov_r2=np.nan

    if len(rth_ix):
        rth_open = float(op[rth_ix[0]])
        rth_close = float(cl[rth_ix[-1]])
        rth_hi = float(np.max(hi[rth_ix]))
        rth_lo = float(np.min(lo[rth_ix]))
        rth_ret = rth_close/rth_open - 1.0
        rth_range = (rth_hi-rth_lo)/rth_open if rth_open else np.nan
        rth_closepos = (rth_close-rth_lo)/(rth_hi-rth_lo) if rth_hi > rth_lo else 0.5
    else:
        rth_open=rth_close=rth_hi=rth_lo=rth_ret=rth_range=rth_closepos=np.nan

    cur_ix = np.concatenate([ov_ix, rth_ix]) if len(ov_ix) or len(rth_ix) else np.array([],dtype=int)
    current_inst_n = len(pd.unique(inst[cur_ix])) if len(cur_ix) else 0

    p0930 = open_at(9*60+30)
    p0945 = open_at(9*60+45)
    p1000 = open_at(10*60)
    p1030 = open_at(10*60+30)

    # 09:30->09:45 known exactly at the 09:45 open, avoiding lookahead.
    ret15 = p0945/p0930 - 1.0 if np.isfinite(p0930) and np.isfinite(p0945) else np.nan

    return {
        'trade_date': pd.Timestamp(td),
        'ov_ret': ov_ret,
        'ov_range': ov_range,
        'ov_closepos': ov_closepos,
        'ov_r2': ov_r2,
        # Overnight sub-sessions (ET)
        'evening': session_ret(18*60, 24*60),   # 18:00-24:00
        'asia':    session_ret(0, 3*60),        # 00:00-03:00
        'europe':  session_ret(3*60, 6*60),     # 03:00-06:00
        'pre':     session_ret(6*60, 9*60+30),  # 06:00-09:30
        'late60':  session_ret(8*60+30, 9*60+30),
        'late30':  session_ret(9*60, 9*60+30),
        'rth_ret': rth_ret,
        'rth_range': rth_range,
        'rth_closepos': rth_closepos,
        'ret15': ret15,
        'ov_n': int(len(ov_ix)),
        'rth_n': int(len(rth_ix)),
        'current_inst_n': int(current_inst_n),
        'p0930': p0930,
        'p0945': p0945,
        'p1000': p1000,
        'p1030': p1030,
    }

print('\n[2/8] 从 1分钟K线生成逐日特征...')
rows = []
for i, (td, g) in enumerate(df.groupby('_trade_date', sort=True), 1):
    rows.append(one_day_features(td, g))
    if i % 500 == 0:
        print(f'  已处理 {i:,} 个交易日...')

feat = pd.DataFrame(rows).sort_values('trade_date').reset_index(drop=True)

# Previous RTH features must be shifted BEFORE filtering valid days.
for c in ['rth_ret','rth_range','rth_closepos']:
    feat['prev_'+c] = feat[c].shift(1)

# This reproduces the 3,636-day research filter.
feat['valid'] = (
    (feat['ov_n'] >= 700) &
    (feat['rth_n'] >= 388) &
    (feat['current_inst_n'] == 1)
)

valid = feat[feat['valid']].copy().reset_index(drop=True)
print(f'生成 {len(feat):,} 个交易日; 有效日 = {len(valid):,}')
print('目标有效日（此前研究）= 3,636')

# Save feature table early.
feat.to_csv(os.path.join(OUT_DIR, 'YM_daily_features_V1.csv'), index=False)

# Drop raw 5m-minute dataframe now to free Colab RAM.
del df

# ---------- 4) RULES ----------
def rule_flags(r):
    flags = {}
    flags['A']  = (r.late30 <= -0.0004) and (r.ov_closepos >= 0.70)
    flags['B']  = (r.late30 >= +0.0004) and (r.ov_r2 <= 0.09)
    flags['C']  = (-999 < r.late30) and (0.0003 <= r.late30 <= 0.0010) and (r.late60 <= -0.0010)
    flags['D']  = (-0.0010 <= r.late30 <= -0.0003) and (r.prev_rth_ret <= -0.0030)
    flags['E']  = (r.late30 >= -0.0004) and (r.ret15 >= +0.0020) and (r.prev_rth_ret >= -0.0025)
    flags['F']  = (r.late30 <= +0.0002) and (r.ret15 >= +0.0005) and (r.ov_closepos >= 0.80)
    flags['G']  = (-0.0020 <= r.late30 <= -0.0010) and (+0.0015 <= r.ret15 <= +0.0030)
    flags['I']  = (r.ov_range <= 0.0045) and (r.prev_rth_closepos <= 0.276)
    flags['J']  = (r.asia >= +0.0017) and (r.prev_rth_closepos >= 0.70)
    flags['K']  = (r.prev_rth_range <= 0.0082) and (r.ret15 <= -0.0023)
    flags['M']  = (r.prev_rth_ret <= -0.0030) and (r.prev_rth_closepos >= 0.276)
    flags['N5'] = (r.ov_ret <= +0.0008) and (r.europe >= +0.0013)
    return {k: bool(v) if pd.notna(v) else False for k,v in flags.items()}

print('\n[3/8] 计算 12 个策略信号并做一致性检查...')
flag_rows = []
for r in valid.itertuples(index=False):
    f = rule_flags(r)
    f['trade_date'] = r.trade_date
    flag_rows.append(f)
flags_df = pd.DataFrame(flag_rows)

actual_counts = {k:int(flags_df[k].sum()) for k in RULE_META}
check = pd.DataFrame({
    'rule': list(RULE_META),
    'expected': [EXPECTED_COUNTS[k] for k in RULE_META],
    'actual': [actual_counts[k] for k in RULE_META],
})
check['difference'] = check['actual'] - check['expected']
print(check.to_string(index=False))
check.to_csv(os.path.join(OUT_DIR, 'sanity_rule_counts.csv'), index=False)

if len(valid) != 3636 or (check['difference'].abs() > 3).any():
    print('\n⚠️ 警告：与此前研究计数存在明显差异。')
    print('最常见原因是时间列/时区/09:45价格定义不同。回测仍会继续，但先检查 sanity_rule_counts.csv。')
else:
    print('\n✅ 规则计数与此前研究基本一致。')

# Merge flags onto features
valid = valid.merge(flags_df, on='trade_date', how='left', suffixes=('','_flag'))

# ---------- 5) RAW CANDIDATE TRADES ----------
def gross_trade_values(side, entry_px, exit_px, contracts=1,
                       slip=SLIPPAGE_POINTS, commission=COMMISSION_PER_SIDE):
    sign = 1 if side == 'LONG' else -1
    gross_pct = sign * (exit_px/entry_px - 1.0)
    gross_points = sign * (exit_px-entry_px)
    # Adverse slippage on BOTH entry and exit.
    net_points = gross_points - 2.0*slip
    net_pnl = net_points * POINT_VALUE * contracts - 2.0*commission*contracts
    return gross_pct, gross_points, net_points, net_pnl

def get_px(r, hhmm):
    return {
        '09:30': r.p0930,
        '09:45': r.p0945,
        '10:00': r.p1000,
        '10:30': r.p1030,
    }[hhmm]

candidates = []
conflict_days = []
for r in valid.itertuples(index=False):
    day_rules = [k for k in RULE_META if getattr(r,k)]
    if day_rules:
        long_rules = [k for k in day_rules if RULE_META[k]['side']=='LONG']
        short_rules = [k for k in day_rules if RULE_META[k]['side']=='SHORT']
        if long_rules and short_rules:
            conflict_days.append({
                'trade_date':r.trade_date,
                'long_rules':','.join(long_rules),
                'short_rules':','.join(short_rules),
                'long_weight':sum(WEIGHTS[x] for x in long_rules),
                'short_weight':sum(WEIGHTS[x] for x in short_rules),
            })

    for rule in day_rules:
        meta = RULE_META[rule]
        ep = get_px(r, meta['entry'])
        xp = get_px(r, meta['exit'])
        if not (np.isfinite(ep) and np.isfinite(xp)):
            continue
        gpct,gpts,npts,npnl = gross_trade_values(meta['side'],ep,xp,1)
        candidates.append({
            'trade_date':r.trade_date,
            'rule':rule,
            'weight':WEIGHTS[rule],
            'side':meta['side'],
            'entry_time':meta['entry'],
            'exit_time':meta['exit'],
            'entry_price':ep,
            'exit_price':xp,
            'gross_pct':gpct,
            'gross_points':gpts,
            'net_points_1ct':npts,
            'net_pnl_1ct':npnl,
        })

cand = pd.DataFrame(candidates)
conflict_df = pd.DataFrame(conflict_days)
cand.to_csv(os.path.join(OUT_DIR,'raw_strategy_signals.csv'), index=False)
conflict_df.to_csv(os.path.join(OUT_DIR,'raw_conflict_days.csv'), index=False)

print(f'原始策略信号: {len(cand):,}')
print(f'多空同时触发的交易日: {len(conflict_df):,}')

# Strategy metrics: gross market move (to compare with prior research) + net $ after configured costs.
def pf_from_values(x):
    x = pd.Series(x).dropna()
    gp = x[x>0].sum()
    gl = -x[x<0].sum()
    return gp/gl if gl > 0 else np.inf

def streak_losses(pnls):
    mx=cur=0
    for x in pnls:
        if x < 0:
            cur += 1; mx=max(mx,cur)
        else:
            cur=0
    return mx

metric_rows=[]
for rule,g in cand.groupby('rule'):
    metric_rows.append({
        'rule':rule,
        'weight':WEIGHTS[rule],
        'N':len(g),
        'gross_win_rate':(g.gross_pct>0).mean(),
        'gross_avg_pct':g.gross_pct.mean(),
        'gross_PF':pf_from_values(g.gross_pct),
        'net_win_rate_after_costs':(g.net_pnl_1ct>0).mean(),
        'net_avg_dollars_1ct':g.net_pnl_1ct.mean(),
        'net_PF_after_costs':pf_from_values(g.net_pnl_1ct),
        'total_net_dollars_1ct':g.net_pnl_1ct.sum(),
    })
strategy_metrics = pd.DataFrame(metric_rows).sort_values('weight',ascending=False)
strategy_metrics.to_csv(os.path.join(OUT_DIR,'strategy_metrics_after_costs.csv'),index=False)
print('\n单策略结果（当前手续费/滑点）：')
print(strategy_metrics.to_string(index=False, formatters={
    'gross_win_rate':'{:.2%}'.format,
    'gross_avg_pct':'{:.4%}'.format,
    'gross_PF':'{:.2f}'.format,
    'net_win_rate_after_costs':'{:.2%}'.format,
    'net_avg_dollars_1ct':'${:.2f}'.format,
    'net_PF_after_costs':'{:.2f}'.format,
    'total_net_dollars_1ct':'${:.2f}'.format,
}))

# ---------- 6) CONFLICT RESOLVER ----------
def resolve_rules(rule_names, resonance=False):
    s = set(rule_names)
    if not s:
        return None

    # Remove both legs of explicit no-trade pairs.
    for pair in NO_TRADE_PAIRS:
        if pair.issubset(s):
            s -= set(pair)

    # Drop weaker leg of explicit winner pairs.
    changed=True
    while changed:
        changed=False
        for pair,winner in WINNER_PAIRS.items():
            if pair.issubset(s):
                loser = next(x for x in pair if x != winner)
                s.discard(loser)
                changed=True

    if not s:
        return None

    longs = sorted([x for x in s if RULE_META[x]['side']=='LONG'])
    shorts = sorted([x for x in s if RULE_META[x]['side']=='SHORT'])
    lw = sum(WEIGHTS[x] for x in longs)
    sw = sum(WEIGHTS[x] for x in shorts)
    net = lw - sw

    if longs and shorts and abs(net) < MIN_NET_SCORE:
        return None

    if net > 0 or (longs and not shorts):
        side='LONG'; chosen=longs; chosen_score=lw; opp_score=sw
    elif net < 0 or (shorts and not longs):
        side='SHORT'; chosen=shorts; chosen_score=sw; opp_score=lw
    else:
        return None

    if resonance and not (len(chosen) >= 2 or chosen_score >= RESONANCE_MIN_SCORE):
        return None

    return {
        'side':side,
        'rules':chosen,
        'all_remaining_rules':sorted(s),
        'chosen_score':chosen_score,
        'opp_score':opp_score,
        'net_score':abs(chosen_score-opp_score),
    }

def margin_budget_pct_for_score(score):
    """Return the fraction of account equity allowed as margin for this entry."""
    if not USE_SCORE_TO_SCALE_MARGIN:
        return MARGIN_BUDGET_PCT
    # Optional score scaling: score 20+ gets the full 30%; score 10 gets 15%, etc.
    scale = min(max(float(score) / float(FULL_MARGIN_SCORE), 0.0), 1.0)
    return MARGIN_BUDGET_PCT * scale


def contracts_for_margin(equity, entry_px, score):
    """
    Dynamic integer contract sizing.

    notional_per_contract = entry price * $/point
    margin_per_contract   = notional * 9%
    margin_budget         = current equity * allowed margin percentage
    contracts             = floor(margin_budget / margin_per_contract)

    Therefore, if account equity doubles (with price roughly unchanged),
    the allowed contract count roughly doubles as well.
    """
    if not (np.isfinite(equity) and np.isfinite(entry_px)) or equity <= 0 or entry_px <= 0:
        return 0, np.nan, 0.0, 0.0

    notional_per_contract = float(entry_px) * POINT_VALUE
    margin_per_contract = notional_per_contract * MARGIN_RATE
    budget_pct = margin_budget_pct_for_score(score)
    margin_budget = float(equity) * budget_pct

    if margin_per_contract <= 0:
        return 0, margin_per_contract, margin_budget, budget_pct

    contracts = int(math.floor(margin_budget / margin_per_contract))
    if MAX_CONTRACTS is not None:
        contracts = min(contracts, int(MAX_CONTRACTS))

    return max(contracts, 0), margin_per_contract, margin_budget, budget_pct

# ---------- 7) PORTFOLIO SIMULATION ----------
def make_trade(td, side, entry_time, exit_time, entry_px, exit_px,
               contracts, rules, score, reason, mode,
               equity_before=np.nan, margin_per_contract=np.nan,
               margin_budget=np.nan, margin_budget_pct=np.nan):
    gpct,gpts,npts,npnl = gross_trade_values(side,entry_px,exit_px,contracts)
    margin_used = margin_per_contract * contracts if np.isfinite(margin_per_contract) else np.nan
    margin_used_pct = (margin_used / equity_before) if (np.isfinite(margin_used) and np.isfinite(equity_before) and equity_before > 0) else np.nan
    return {
        'trade_date':pd.Timestamp(td),
        'mode':mode,
        'side':side,
        'contracts':int(contracts),
        'rules':','.join(sorted(rules)),
        'score':float(score),
        'entry_time':entry_time,
        'exit_time':exit_time,
        'entry_price':float(entry_px),
        'exit_price':float(exit_px),
        'gross_pct':gpct,
        'gross_points_per_ct':gpts,
        'net_points_per_ct':npts,
        'net_pnl':npnl,
        'equity_before_entry':equity_before,
        'margin_per_contract':margin_per_contract,
        'margin_budget':margin_budget,
        'margin_budget_pct':margin_budget_pct,
        'margin_used':margin_used,
        'margin_used_pct':margin_used_pct,
        'reason':reason,
    }

def simulate_independent():
    # Every rule is its own 1-contract sleeve; overlap is allowed.
    if cand.empty: return pd.DataFrame()
    out = cand.copy()
    out['mode']='ALL_INDEPENDENT'
    out['contracts']=1
    out['rules']=out['rule']
    out['score']=out['weight']
    out['net_pnl']=out['net_pnl_1ct']
    out['reason']='independent_rule'
    return out[['trade_date','mode','side','contracts','rules','score','entry_time','exit_time',
                'entry_price','exit_price','gross_pct','gross_points','net_points_1ct','net_pnl','reason']].rename(
        columns={'gross_points':'gross_points_per_ct','net_points_1ct':'net_points_per_ct'})

def simulate_event(mode='ONE_POSITION'):
    margin_sized = mode == 'MARGIN_30PCT'
    resonance = mode == 'RESONANCE_ONLY'
    logs=[]
    skipped=[]
    equity = float(INITIAL_CAPITAL)

    def build_position(td, dec, entry_time, entry_px, planned_exit):
        nonlocal equity
        if margin_sized:
            ct, margin_per_ct, margin_budget, budget_pct = contracts_for_margin(
                equity, entry_px, dec['net_score']
            )
            if ct < 1:
                skipped.append({
                    'trade_date':pd.Timestamp(td),
                    'mode':mode,
                    'entry_time':entry_time,
                    'side':dec['side'],
                    'rules':','.join(sorted(dec['rules'])),
                    'score':dec['net_score'],
                    'equity':equity,
                    'entry_price':entry_px,
                    'margin_per_contract':margin_per_ct,
                    'margin_budget':margin_budget,
                    'margin_budget_pct':budget_pct,
                    'reason':'insufficient_30pct_margin_budget',
                })
                return None
        else:
            ct = 1
            margin_per_ct = np.nan
            margin_budget = np.nan
            budget_pct = np.nan

        return {
            'side':dec['side'],
            'contracts':ct,
            'rules':set(dec['rules']),
            'score':dec['net_score'],
            'entry_time':entry_time,
            'entry_px':entry_px,
            'planned_exit':planned_exit,
            'equity_before_entry':equity if margin_sized else np.nan,
            'margin_per_contract':margin_per_ct,
            'margin_budget':margin_budget,
            'margin_budget_pct':budget_pct,
        }

    def close_position(td, pos, exit_time, exit_px, reason):
        nonlocal equity
        tr = make_trade(
            td,pos['side'],pos['entry_time'],exit_time,
            pos['entry_px'],exit_px,pos['contracts'],pos['rules'],pos['score'],reason,mode,
            equity_before=pos.get('equity_before_entry',np.nan),
            margin_per_contract=pos.get('margin_per_contract',np.nan),
            margin_budget=pos.get('margin_budget',np.nan),
            margin_budget_pct=pos.get('margin_budget_pct',np.nan),
        )
        logs.append(tr)
        if margin_sized:
            equity += tr['net_pnl']
        return tr

    for r in valid.itertuples(index=False):
        td = r.trade_date
        triggered = [k for k in RULE_META if getattr(r,k)]
        r930 = [k for k in triggered if RULE_META[k]['entry']=='09:30']
        r945 = [k for k in triggered if RULE_META[k]['entry']=='09:45']

        pos = None

        # ----- 09:30 -----
        dec = resolve_rules(r930, resonance=resonance)
        if dec and np.isfinite(r.p0930):
            pos = build_position(td, dec, '09:30', r.p0930, '10:00')

        # ----- 09:45: new information arrives -----
        new_dec = resolve_rules(r945, resonance=resonance)

        if pos is None:
            if new_dec and np.isfinite(r.p0945):
                pos = build_position(td, new_dec, '09:45', r.p0945, '10:30')
        else:
            if r945 and np.isfinite(r.p0945):
                # Resolve active rules + newly-triggered rules at 09:45.
                combined_names = set(pos['rules']) | set(r945)
                combo = resolve_rules(combined_names, resonance=False)

                if combo is None:
                    # Conflict says flatten.
                    close_position(td, pos, '09:45', r.p0945, 'conflict_flat')
                    pos = None
                elif combo['side'] != pos['side']:
                    # Close existing position and reverse using UPDATED realized equity.
                    close_position(td, pos, '09:45', r.p0945, 'reverse_out')
                    pos = build_position(td, combo, '09:45', r.p0945, '10:30')
                else:
                    # Same-side confirmation: keep the original number of contracts.
                    # We deliberately do NOT pyramid at 09:45; only update rules/exit time.
                    pos['rules'] = set(combo['rules'])
                    pos['score'] = max(pos['score'], combo['net_score'])
                    if any(x in r945 for x in combo['rules']):
                        pos['planned_exit'] = '10:30'

        # ----- scheduled exit -----
        if pos is not None:
            if pos['planned_exit']=='10:00' and np.isfinite(r.p1000):
                close_position(td, pos, '10:00', r.p1000, 'scheduled_exit')
                pos=None
            elif pos['planned_exit']=='10:30' and np.isfinite(r.p1030):
                close_position(td, pos, '10:30', r.p1030, 'scheduled_exit')
                pos=None

    out = pd.DataFrame(logs)
    skip_df = pd.DataFrame(skipped)
    if margin_sized:
        skip_df.to_csv(os.path.join(OUT_DIR,'skipped_margin_signals.csv'),index=False)
        print(f'  MARGIN_30PCT skipped for insufficient margin budget: {len(skip_df):,}')
    return out

print('\n[4/8] 运行四种组合模式...')
mode_trades = {
    'ALL_INDEPENDENT': simulate_independent(),
    'ONE_POSITION': simulate_event('ONE_POSITION'),
    'MARGIN_30PCT': simulate_event('MARGIN_30PCT'),
    'RESONANCE_ONLY': simulate_event('RESONANCE_ONLY'),
}
for name,t in mode_trades.items():
    t.to_csv(os.path.join(OUT_DIR,f'trades_{name}.csv'),index=False)
    print(f'  {name:18s}: {len(t):,} trades')

# ---------- 8) METRICS / TRAIN-VALIDATION-TEST ----------
def portfolio_report(trades, mode_name):
    dates = pd.DatetimeIndex(valid['trade_date'].sort_values().unique())
    daily = pd.Series(0.0,index=dates,name='pnl')
    if trades is not None and len(trades):
        tmp=trades.copy()
        tmp['trade_date']=pd.to_datetime(tmp['trade_date'])
        p=tmp.groupby('trade_date')['net_pnl'].sum()
        daily.loc[daily.index.intersection(p.index)] = p.reindex(daily.index.intersection(p.index)).values
    eq = INITIAL_CAPITAL + daily.cumsum()
    prev_eq = eq.shift(1).fillna(INITIAL_CAPITAL)
    dret = daily / prev_eq.replace(0,np.nan)
    peak=eq.cummax()
    dd=eq/peak-1.0

    n = 0 if trades is None else len(trades)
    pnl_arr = np.array([]) if n==0 else trades['net_pnl'].to_numpy(dtype=float)
    gross_profit = pnl_arr[pnl_arr>0].sum() if n else 0.0
    gross_loss = -pnl_arr[pnl_arr<0].sum() if n else 0.0
    pf = gross_profit/gross_loss if gross_loss>0 else np.inf
    win = (pnl_arr>0).mean() if n else np.nan
    years = max((dates[-1]-dates[0]).days/365.25, 1e-9)
    cagr = (eq.iloc[-1]/INITIAL_CAPITAL)**(1/years)-1 if eq.iloc[-1]>0 else np.nan
    sharpe = np.sqrt(252)*dret.mean()/dret.std(ddof=1) if dret.std(ddof=1)>0 else np.nan
    downside=dret[dret<0]
    sortino=np.sqrt(252)*dret.mean()/downside.std(ddof=1) if len(downside)>1 and downside.std(ddof=1)>0 else np.nan

    report={
        'mode':mode_name,
        'trades':n,
        'trade_days': int((daily!=0).sum()),
        'trades_per_valid_day': n/len(daily) if len(daily) else np.nan,
        'win_rate':win,
        'avg_net_pnl_per_trade': pnl_arr.mean() if n else np.nan,
        'profit_factor':pf,
        'total_net_pnl': pnl_arr.sum() if n else 0.0,
        'ending_equity':eq.iloc[-1],
        'total_return_on_initial': eq.iloc[-1]/INITIAL_CAPITAL-1,
        'CAGR':cagr,
        'Sharpe_daily':sharpe,
        'Sortino_daily':sortino,
        'max_drawdown_pct':dd.min(),
        'max_consecutive_losses':streak_losses(pnl_arr),
        'avg_contracts': trades['contracts'].mean() if n and 'contracts' in trades.columns else np.nan,
        'max_contracts': trades['contracts'].max() if n and 'contracts' in trades.columns else np.nan,
        'avg_margin_used_pct': trades['margin_used_pct'].dropna().mean() if n and 'margin_used_pct' in trades.columns and trades['margin_used_pct'].notna().any() else np.nan,
        'max_margin_used_pct': trades['margin_used_pct'].dropna().max() if n and 'margin_used_pct' in trades.columns and trades['margin_used_pct'].notna().any() else np.nan,
    }
    curve=pd.DataFrame({'trade_date':dates,'daily_pnl':daily.values,'equity':eq.values,'drawdown':dd.values})
    return report,curve

reports=[]; curves={}
for name,t in mode_trades.items():
    rep,curve=portfolio_report(t,name)
    reports.append(rep); curves[name]=curve
    curve.to_csv(os.path.join(OUT_DIR,f'equity_{name}.csv'),index=False)

summary=pd.DataFrame(reports)
summary.to_csv(os.path.join(OUT_DIR,'portfolio_summary.csv'),index=False)

print('\n[5/8] 组合回测汇总（已扣当前设置的手续费+滑点）：')
show=summary.copy()
for c in ['win_rate','total_return_on_initial','CAGR','max_drawdown_pct','avg_margin_used_pct','max_margin_used_pct']:
    show[c]=show[c].map(lambda x: f'{x:.2%}' if pd.notna(x) else 'NaN')
for c in ['avg_net_pnl_per_trade','total_net_pnl','ending_equity']:
    show[c]=show[c].map(lambda x: f'${x:,.2f}' if pd.notna(x) else 'NaN')
for c in ['profit_factor','Sharpe_daily','Sortino_daily','trades_per_valid_day','avg_contracts','max_contracts']:
    show[c]=show[c].map(lambda x: f'{x:.2f}' if pd.notna(x) else 'NaN')
print(show.to_string(index=False))

# Train / Validation / Test splits
splits = {
    'TRAIN_2011_2018': ('2011-01-01','2018-12-31'),
    'VALID_2019_2022': ('2019-01-01','2022-12-31'),
    'TEST_2023_2026':  ('2023-01-01','2026-12-31'),
}
split_rows=[]
for mode,t in mode_trades.items():
    if t is None or t.empty: continue
    tt=t.copy(); tt['trade_date']=pd.to_datetime(tt['trade_date'])
    for sn,(a,b) in splits.items():
        x=tt[(tt.trade_date>=a)&(tt.trade_date<=b)]
        vals=x.net_pnl.to_numpy(dtype=float)
        split_rows.append({
            'mode':mode,'split':sn,'trades':len(x),
            'win_rate':(vals>0).mean() if len(vals) else np.nan,
            'avg_net_pnl':vals.mean() if len(vals) else np.nan,
            'profit_factor':pf_from_values(vals),
            'total_net_pnl':vals.sum() if len(vals) else 0.0,
        })
split_metrics=pd.DataFrame(split_rows)
split_metrics.to_csv(os.path.join(OUT_DIR,'train_validation_test_metrics.csv'),index=False)
print('\n[6/8] Train / Validation / Test:')
print(split_metrics.to_string(index=False, formatters={
    'win_rate':'{:.2%}'.format,
    'avg_net_pnl':'${:.2f}'.format,
    'profit_factor':'{:.2f}'.format,
    'total_net_pnl':'${:,.2f}'.format,
}))

# Yearly contribution by strategy (independent, 1 contract) and by portfolio mode.
cand2=cand.copy(); cand2['year']=pd.to_datetime(cand2.trade_date).dt.year
strategy_yearly=(cand2.groupby(['year','rule'])['net_pnl_1ct'].sum().reset_index())
strategy_yearly.to_csv(os.path.join(OUT_DIR,'strategy_yearly_pnl_1ct.csv'),index=False)

portfolio_years=[]
for mode,t in mode_trades.items():
    if t is None or t.empty: continue
    x=t.copy(); x['year']=pd.to_datetime(x.trade_date).dt.year
    y=x.groupby('year').net_pnl.sum()
    for yr,pnl in y.items(): portfolio_years.append({'mode':mode,'year':yr,'net_pnl':pnl})
pd.DataFrame(portfolio_years).to_csv(os.path.join(OUT_DIR,'portfolio_yearly_pnl.csv'),index=False)

# Monthly P&L
portfolio_months=[]
for mode,t in mode_trades.items():
    if t is None or t.empty: continue
    x=t.copy(); x['month']=pd.to_datetime(x.trade_date).dt.to_period('M').astype(str)
    y=x.groupby('month').net_pnl.sum()
    for mo,pnl in y.items(): portfolio_months.append({'mode':mode,'month':mo,'net_pnl':pnl})
pd.DataFrame(portfolio_months).to_csv(os.path.join(OUT_DIR,'portfolio_monthly_pnl.csv'),index=False)

# Equity chart
plt.figure(figsize=(13,6))
for mode,curve in curves.items():
    plt.plot(pd.to_datetime(curve.trade_date),curve.equity,label=mode,linewidth=1.4)
plt.axhline(INITIAL_CAPITAL,linestyle='--',linewidth=1)
plt.title('YM Opening Strategy V2 - Equity Curves (9% margin, up to 30% equity budget)')
plt.xlabel('Date'); plt.ylabel('Equity ($)'); plt.legend(); plt.grid(alpha=.25)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR,'equity_curves.png'),dpi=160)
plt.show()

# ---------- 9) PACKAGE ----------
config_dump = {
    'INITIAL_CAPITAL':INITIAL_CAPITAL,
    'CONTRACT_NAME':CONTRACT_NAME,
    'POINT_VALUE':POINT_VALUE,
    'COMMISSION_PER_SIDE':COMMISSION_PER_SIDE,
    'SLIPPAGE_POINTS':SLIPPAGE_POINTS,
    'MARGIN_RATE':MARGIN_RATE,
    'MARGIN_BUDGET_PCT':MARGIN_BUDGET_PCT,
    'USE_SCORE_TO_SCALE_MARGIN':USE_SCORE_TO_SCALE_MARGIN,
    'FULL_MARGIN_SCORE':FULL_MARGIN_SCORE,
    'MAX_CONTRACTS':MAX_CONTRACTS,
    'MIN_NET_SCORE':MIN_NET_SCORE,
    'RESONANCE_MIN_SCORE':RESONANCE_MIN_SCORE,
    'WEIGHTS':WEIGHTS,
    'RULE_META':RULE_META,
}
with open(os.path.join(OUT_DIR,'config.json'),'w') as f:
    json.dump(config_dump,f,indent=2)

zip_path='/content/YM_V2_margin30_backtest_results.zip'
if os.path.exists(zip_path): os.remove(zip_path)
shutil.make_archive('/content/YM_V2_margin30_backtest_results','zip',OUT_DIR)

print('\n[7/8] 输出文件已生成:')
print(zip_path)
print('\n主要文件:')
for f in sorted(os.listdir(OUT_DIR)):
    print(' ',f)

print('\n[8/8] 完成。')
print('主模式 MARGIN_30PCT：每次新开仓按当前账户权益动态计算手数；9%理论保证金，最多使用30%账户权益。')
print('如果当前30%预算不足1手YM，该次信号会跳过并记录在 skipped_margin_signals.csv。')
print('建议随后把 SLIPPAGE_POINTS 分别改成 0 / 1 / 2，三次重跑做压力测试。')

if AUTO_DOWNLOAD_ZIP:
    try:
        from google.colab import files
        files.download(zip_path)
    except Exception as e:
        print('自动下载未触发，可手动运行:')
        print("from google.colab import files; files.download('/content/YM_V2_margin30_backtest_results.zip')")