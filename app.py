import os
import time
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Any, Optional

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

# =========================
# Config
# =========================
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "").strip().strip('"').strip("'")
if not RIOT_API_KEY:
    st.error("RIOT_API_KEY não encontrada no .env (RIOT_API_KEY=RGAPI-...)")
    st.stop()

REGIONAL_ROUTING = "americas"   # account-v1 / match-v5
QUEUE_SOLOQ = 420               # Ranked Solo
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

DEFAULT_PLAYERS = [
    "Forlin#br1",
    "Aegis#ijji",
    "Aithusa#lol",
    "Takagi#Gru",
    "Horse Negs#Sabão",
]

SESSION = requests.Session()
SESSION.headers.update({"X-Riot-Token": RIOT_API_KEY})

# Data Dragon (imagens)
DDRAGON_VER = "15.16.1"  # se quiser, pode trocar depois
CHAMP_SQUARE = "https://ddragon.leagueoflegends.com/cdn/{ver}/img/champion/{champ}.png"


# =========================
# UI Styling (op.gg-lite dark + cards)
# =========================
st.set_page_config(page_title="SoloQ Tracker", page_icon="🎮", layout="wide")
st.markdown(
    """
<style>
:root { color-scheme: dark; }
.block-container { padding-top: 1.1rem; padding-bottom: 2rem; }
[data-testid="stSidebar"] { background: #0b0f14; border-right: 1px solid #151b22; }
[data-testid="stAppViewContainer"] {
  background: radial-gradient(1200px 700px at 30% 0%, #121826 0%, #0b0f14 45%, #070a0f 100%);
}
.small-muted { color: #9aa4b2; font-size: 0.92rem; }

.card {
  background: linear-gradient(180deg, rgba(17,24,39,.85), rgba(10,15,20,.85));
  border: 1px solid rgba(148,163,184,.12);
  border-radius: 16px;
  padding: 14px 14px 12px 14px;
  box-shadow: 0 10px 30px rgba(0,0,0,.22);
  margin-bottom: 16px;
}
.card-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px; }
.card-title { font-weight: 900; font-size: 1.05rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pill {
  padding: 4px 10px; border-radius: 999px;
  background: rgba(59,130,246,.12);
  border: 1px solid rgba(59,130,246,.22);
  color: #cde2ff; font-size: .82rem;
}

.kpis { display:flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }
.kpi { background: rgba(2,6,23,.35); border: 1px solid rgba(148,163,184,.10); border-radius: 12px; padding: 10px 12px; min-width: 140px; }
.kpi .label { color:#9aa4b2; font-size:.84rem; }
.kpi .value { font-size: 1.25rem; font-weight: 900; margin-top: 2px; }

.hr { height:1px; background: rgba(148,163,184,.12); margin: 12px 0; }
.section-title { margin-top: 6px; font-weight: 900; }

.champ-row {
  display:flex; align-items:center; gap:10px;
  padding: 8px 10px;
  border: 1px solid rgba(148,163,184,.10);
  background: rgba(2,6,23,.25);
  border-radius: 12px;
  margin-bottom: 8px;
}
.champ-row img { width: 34px; height: 34px; border-radius: 10px; }
.champ-meta { flex: 1; }
.champ-name { font-weight: 800; }
.champ-sub { color: #9aa4b2; font-size: .88rem; margin-top: 2px; }
.champ-right { text-align:right; min-width: 160px; }
.champ-right .big { font-weight: 900; }
.champ-right .sub { color:#9aa4b2; font-size: .86rem; }

.bad { color: #fca5a5; font-weight: 800; }
.good { color: #86efac; font-weight: 800; }
.mid { color: #93c5fd; font-weight: 800; }
</style>
""",
    unsafe_allow_html=True,
)


# =========================
# Helpers
# =========================
def fmt_date_br(d: date) -> str:
    return d.strftime("%d/%m/%Y")

def to_unix_start(d: date) -> int:
    dt_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=LOCAL_TZ)
    return int(dt_local.astimezone(timezone.utc).timestamp())

def to_unix_end(d: date) -> int:
    dt_local = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=LOCAL_TZ)
    return int(dt_local.astimezone(timezone.utc).timestamp())

def dt_from_ms_local(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)

