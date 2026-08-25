import json
import os
from datetime import datetime
from statistics import mean
from typing import Any, Callable

import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Win Daniel - Últimas Rodadas - Sorte na Bet 3", layout="wide")

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

try:
    import plotly.graph_objects as go

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vr5_config.json")
DEFAULT_CONFIG = {"limite_baixa": 2.0, "alvo_alto": 10.0}


# ---------------------------------------------------------------------------
# Banco de dados — conexão e query mantidas exatamente como estavam
# (único ajuste: cast para float já na leitura, para evitar problemas de
# comparação entre Decimal e float nos cálculos analíticos abaixo)
# ---------------------------------------------------------------------------
def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL não configurada no .env")
    return psycopg2.connect(database_url)


def fetch_recent_rounds(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT round_id, multiplier, round_timestamp, source, created_at
                FROM public.game_rounds
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "round_id": row[0],
            "multiplier": float(row[1]) if row[1] is not None else 0.0,
            "round_timestamp": row[2],
            "source": row[3],
            "created_at": row[4],
            "imported": False,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Configuração de estratégia (Limite de baixa / Alvo alto) — persistida em
# um arquivo local simples, sem tocar na tabela public.game_rounds.
# ---------------------------------------------------------------------------
def load_config() -> dict[str, float]:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**DEFAULT_CONFIG, **data}
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict[str, float]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f)


# ---------------------------------------------------------------------------
# Helpers visuais / analíticos
# ---------------------------------------------------------------------------
def get_card_style(multiplier: float) -> tuple[str, str, str]:
    if multiplier >= 50:
        return "linear-gradient(135deg, #ff2f92 0%, #8b0058 100%)", "#ff8ac2", "#ffffff"
    if multiplier >= 10:
        return "linear-gradient(135deg, #7c3aed 0%, #4c1d95 100%)", "#c4b5fd", "#ffffff"
    return "linear-gradient(135deg, #0f4c81 0%, #0b1026 100%)", "#93c5fd", "#ffffff"


def classify_multiplier(multiplier: float, limite_baixa: float, alvo_alto: float) -> str:
    if multiplier >= 50:
        return "Ultra 50x+"
    if multiplier >= alvo_alto:
        return "Alta"
    if multiplier >= limite_baixa:
        return "Normal"
    return "Baixa"


def format_round_time(round_data: dict[str, Any]) -> str:
    value = round_data.get("round_timestamp") or round_data.get("created_at")
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    return str(value)


def current_streak(rounds_desc: list[dict[str, Any]], predicate: Callable[[float], bool]) -> int:
    """Conta quantas rodadas consecutivas, a partir da mais recente, satisfazem a condição."""
    count = 0
    for r in rounds_desc:
        if predicate(r["multiplier"]):
            count += 1
        else:
            break
    return count


def rounds_since_last(rounds_desc: list[dict[str, Any]], predicate: Callable[[float], bool]) -> int:
    """Quantas rodadas se passaram desde a última que satisfez a condição (0 = a mais recente já satisfaz)."""
    count = 0
    for r in rounds_desc:
        if predicate(r["multiplier"]):
            return count
        count += 1
    return count


def casas_indicadas(rounds_desc: list[dict[str, Any]], alvo_alto: float, max_casas: int = 3) -> list[str]:
    """Usa os dígitos do último multiplicador >= alvo_alto para sugerir casas de referência."""
    for r in rounds_desc:
        if r["multiplier"] >= alvo_alto:
            digits_str = f"{r['multiplier']:.2f}".replace(".", "")
            seen: list[str] = []
            for ch in digits_str:
                if ch != "0" and ch not in seen:
                    seen.append(ch)
                if len(seen) >= max_casas:
                    break
            return seen
    return []


def parse_multiplier_list(text: str) -> list[float]:
    values: list[float] = []
    for token in text.replace("\n", ",").split(","):
        token = token.strip().lower().replace("x", "")
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


