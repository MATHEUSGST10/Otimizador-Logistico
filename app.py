import streamlit as st
import pandas as pd
import math
import io
import sqlite3
import os
import plotly.express as px
from datetime import datetime
from ortools.linear_solver import pywraplp

# =========================
# BANCO
# =========================

conn = sqlite3.connect("usuarios.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios (
    email TEXT,
    senha TEXT,
    empresa TEXT,
    tipo TEXT
)
""")
conn.commit()

# ADMIN PADRÃO
admin = ("admin@admin.com", "admin123", "Admin", "admin")

cursor.execute("SELECT * FROM usuarios WHERE email=?", (admin[0],))
if not cursor.fetchone():
    cursor.execute("INSERT INTO usuarios VALUES (?,?,?,?)", admin)
    conn.commit()

# =========================
# LOGIN
# =========================

def tela_login():

    if "email" not in st.session_state:
        st.session_state["email"] = ""

    if "senha" not in st.session_state:
        st.session_state["senha"] = ""

    st.title("🔐 Login")

    email = st.text_input("Email", key="email")
    senha = st.text_input("Senha", type="password", key="senha")

    if st.button("Entrar"):
        cursor.execute("SELECT * FROM usuarios WHERE email=? AND senha=?", (email, senha))
        user = cursor.fetchone()

        if user:
            st.session_state["logado"] = True
            st.session_state["empresa"] = user[2]
            st.session_state["tipo"] = user[3]

            st.session_state.pop("email", None)
            st.session_state.pop("senha", None)

            st.rerun()
        else:
            st.error("Login inválido")

def tela_cadastro():
    st.subheader("Cadastrar Usuário")

    email = st.text_input("Novo email")
    senha = st.text_input("Senha", type="password")
    empresa = st.text_input("Empresa")

    if st.button("Cadastrar"):
        cursor.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (email, senha, empresa, "cliente"))
        conn.commit()
        st.success("Usuário criado!")

# =========================
# CONTROLE LOGIN
# =========================

if "logado" not in st.session_state:
    st.session_state["logado"] = False

if not st.session_state["logado"]:
    tela_login()
    st.stop()

# =========================
# RESET
# =========================

def reset_otimizacao():
    for k in list(st.session_state.keys()):
        if k not in ["logado", "empresa", "tipo", "usar_bid_salvo"]:
            del st.session_state[k]

# =========================
# HEADER
# =========================

st.set_page_config(layout="wide")

# 🔥 VISUAL MELHORADO
st.markdown("""
<style>
div[data-testid="metric-container"] {
    background-color: #111827;
    border: 1px solid #1f2937;
    padding: 15px;
    border-radius: 12px;
}
</style>
""", unsafe_allow_html=True)

colA, colB, colC = st.columns([6,2,2])

with colA:
    st.title(f"🚛 Otimizador - {st.session_state['empresa']}")

with colB:
    if st.button("🔄 Nova Otimização", use_container_width=True):
        reset_otimizacao()
        st.rerun()

with colC:
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ADMIN PANEL
if st.session_state["tipo"] == "admin":
    with st.expander("⚙️ Administração"):
        tela_cadastro()

# =========================
# FROTA
# =========================

tem_frota = st.selectbox("🚛 Possui frota?", ["Sim", "Não"])

hoje = pd.Timestamp.today().normalize()

frota_por_dia = {}

if tem_frota == "Sim":
    col1, col2, col3 = st.columns(3)

    frota_por_dia[0] = col1.number_input("Dia 0 (Hoje)", 0, 100, 8)
    frota_por_dia[1] = col2.number_input("Dia 1", 0, 100, 8)
    frota_por_dia[2] = col3.number_input("Dia 2", 0, 100, 8)

# =========================
# BID SALVO
# =========================

arquivo_bid = f"bid_{st.session_state['empresa']}.xlsx"

if "usar_bid_salvo" not in st.session_state:
    st.session_state["usar_bid_salvo"] = False

if os.path.exists(arquivo_bid):
    data_mod = datetime.fromtimestamp(os.path.getmtime(arquivo_bid))
    st.info(f"📁 Último BID salvo: {data_mod.strftime('%d/%m/%Y %H:%M')}")

    st.session_state["usar_bid_salvo"] = st.checkbox(
        "Usar último BID salvo?",
        value=st.session_state["usar_bid_salvo"]
    )

usar_bid_salvo = st.session_state["usar_bid_salvo"]

# =========================
# UPLOAD
# =========================

if usar_bid_salvo:
    st.success("Usando BID salvo ✅")
    bid_file = None
else:
    bid_file = st.file_uploader("📤 Upload BID")

cargas_file = st.file_uploader("📤 Upload CARGAS")

# =========================
# OTIMIZAÇÃO
# =========================

if st.button("🚀 Otimizar"):

    if not usar_bid_salvo and bid_file is None:
        st.warning("Suba o BID")
        st.stop()

    if cargas_file is None:
        st.warning("Suba as cargas")
        st.stop()

    if usar_bid_salvo:
        bid = pd.read_excel(arquivo_bid)
    else:
        bid = pd.read_excel(bid_file)
        with open(arquivo_bid, "wb") as f:
            f.write(bid_file.getbuffer())

    cargas = pd.read_excel(cargas_file)

    bid.columns = bid.columns.str.lower()
    cargas.columns = cargas.columns.str.lower()

    cargas["data_coleta"] = pd.to_datetime(cargas["data_coleta"]).dt.normalize()
    cargas["dias"] = (cargas["data_coleta"] - hoje).dt.days

    def rota(df):
        return (
            df["cidade_origem"].astype(str).str.lower() + "|" +
            df["cidade_destino"].astype(str).str.lower() + "|" +
            df["tipo_veiculo"].astype(str).str.lower()
        )

    bid["id_rota"] = rota(bid)
    cargas["id_rota"] = rota(cargas)

    fretes = {}

    for r, g in bid.groupby("id_rota"):
        f = g[g["transportadora"].str.lower() == "frota"]
        t = g[g["transportadora"].str.lower() != "frota"]

        if not f.empty and not t.empty:
            fretes[r] = {
                "frota": f["valor_frete"].min(),
                "terceiro": t["valor_frete"].min(),
                "lead": g["lead_time"].iloc[0]
            }

    cargas["decisao_final"] = "TERCEIRO"
    cargas["economia"] = 0.0
    total_viagens_frota = 0

    for dia in [0,1,2]:

        if frota_por_dia.get(dia, 0) == 0:
            continue

        cargas_dia = cargas[cargas["dias"] == dia]

        rotas = []

        for r, g in cargas_dia.groupby("id_rota"):

            if r not in fretes:
                continue

            dados = fretes[r]
            econ = dados["terceiro"] - dados["frota"]

            capacidade = {"24t":24000,"truck":12000,"toco":6000}.get(
                g["tipo_veiculo"].iloc[0].lower(), 999999
            )

            viagens = math.ceil(g["peso_kg"].sum() / capacidade)
            tempo = dados["lead"] * 2

            score = (econ * viagens) / tempo if tempo > 0 else 0

            rotas.append({
                "rota": r,
                "viagens": viagens,
                "score": score,
                "economia": econ * viagens
            })

        if not rotas:
            continue

        solver = pywraplp.Solver.CreateSolver("SCIP")
        x = {i: solver.IntVar(0,1,f"x{i}") for i in range(len(rotas))}

        solver.Add(sum(x[i]*rotas[i]["viagens"] for i in x) <= frota_por_dia[dia])
        solver.Maximize(sum(x[i]*rotas[i]["score"] for i in x))

        solver.Solve()

        escolhidas = [rotas[i]["rota"] for i in x if x[i].solution_value() == 1]

        total_viagens_frota += sum(
            rotas[i]["viagens"] for i in x if x[i].solution_value() == 1
        )

        cargas.loc[
            (cargas["dias"] == dia) &
            (cargas["id_rota"].isin(escolhidas)),
            "decisao_final"
        ] = "FROTA"

    for i in range(len(cargas)):
        rota = cargas.iloc[i]["id_rota"]
        if rota in fretes:
            econ = fretes[rota]["terceiro"] - fretes[rota]["frota"]
            if cargas.iloc[i]["decisao_final"] == "FROTA":
                cargas.at[i, "economia"] = float(econ)

    # =========================
    # KPIs MELHORADOS
    # =========================

    total = len(cargas)
    terceiro = (cargas["decisao_final"] == "TERCEIRO").sum()
    economia_total = cargas["economia"].sum()

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("📦 Total de cargas", total)
    col2.metric("🚛 Frota utilizada", total_viagens_frota)
    col3.metric("📉 Cargas em terceiro", terceiro)
    col4.metric("💰 Economia total", f"R$ {economia_total:,.2f}")

    # =========================
    # GRÁFICOS
    # =========================

    colg1, colg2 = st.columns(2)

    with colg1:
        fig1 = px.pie(
            names=["FROTA", "TERCEIRO"],
            values=[total_viagens_frota, terceiro],
            title="Distribuição de Transporte",
            hole=0.4
        )
        st.plotly_chart(fig1, use_container_width=True)

    with colg2:
        df_plot = (
            cargas.groupby(["cidade_destino", "decisao_final"])
            .size()
            .reset_index(name="qtd")
        )

        fig2 = px.bar(
            df_plot,
            x="cidade_destino",
            y="qtd",
            color="decisao_final",
            barmode="stack",
            title="Frota vs Terceiro por Destino"
        )

        st.plotly_chart(fig2, use_container_width=True)

    # RESULTADO
    cargas["data_coleta"] = cargas["data_coleta"].dt.strftime("%d/%m/%Y")

    st.success("✅ Otimização concluída!")
    st.dataframe(cargas)

    output = io.BytesIO()
    cargas.to_excel(output, index=False)
    output.seek(0)

    st.download_button("📥 Baixar resultado", output, "resultado.xlsx")