def mmss(seconds: int) -> str:
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"

def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0

def champ_img(champ: str) -> str:
    # champName já vem no padrão DDragon (ex.: LeeSin, Ahri, Aatrox)
    return CHAMP_SQUARE.format(ver=DDRAGON_VER, champ=champ)

def riot_get(url: str) -> Any:
    last_err = None
    for attempt in range(6):
        r = SESSION.get(url, timeout=30)

        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            sleep_s = int(ra) if ra and ra.isdigit() else (2 + attempt * 2)
            time.sleep(sleep_s)
            continue

        if 500 <= r.status_code <= 599:
            time.sleep(1.0 + attempt * 0.6)
            continue

        if r.ok:
            return r.json()

        try:
            detail = r.json()
        except Exception:
            detail = r.text

        last_err = RuntimeError(f"Riot API error {r.status_code}: {detail}")
        raise last_err

    raise last_err or RuntimeError("Erro desconhecido na Riot API.")


# =========================
# Riot calls (cached)
# =========================
@st.cache_data(ttl=60 * 60, show_spinner=False)
def get_account_by_riot_id(riot_id: str) -> Dict[str, Any]:
    if "#" not in riot_id:
        raise ValueError(f"RiotID inválido: {riot_id}. Use Nome#TAG")
    game, tag = riot_id.split("#", 1)
    url = (
        f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
        f"{requests.utils.quote(game)}/{requests.utils.quote(tag)}"
    )
    return riot_get(url)

@st.cache_data(ttl=60 * 20, show_spinner=False)
def get_match_ids_by_puuid(
    puuid: str,
    start_time: int,
    end_time: int,
    max_ids: int = 600,
) -> List[str]:
    """
    IDs já filtrados por SoloQ (queue=420).
    """
    ids: List[str] = []
    start = 0
    page_size = 100

    while len(ids) < max_ids:
        count = min(page_size, max_ids - len(ids))
        url = (
            f"https://{REGIONAL_ROUTING}.api.riotgames.com/lol/match/v5/matches/by-puuid/"
            f"{requests.utils.quote(puuid)}/ids?"
            f"startTime={start_time}&endTime={end_time}&queue={QUEUE_SOLOQ}&start={start}&count={count}"
        )
        batch = riot_get(url)
        if not isinstance(batch, list) or not batch:
            break

        ids.extend(batch)
        if len(batch) < count:
            break
        start += count

    return ids

@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def get_match_detail(match_id: str) -> Dict[str, Any]:
    url = f"https://{REGIONAL_ROUTING}.api.riotgames.com/lol/match/v5/matches/{requests.utils.quote(match_id)}"
    return riot_get(url)