# ---------------------------------------------------------------------------
# CSS global — tema escuro estilo VR5 Analytics
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; }

    .history-scroll {
        max-height: 620px;
        overflow-y: auto;
        overflow-x: auto;
        padding: 6px 2px 8px;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        background: rgba(255,255,255,0.02);
    }
    .history-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
        gap: 8px;
        min-width: 0;
    }
    .history-card {
        width: 100%;
        min-height: 72px;
        border: 2px solid;
        border-radius: 10px;
        padding: 5px 3px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.16);
        box-sizing: border-box;
    }
    .history-value { font-size: 0.92rem; font-weight: 800; line-height: 1.05; margin-bottom: 3px; }
    .history-time { font-size: 0.62rem; opacity: 0.95; line-height: 1.1; }

    .kpi-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 12px 8px;
        text-align: center;
    }
    .kpi-value { font-size: 1.5rem; font-weight: 800; line-height: 1; }
    .kpi-label { font-size: 0.68rem; opacity: 0.7; text-transform: uppercase; letter-spacing: .04em; margin-top: 4px; }

    .indicator-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 2px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        font-size: 0.85rem;
    }

    .casa-chip {
        display: inline-block;
        background: linear-gradient(135deg, #7c3aed 0%, #4c1d95 100%);
        border-radius: 8px;
        padding: 10px 18px;
        margin: 0 8px 8px 0;
        font-weight: 700;
        color: #ffffff;
    }

    .strategy-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 18px;
        height: 100%;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style="height: 12px; border-radius: 999px; margin: 0 0 20px 0;
                background: linear-gradient(90deg, #ef4444 0%, #7f1d1d 50%, #000000 100%);
                box-shadow: 0 8px 24px rgba(239,68,68,0.22);"></div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <div style="margin-bottom: 8px;">
        <h1 style="margin: 0; font-size: 2rem; font-weight: 800; color: #ffffff;">SORTE NA BET 3</h1>
        <p style="margin: 4px 0 0 0; color: #f87171; font-size: 1rem;">Classificação · Painel de análise em tempo real</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if st_autorefresh is not None:
    st_autorefresh(interval=2000, key="rounds_refresh")
else:
    st.caption("Atualização automática indisponível nesta instalação do Streamlit.")

# ---------------------------------------------------------------------------
# Carregamento de dados
# ---------------------------------------------------------------------------
try:
    db_rounds = fetch_recent_rounds(300)
except Exception as exc:
    st.error(f"Não foi possível conectar ao banco de dados: {exc}")
    st.stop()

if not db_rounds:
    st.info("Nenhuma rodada encontrada na tabela public.game_rounds.")
    st.stop()

if "imported_rounds" not in st.session_state:
    st.session_state["imported_rounds"] = []

# Rodadas importadas manualmente (sessão local) entram na frente, como as mais recentes.
rounds: list[dict[str, Any]] = st.session_state["imported_rounds"] + db_rounds
config = load_config()
multipliers = [r["multiplier"] for r in rounds]

tab_resumo, tab_grafico, tab_historico, tab_estrategias = st.tabs(
    ["📊 RESUMO", "📈 GRÁFICO", "📋 HISTÓRICO", "🎯 ESTRATÉGIAS"]
)

# =============================================================================
# 📊 RESUMO
# =============================================================================
with tab_resumo:
    sidebar_col, main_col = st.columns([1, 3], gap="medium")

    with sidebar_col:
        st.markdown("#### ✦ Resumo")
        st.caption("Velas recentes")
        recent_for_bars = list(reversed(rounds[:20]))
        bar_df = pd.DataFrame({"multiplicador": [r["multiplier"] for r in recent_for_bars]})
        st.bar_chart(bar_df, height=140, use_container_width=True)

        total = len(rounds)
        abaixo_2x = sum(1 for m in multipliers if m < config["limite_baixa"])
        dez_mais = sum(1 for m in multipliers if m >= 10)
        cinquenta_mais = sum(1 for m in multipliers if m >= 50)

        k1, k2 = st.columns(2)
        with k1:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-value">{abaixo_2x}</div>'
                f'<div class="kpi-label">abaixo {config["limite_baixa"]:g}x</div></div>',
                unsafe_allow_html=True,
            )
        with k2:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-value">{dez_mais}</div>'
                f'<div class="kpi-label">10x+</div></div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div class="kpi-card" style="margin-top:8px;"><div class="kpi-value">{cinquenta_mais}</div>'
            f'<div class="kpi-label">50x+</div></div>',
            unsafe_allow_html=True,
        )

        media = mean(multipliers)
        maior = max(multipliers)
        k3, k4 = st.columns(2)
        k3.metric("Média", f"{media:.2f}x")
        k4.metric("Maior", f"{maior:.2f}x")

        st.markdown("#### ⚙ Indicadores")
        seq_abaixo = current_streak(rounds, lambda m: m < config["limite_baixa"])
        seq_dez = current_streak(rounds, lambda m: m >= 10)
        ultima_50 = rounds_since_last(rounds, lambda m: m >= 50)
        st.markdown(
            f'<div class="indicator-row"><span>Sequência abaixo de {config["limite_baixa"]:g}x</span><b>{seq_abaixo}</b></div>'
            f'<div class="indicator-row"><span>Sequência 10x+</span><b>{seq_dez}</b></div>'
            f'<div class="indicator-row"><span>Última 50x+</span><b>{ultima_50}</b></div>',
            unsafe_allow_html=True,
        )

        st.markdown("#### Importar resultados")
        st.caption("Somente para visualização nesta sessão — não grava no banco.")
        pasted = st.text_area(
            "Cole números: 1.25x, 2.50x, 15.10x...",
            key="import_box",
            height=90,
            label_visibility="collapsed",
        )
        imp_col1, imp_col2 = st.columns(2)
        with imp_col1:
            if st.button("Importar velas", use_container_width=True):
                novos = parse_multiplier_list(pasted)
                if novos:
                    now = datetime.now()
                    for valor in novos:
                        st.session_state["imported_rounds"].insert(
                            0,
                            {
                                "round_id": f"manual-{len(st.session_state['imported_rounds'])}",
                                "multiplier": valor,
                                "round_timestamp": now,
                                "source": "manual",
                                "created_at": now,
                                "imported": True,
                            },
                        )
                    st.success(f"{len(novos)} vela(s) importada(s).")
                    st.rerun()
                else:
                    st.warning("Nenhum multiplicador válido encontrado.")
        with imp_col2:
            if st.button("Limpar importadas", use_container_width=True):
                st.session_state["imported_rounds"] = []
                st.rerun()

    with main_col:
        st.markdown(f"**RODADAS** &nbsp;·&nbsp; {len(rounds)} resultados &nbsp;·&nbsp; maior **{maior:.2f}x**")
        card_html = []
        for r in rounds:
            m = r["multiplier"]
            background, border, text_color = get_card_style(m)
            display_time = format_round_time(r)
            card_html.append(
                f'<div class="history-card" style="background:{background}; border-color:{border}; color:{text_color};">'
                f'<div class="history-value">{m:.2f}x</div>'
                f'<div class="history-time">{display_time}</div></div>'
            )
        st.markdown(
            f'<div class="history-scroll"><div class="history-grid">{"".join(card_html)}</div></div>',
            unsafe_allow_html=True,
        )

