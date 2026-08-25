# Win Daniel - Painel Streamlit

Este projeto é um painel em Streamlit para visualizar as últimas rodadas de um jogo a partir de um banco PostgreSQL.

## Estrutura principal

- `app.py` — ponto de entrada para execução local e para o Streamlit Cloud.
- `app_streamlit.py` — aplicação principal com a UI e a conexão ao banco.
- `.env` — arquivo local com variáveis de ambiente para execução local.
- `.streamlit/secrets.toml` — arquivo usado pelo Streamlit Cloud para secrets.

## Requisitos

Instale as dependências com:

```bash
pip install -r requirements.txt
```

## Execução local

```bash
cd /home/samuel/Projeto\ Daniel\ Win\ \ original/win_daniel_estrutura_inicial
source .venv/bin/activate
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

A aplicação ficará disponível em:

```text
http://localhost:8501
```

## Configuração da DATABASE_URL

O painel depende da variável `DATABASE_URL` para conectar ao PostgreSQL.

### Opção 1 — execução local
Edite o arquivo `.env` com a sua conexão:

```env
DATABASE_URL=postgresql://usuario:senha@host:5432/banco
```

### Opção 2 — deploy no Streamlit Cloud
No Streamlit Cloud, use o arquivo `.streamlit/secrets.toml` (ou configure os secrets diretamente na interface do Streamlit Cloud).

Exemplo:

```toml
[general]
DATABASE_URL = "postgresql://usuario:senha@host:5432/banco"
```

> O projeto lê a variável `DATABASE_URL` via `os.getenv("DATABASE_URL")`.

## Deploy no Streamlit Cloud

1. Envie este projeto para um repositório GitHub.
2. Acesse o Streamlit Cloud.
3. Crie um novo app apontando para o repositório.
4. Defina o arquivo principal como `app.py`.
5. Configure a secret `DATABASE_URL` no painel de Secrets do Streamlit Cloud.

## Observação importante

Para deploy público gratuito, a conexão com o banco precisa ser acessível pela internet ou por uma solução compatível com o Streamlit Cloud. Se o banco estiver apenas em rede local, o painel só funcionará localmente ou em uma rede que permita acesso externo.