# =========================
# Build: per match rows with KDA/CS/duration
# =========================
def build_games(
    puuid: str,
    match_ids: List[str],
    max_workers: int = 8,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    def parse_one(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        info = m.get("info", {})
        if info.get("queueId") != QUEUE_SOLOQ:
            return None

        participant = None
        for p in info.get("participants", []):
            if p.get("puuid") == puuid:
                participant = p
                break
        if not participant:
            return None

        win = bool(participant.get("win", False))
        champ = participant.get("championName") or "Unknown"
        pos = participant.get("teamPosition") or "-"

        kills = int(participant.get("kills", 0))
        deaths = int(participant.get("deaths", 0))
        assists = int(participant.get("assists", 0))

        total_minions = int(participant.get("totalMinionsKilled", 0)) + int(participant.get("neutralMinionsKilled", 0))

        duration_sec = int(info.get("gameDuration", 0))
        duration_min = duration_sec / 60.0

        cs_min = safe_div(total_minions, duration_min)
        kda = safe_div((kills + assists), max(1, deaths))

        ms = int(info.get("gameCreation", 0))
        dt_local = dt_from_ms_local(ms)

        return {
            "dt": dt_local,
            "day_iso": dt_local.date().isoformat(),
            "Data": dt_local.strftime("%d/%m/%Y"),
            "Hora": dt_local.strftime("%H:%M"),
            "Resultado": "W" if win else "L",
            "win": 1 if win else 0,
            "loss": 0 if win else 1,
            "Campeão": champ,
            "Posição": pos,
            "Kills": kills,
            "Deaths": deaths,
            "Assists": assists,
            "KDA": round(kda, 2),
            "CS": total_minions,
            "CS/min": round(cs_min, 2),
            "Duração": mmss(duration_sec),
            "duration_sec": duration_sec,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(get_match_detail, mid) for mid in match_ids]
        for fut in as_completed(futures):
            m = fut.result()
            row = parse_one(m)
            if row:
                rows.append(row)

    if not rows:
        return pd.DataFrame()

    rows.sort(key=lambda x: x["dt"])  # cronológico

    # numerar jogo do dia
    seq_by_day: Dict[str, int] = {}
    for r in rows:
        d = r["day_iso"]
        seq_by_day[d] = seq_by_day.get(d, 0) + 1
        r["Jogo do dia"] = seq_by_day[d]

    return pd.DataFrame(rows)


def champion_agg(df_games: pd.DataFrame) -> pd.DataFrame:
    """
    Por campeão:
      - Jogos
      - W / L / WR%
      - KDA médio
      - CS/min médio
    """
    if df_games.empty:
        return pd.DataFrame(columns=["Campeão", "Jogos", "W", "L", "WR%", "KDA", "CS/min"])

    agg = (
        df_games.groupby("Campeão", as_index=False)
        .agg(
            Jogos=("Campeão", "count"),
            W=("win", "sum"),
            L=("loss", "sum"),
            KDA=("KDA", "mean"),
            CSmin=("CS/min", "mean"),
        )
    )
    agg["WR%"] = (agg["W"] / agg["Jogos"] * 100.0).round(1)
    agg["KDA"] = agg["KDA"].round(2)
    agg["CS/min"] = agg["CSmin"].round(2)
    agg = agg.drop(columns=["CSmin"])
    agg = agg.sort_values(["Jogos", "WR%"], ascending=[False, False]).reset_index(drop=True)
    return agg


def games_per_day(df_games: pd.DataFrame) -> pd.DataFrame:
    if df_games.empty:
        return pd.DataFrame(columns=["Dia", "Jogos"])
    out = df_games.groupby("day_iso", as_index=False).size()
    out.columns = ["DiaISO", "Jogos"]
    out["Dia"] = pd.to_datetime(out["DiaISO"]).dt.strftime("%d/%m/%Y")
    return out[["Dia", "Jogos"]]


# =========================
# UI
# =========================
st.title("🎮 SoloQ Tracker (BR) — Cards + KDA/CS/Duração")
st.markdown(
    '<div class="small-muted">Modo <b>Consolidado</b>: só Top champs (imagem) + WR/KDA/CS/min. '
    'Modo <b>Detalhado</b>: lista de partidas com duração + KDA + CS/min.</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Configurações")

    players_text = st.text_area("Players (um por linha)", value="\n".join(DEFAULT_PLAYERS), height=170)
    players = [p.strip() for p in players_text.splitlines() if p.strip()]

    today = date.today()
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("De", value=today - timedelta(days=1))
    with c2:
        end_d = st.date_input("Até", value=today)

    # Aceleração: últimos X jogos (cap)
    last_x = st.selectbox("Somente últimos X jogos (acelera)", options=[ 5, 10, 15 ,30, 50, 100, 200, 400, 600], index=2)

    max_workers = st.slider("Concorrência (detalhes)", 2, 16, 8, 1)

    mode = st.radio("Modo", ["Consolidado (Top champs)", "Detalhado (lista de partidas)"], index=0)

    min_games_for_wr = st.slider("Mínimo de jogos (por champ) no gráfico WR%", 1, 10, 3, 1)
    top_n_chart = st.slider("Top N campeões no gráfico", 5, 20, 10, 1)

    show_daily_progress = st.toggle("Mostrar progresso por dia (expander)", value=False)
    show_table_all = st.toggle("Mostrar tabela completa (debug)", value=False)

    run = st.button("Buscar", type="primary", use_container_width=True)

if not players:
    st.warning("Adicione ao menos 1 player.")
    st.stop()

if start_d > end_d:
    st.error("A data 'De' não pode ser maior que 'Até'.")
    st.stop()

period_label = f"{fmt_date_br(start_d)} até {fmt_date_br(end_d)}"
st.subheader(f"Período: {period_label}  •  (limitado aos últimos {last_x} jogos)")

if not run:
    st.stop()

# Fetch all players
progress = st.progress(0)
status = st.empty()

results: Dict[str, Dict[str, Any]] = {}
errors: List[Dict[str, str]] = []

for i, riot_id in enumerate(players, start=1):
    status.write(f"Buscando **{riot_id}** ({i}/{len(players)})...")
    try:
        acc = get_account_by_riot_id(riot_id)
        puuid = acc.get("puuid")
        if not puuid:
            raise RuntimeError(f"Sem puuid na resposta account: {acc}")

        # IDs SoloQ no range
        match_ids = get_match_ids_by_puuid(
            puuid=puuid,
            start_time=to_unix_start(start_d),
            end_time=to_unix_end(end_d),
            max_ids=last_x,  # 🔥 aqui está o "somente últimos X"
        )

        df_games = build_games(puuid, match_ids, max_workers=max_workers)
        df_champ = champion_agg(df_games)

        total = int(len(df_games))
        wins = int(df_games["Resultado"].eq("W").sum()) if total else 0
        losses = int(df_games["Resultado"].eq("L").sum()) if total else 0
        wr = (wins / total * 100.0) if total else 0.0

        results[riot_id] = {
            "puuid": puuid,
            "total": total,
            "wins": wins,
            "losses": losses,
            "wr": wr,
            "df_games": df_games,
            "df_champ": df_champ,
        }

    except Exception as e:
        errors.append({"Player": riot_id, "Erro": str(e)})

    progress.progress(i / len(players))

status.empty()
progress.empty()

if errors:
    st.error("Erros em alguns players:")
    st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)

if not results:
    st.stop()

# Dashboard summary
total_all = sum(v["total"] for v in results.values())
wins_all = sum(v["wins"] for v in results.values())
loss_all = sum(v["losses"] for v in results.values())
wr_all = (wins_all / total_all * 100.0) if total_all else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total geral (SoloQ)", total_all)
c2.metric("Vitórias (geral)", wins_all)
c3.metric("Derrotas (geral)", loss_all)
c4.metric("Winrate (geral)", f"{wr_all:.1f}%")

st.divider()

# Render cards in grid (2 columns)
cols = st.columns(2)
col_idx = 0

for riot_id, r in results.items():
    container = cols[col_idx % 2]
    col_idx += 1

    with container:
        st.markdown(
            f"""
<div class="card">
  <div class="card-head">
    <div class="card-title">{riot_id}</div>
    <div class="pill">SoloQ 420</div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="label">Total</div><div class="value">{r['total']}</div></div>
    <div class="kpi"><div class="label">Vitórias</div><div class="value">{r['wins']}</div></div>
    <div class="kpi"><div class="label">Derrotas</div><div class="value">{r['losses']}</div></div>
    <div class="kpi"><div class="label">WR%</div><div class="value">{r['wr']:.1f}%</div></div>
  </div>

  <div class="hr"></div>
</div>
""",
            unsafe_allow_html=True,
        )

        df_games: pd.DataFrame = r["df_games"]
        df_champ: pd.DataFrame = r["df_champ"]

        if r["total"] == 0:
            st.info("Nenhuma SoloQ encontrada no período.")
            continue

        # =========================
        # Consolidado: "só a foto do champ + wr kda cs/min"
        # =========================
        if mode == "Consolidado (Top champs)":
            st.markdown('<div class="section-title">🏆 Top campeões (consolidado)</div>', unsafe_allow_html=True)

            top = df_champ.head(10).copy()
            for _, row in top.iterrows():
                champ = row["Campeão"]
                jogos = int(row["Jogos"])
                w = int(row["W"])
                l = int(row["L"])
                wrp = float(row["WR%"])
                kda = float(row["KDA"])
                csmin = float(row["CS/min"])

                st.markdown(
                    f"""
<div class="champ-row">
  <img src="{champ_img(champ)}" />
  <div class="champ-meta">
    <div class="champ-name">{champ}</div>
    <div class="champ-sub">{jogos} jogos • {w}W {l}L</div>
  </div>
  <div class="champ-right">
    <div class="big">{wrp:.1f}% WR</div>
    <div class="sub">KDA {kda:.2f} • CS/min {csmin:.2f}</div>
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )

            st.markdown('<div class="section-title">📊 WR% por campeão (com mínimo de N jogos)</div>', unsafe_allow_html=True)
            filtered = df_champ[df_champ["Jogos"] >= min_games_for_wr].copy()
            filtered = filtered.sort_values(["Jogos", "WR%"], ascending=[False, False]).head(top_n_chart)
            if filtered.empty:
                st.info("Nenhum campeão atende o mínimo de jogos para o gráfico.")
            else:
                st.bar_chart(filtered.set_index("Campeão")["WR%"])

        # =========================
        # Detalhado: lista de partidas
        # =========================
        else:
            st.markdown('<div class="section-title">🧾 Lista de partidas (duração + KDA + CS/min)</div>', unsafe_allow_html=True)
            df_view = df_games.sort_values("dt", ascending=False).copy()
            df_view["K/D/A"] = df_view["Kills"].astype(str) + "/" + df_view["Deaths"].astype(str) + "/" + df_view["Assists"].astype(str)

            # tabela "opgg-like"
            show_cols = ["Data", "Hora", "Resultado", "Campeão", "Posição", "Duração", "K/D/A", "KDA", "CS", "CS/min"]
            st.dataframe(df_view[show_cols], use_container_width=True, hide_index=True)

            st.markdown('<div class="section-title">🏆 Performance por campeão</div>', unsafe_allow_html=True)
            st.dataframe(df_champ, use_container_width=True, hide_index=True)

            st.markdown('<div class="section-title">📊 WR% por campeão (com mínimo de N jogos)</div>', unsafe_allow_html=True)
            filtered = df_champ[df_champ["Jogos"] >= min_games_for_wr].copy()
            filtered = filtered.sort_values(["Jogos", "WR%"], ascending=[False, False]).head(top_n_chart)
            if filtered.empty:
                st.info("Nenhum campeão atende o mínimo de jogos para o gráfico.")
            else:
                st.bar_chart(filtered.set_index("Campeão")["WR%"])

        # Jogos por dia (sempre útil)
        st.markdown('<div class="section-title">📅 Jogos por dia</div>', unsafe_allow_html=True)
        df_day = df_games.groupby("day_iso", as_index=False).size()
        df_day.columns = ["DiaISO", "Jogos"]
        df_day["Dia"] = pd.to_datetime(df_day["DiaISO"]).dt.strftime("%d/%m/%Y")
        st.bar_chart(df_day.set_index("Dia")["Jogos"])

        # Progresso por dia opcional
        if show_daily_progress:
            with st.expander("📅 Progresso por dia (jogo a jogo)", expanded=False):
                df_sorted = df_games.sort_values("dt")
                for day_iso in sorted(df_sorted["day_iso"].unique()):
                    day_df = df_sorted[df_sorted["day_iso"] == day_iso].sort_values("dt")
                    day_w = int(day_df["Resultado"].eq("W").sum())
                    day_l = int(day_df["Resultado"].eq("L").sum())
                    day_total = day_w + day_l
                    day_label = datetime.fromisoformat(day_iso).strftime("%d/%m/%Y")

                    st.markdown(f"**{day_label} — {day_total} jogos ({day_w}W {day_l}L)**")
                    for _, row in day_df.iterrows():
                        res_icon = "🟢" if row["Resultado"] == "W" else "🔴"
                        st.write(
                            f"Jogo {int(row['Jogo do dia'])} — {row['Hora']} — {res_icon} {row['Resultado']} — "
                            f"**{row['Campeão']}** — {row['Posição']} — "
                            f"{row['K/D/A'] if 'K/D/A' in row else ''} • KDA {row['KDA']:.2f} • CS/min {row['CS/min']:.2f} • {row['Duração']}"
                        )
                    st.markdown("---")

        if show_table_all:
            with st.expander("📄 Debug — dataframe completo", expanded=False):
                st.dataframe(df_games.sort_values("dt", ascending=False), use_container_width=True, hide_index=True)

st.caption("Obs.: Para KDA/CS/duração é necessário baixar detalhes das partidas. O filtro 'últimos X jogos' reduz muito o tempo.")