# =============================================================================
# 📈 GRÁFICO
# =============================================================================
with tab_grafico:
    st.markdown("#### Gráfico das rodadas")
    st.caption("Evolução dos multiplicadores ao longo do tempo · arraste para navegar, roda do mouse para zoom")

    chrono = list(reversed(rounds))  # ordem cronológica: mais antiga -> mais recente

    if PLOTLY_AVAILABLE:
        x = list(range(len(chrono)))
        y = [r["multiplier"] for r in chrono]
        colors = []
        for m in y:
            if m >= 10:
                colors.append("#ff2f92")
            elif m >= 2:
                colors.append("#38bdf8")
            else:
                colors.append("#64748b")

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=x, y=y, mode="lines",
                line=dict(color="rgba(148,163,184,0.45)", width=1.5),
                hoverinfo="skip", showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x, y=y, mode="markers",
                marker=dict(color=colors, size=6, line=dict(width=0)),
                text=[format_round_time(r) for r in chrono],
                hovertemplate="%{text}<br>%{y:.2f}x<extra></extra>",
                showlegend=False,
            )
        )
        fig.update_layout(
            paper_bgcolor="#0b1026",
            plot_bgcolor="#0b1026",
            font_color="#e2e8f0",
            margin=dict(l=10, r=10, t=10, b=10),
            height=560,
            xaxis=dict(showgrid=False, zeroline=False, visible=False),
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", title="Multiplicador"),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("● <2x   ● 2x–9.99x   ● 10x+")
    else:
        chart_df = pd.DataFrame(
            {"multiplicador": [r["multiplier"] for r in chrono]},
            index=[format_round_time(r) for r in chrono],
        )
        st.line_chart(chart_df, height=560, use_container_width=True)
        st.caption("Instale `plotly` (pip install plotly) para o gráfico colorido por faixa de multiplicador.")

# =============================================================================
# 📋 HISTÓRICO
# =============================================================================
with tab_historico:
    st.markdown("#### Histórico completo")

    total = len(rounds)
    table_rows = []
    for i, r in enumerate(rounds):
        table_rows.append(
            {
                "#": total - i,
                "Multiplicador": f"{r['multiplier']:.2f}x",
                "Classificação": classify_multiplier(r["multiplier"], config["limite_baixa"], config["alvo_alto"]),
                "Horário": format_round_time(r),
            }
        )
    df_hist = pd.DataFrame(table_rows)
    st.dataframe(df_hist, use_container_width=True, hide_index=True, height=620)

    csv_bytes = df_hist.to_csv(index=False).encode("utf-8")
    st.download_button("Exportar CSV", data=csv_bytes, file_name="historico_rodadas.csv", mime="text/csv")

# =============================================================================
# 🎯 ESTRATÉGIAS
# =============================================================================
with tab_estrategias:
    col_a, col_b, col_c = st.columns(3, gap="medium")

    with col_a:
        st.markdown('<div class="strategy-card">', unsafe_allow_html=True)
        st.markdown("##### Ausência de 50x")
        st.caption("Conta quantas rodadas ocorreram desde a última rodada acima de 50x.")
        ausencia = rounds_since_last(rounds, lambda m: m >= 50)
        st.markdown(
            f'<div class="kpi-value" style="font-size:2.3rem;">{ausencia}</div>'
            f'<div class="kpi-label">rodadas desde 50x+</div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col_b:
        st.markdown('<div class="strategy-card">', unsafe_allow_html=True)
        st.markdown("##### Casas indicadas")
        st.caption("Usa os dígitos do último multiplicador alto para mostrar casas de referência.")
        casas = casas_indicadas(rounds, config["alvo_alto"])
        if casas:
            chips = "".join(f'<span class="casa-chip">{d}ª casa</span>' for d in casas)
            st.markdown(chips, unsafe_allow_html=True)
        else:
            st.caption("Nenhuma rodada acima do alvo alto ainda.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_c:
        st.markdown('<div class="strategy-card">', unsafe_allow_html=True)
        st.markdown("##### Configuração")
        with st.form("config_form"):
            limite_baixa = st.number_input(
                "Limite de baixa", min_value=1.0, step=0.5, value=float(config["limite_baixa"])
            )
            alvo_alto = st.number_input(
                "Alvo alto", min_value=2.0, step=1.0, value=float(config["alvo_alto"])
            )
            submitted = st.form_submit_button("Salvar configuração", use_container_width=True)
            if submitted:
                save_config({"limite_baixa": limite_baixa, "alvo_alto": alvo_alto})
                st.success("Configuração salva.")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
