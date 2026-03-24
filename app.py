#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import math
import time
import requests
import streamlit as st
from bs4 import BeautifulSoup
from pytrends.request import TrendReq


def get_horses_from_netkeiba(race_id: str) -> list:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://race.netkeiba.com/",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }

    try:
        shutuba_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        resp = requests.get(shutuba_url, headers=headers, timeout=15)
        resp.encoding = "euc-jp"
    except requests.RequestException as e:
        st.error(f"netkeibaへの接続に失敗しました: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    name_by_num = {}
    for i, row in enumerate(soup.select("tr.HorseList"), start=1):
        name_tag = row.select_one("span.HorseName")
        if name_tag:
            name_by_num[str(i)] = name_tag.get_text(strip=True)

    if not name_by_num:
        st.error("馬名が取得できませんでした。race_idを確認してください。")
        return []

    try:
        odds_url = f"https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=init"
        resp2 = requests.get(odds_url, headers=headers, timeout=10)
        odds_data = resp2.json()
    except Exception:
        odds_data = {}

    odds_by_num = {}
    try:
        raw_odds = odds_data["data"]["odds"]["1"]
        for horse_num, vals in raw_odds.items():
            try:
                odds_by_num[horse_num] = float(vals[0])
            except (ValueError, IndexError):
                odds_by_num[horse_num] = None
    except (KeyError, TypeError):
        pass

    horses = []
    for num, name in name_by_num.items():
        odds = odds_by_num.get(num)
        horses.append({"name": name, "odds": odds})

    return horses


def get_trend_scores(horse_names: list, timeframe: str) -> dict:
    pytrends = TrendReq(hl="ja-JP", tz=540)
    scores = {name: 0.0 for name in horse_names}

    progress = st.progress(0, text="Googleトレンド取得中...")
    total = len(horse_names)

    for i in range(0, total, 5):
        batch = horse_names[i: i + 5]
        try:
            pytrends.build_payload(batch, geo="JP", timeframe=timeframe)
            data = pytrends.interest_over_time()
            if not data.empty:
                for horse in batch:
                    if horse in data.columns:
                        scores[horse] = float(data[horse].mean())
            time.sleep(2)
        except Exception:
            time.sleep(5)
        progress.progress(min(i + 5, total) / total, text=f"Googleトレンド取得中... ({min(i+5, total)}/{total}頭)")

    progress.empty()
    return scores


def rank_by_discrepancy(horses: list, trends: dict) -> list:
    results = []
    for horse in horses:
        name = horse["name"]
        odds = horse["odds"]
        trend = trends.get(name, 0.0)

        if odds is not None and odds > 0 and trend > 0:
            gap_score = trend * math.log(odds + 1)
        else:
            gap_score = 0.0

        results.append({
            "name": name,
            "odds": odds if odds is not None else "-",
            "trend": round(trend, 1),
            "gap_score": round(gap_score, 2),
        })

    results.sort(key=lambda x: x["gap_score"], reverse=True)
    return results


# ─── UI ───────────────────────────────────────────
st.set_page_config(page_title="競馬オッズ分析", page_icon="🐎", layout="centered")
st.title("🐎 競馬オッズ vs Googleトレンド")
st.caption("netkeibaの単勝オッズとGoogleトレンドの注目度を比較し、穴馬候補をランキング化します。")

with st.expander("race_idの調べ方"):
    st.markdown("""
1. [netkeiba](https://race.netkeiba.com/) でレースページを開く
2. URLに含まれる `race_id=` の後の12桁の数字をコピー
例: `https://race.netkeiba.com/odds/index.html?race_id=`**`202606030111`**
    """)

race_id = st.text_input("race_id を入力", placeholder="例: 202606030111")

timeframe_label = st.selectbox("検索期間", ["過去1時間", "過去4時間", "過去1日（推奨）", "過去7日", "過去30日"])
timeframe_map = {
    "過去1時間": "now 1-H",
    "過去4時間": "now 4-H",
    "過去1日（推奨）": "now 1-d",
    "過去7日": "now 7-d",
    "過去30日": "today 1-m",
}
timeframe = timeframe_map[timeframe_label]

if st.button("分析スタート", type="primary", disabled=not race_id):
    with st.spinner("netkeibaから馬データを取得中..."):
        horses = get_horses_from_netkeiba(race_id)

    if horses:
        st.success(f"{len(horses)}頭のデータを取得しました。")
        horse_names = [h["name"] for h in horses]
        trends = get_trend_scores(horse_names, timeframe)
        results = rank_by_discrepancy(horses, trends)

        st.subheader("分析結果")
        st.caption("ずれスコアが高い = トレンド注目度が高いのにオッズも高い馬（穴馬候補）")

        st.dataframe(
            results,
            column_config={
                "name":      st.column_config.TextColumn("馬名"),
                "odds":      st.column_config.NumberColumn("単勝オッズ"),
                "trend":     st.column_config.ProgressColumn("トレンド", min_value=0, max_value=100),
                "gap_score": st.column_config.NumberColumn("ずれスコア", format="%.2f"),
            },
            hide_index=True,
            use_container_width=True,
        )
