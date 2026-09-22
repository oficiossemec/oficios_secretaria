import datetime
import zoneinfo
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# Configuração da página
st.set_page_config(
    page_title="Ofícios SEMEC",
    layout="wide",
)

# Conexão com o Supabase usando as chaves dos Secrets
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()


# Função para obter a hora atual no fuso da Bahia / Brasília (UTC-3)
def obter_data_hora_brasil():
    try:
        fuso_br = zoneinfo.ZoneInfo("America/Bahia")
        return datetime.datetime.now(fuso_br).strftime("%d/%m/%Y %H:%M")
    except Exception:
        # Fallback de 3 horas a menos caso a timezone não esteja disponível
        fuso_manual = datetime.timezone(datetime.timedelta(hours=-3))
        return datetime.datetime.now(fuso_manual).strftime("%d/%m/%Y %H:%M")


# Função para obter a sugestão do próximo número de ofício
def obter_sugestao_numero(ano_atual):
    response = (
        supabase.table("oficios")
        .select("numero")
        .eq("ano", ano_atual)
        .order("numero", desc=True)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]["numero"] + 1
    return 1


# Função para salvar o ofício no Supabase via RPC (Atómica / Anti-concorrência)
def salvar_oficio(ano_atual, tema, setor, responsavel):
    data_hoje = obter_data_hora_brasil()

    try:
        # Chama a função PL/pgSQL no Supabase que trava a tabela e gera o número único
        resultado = supabase.rpc(
            "registrar_oficio",
            {
                "p_ano": ano_atual,
                "p_tema": tema,
                "p_setor": setor,
                "p_responsavel": responsavel,
                "p_data_emissao": data_hoje,
            },
        ).execute()

        if resultado.data:
            codigo_gerado = resultado.data[0]["codigo_oficio"]
            return (
                True,
                f"✅ Ofício cadastrado com sucesso! **Número: {codigo_gerado}**",
            )
        else:
            return False, "❌ Erro ao registrar o ofício. Tente novamente."

    except Exception as e:
        return False, f"❌ Erro ao salvar no banco de dados: {str(e)}"


# Função para remover um ofício do banco de dados
def deletar_oficio(id_oficio):
    supabase.table("oficios").delete().eq("id", id_oficio).execute()


# --- CABEÇALHO COM LOGO ---
col_logo, col_titulo = st.columns([1, 4])

with col_logo:
    try:
        st.image("logo.png", width=140)
    except Exception:
        st.info("🖼️ [Envie o arquivo logo.png para o GitHub]")

with col_titulo:
    st.title("Sistema de Numeração de Ofícios")
    st.subheader("Secretaria Municipal de Educação de Mansidão")

st.divider()

# Obtém o ano atual considerando o fuso da Bahia/Brasília
try:
    fuso_br = zoneinfo.ZoneInfo("America/Bahia")
    ano_atual = datetime.datetime.now(fuso_br).year
except Exception:
    ano_atual = datetime.datetime.now().year

sugestao_num = obter_sugestao_numero(ano_atual)

# Formulário de Cadastro
with st.form("form_oficio", clear_on_submit=False):
    col1, col2, col3 = st.columns([1, 2, 2])

    with col1:
        sugestao_formatada = f"{int(sugestao_num):03d}"
        st.text_input(
            "Próximo Número (Automático)",
            value=sugestao_formatada,
            disabled=True,
            help="O número é gerado sequencialmente e bloqueado para evitar duplicidades em acessos simultâneos.",
        )

    with col2:
        setor = st.text_input("Setor / Departamento")

    with col3:
        responsavel = st.text_input("Nome do Responsável")

    tema = st.text_area("Assunto / Tema do Ofício")

    submetido = st.form_submit_button("Registrar Ofício")

    if submetido:
        if tema and setor and responsavel:
            sucesso, mensagem = salvar_oficio(
                ano_atual, tema, setor, responsavel
            )

            if sucesso:
                st.success(mensagem)
                st.rerun()
            else:
                st.error(mensagem)
        else:
            st.warning("⚠️ Preencha todos os campos antes de registrar.")

st.divider()

# Tabela de Consulta em Tempo Real
st.subheader("Ofícios Registrados")

response = (
    supabase.table("oficios")
    .select("id, codigo_oficio, numero, ano, tema, setor, responsavel, data_emissao")
    .order("id", desc=True)
    .execute()
)
registros = response.data

if registros:
    df = pd.DataFrame(registros)
    df = df.rename(
        columns={
            "id": "ID",
            "codigo_oficio": "Código",
            "numero": "Número",
            "ano": "Ano",
            "tema": "Assunto / Tema",
            "setor": "Setor",
            "responsavel": "Responsável",
            "data_emissao": "Data/Hora",
        }
    )

    col_busca, col_download = st.columns([3, 1])

    with col_busca:
        busca = st.text_input(
            "🔍 Buscar por assunto, código, responsável ou setor:"
        )

    with col_download:
        csv_excel = df.drop(columns=["ID"]).to_csv(
            index=False, sep=";", encoding="utf-8-sig"
        )
        data_hoje_str = datetime.datetime.now().strftime("%Y-%m-%d")

        st.write("")
        st.download_button(
            label="📥 Baixar Backup (Excel)",
            data=csv_excel,
            file_name=f"backup_oficios_{data_hoje_str}.csv",
            mime="text/csv",
            help="Baixa uma planilha formatada com todos os ofícios registrados.",
        )

    if busca:
        df_exibicao = df[
            df.apply(
                lambda row: row.astype(str)
                .str.contains(busca, case=False)
                .any(),
                axis=1,
            )
        ]
    else:
        df_exibicao = df

    st.dataframe(df_exibicao.drop(columns=["ID"]), width=1000)

    st.divider()

    # Área de Exclusão de Ofício
    st.subheader("🗑️ Cancelar / Remover Ofício Cadastrado")

    opcoes_oficios = {
        f"{row['Código']} - {row['Assunto / Tema']} ({row['Setor']})": row["ID"]
        for _, row in df.iterrows()
    }

    oficio_selecionado = st.selectbox(
        "Selecione o ofício que deseja remover:", list(opcoes_oficios.keys())
    )

    if st.button("❌ Confirmar Exclusão", type="primary"):
        id_para_deletar = opcoes_oficios[oficio_selecionado]
        deletar_oficio(id_para_deletar)
        st.success("Ofício removido com sucesso!")
        st.rerun()
else:
    st.info("Nenhum ofício cadastrado até o momento.")
