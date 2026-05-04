# Telegram Flight Alert Bot

Bot simples para alertar no Telegram quando aparecer passagem abaixo do preco-alvo.

## O que ele monitora

- Passagens so ida
- Passagens ida e volta
- Rotas configuradas em `routes.json`
- Datas entre `START_DATE` e `END_DATE`
- Precos-alvo configurados no `.env`

## Passo a passo no Windows

### 1. Instalar Python

No PowerShell, teste:

```powershell
py --version
```

Se nao aparecer a versao, instale Python em https://www.python.org/downloads/ e marque `Add Python to PATH`.

### 2. Instalar dependencias

Na pasta do bot:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install_windows.ps1
```

Isso cria o ambiente virtual, instala dependencias e cria o `.env` se ele ainda nao existir.

### 3. Configurar `.env`

Abra o arquivo `.env` e preencha:

```text
TELEGRAM_BOT_TOKEN=seu_token_novo_do_botfather
TELEGRAM_CHAT_ID=seu_chat_id
SERPAPI_KEY=sua_chave_serpapi
```

Para teste, deixe:

```text
MAX_CHECKS_PER_RUN=5
ONEWAY_TARGET_BRL=10000
ROUNDTRIP_TARGET_BRL=10000
```

Depois que confirmar que esta funcionando, volte para:

```text
ONEWAY_TARGET_BRL=1800
ROUNDTRIP_TARGET_BRL=3600
MAX_CHECKS_PER_RUN=0
```

### 4. Testar Telegram

```powershell
.\test_telegram_windows.ps1
```

Se chegar uma mensagem no Telegram, essa parte esta OK.

### 5. Ver configuracao

```powershell
.\show_config_windows.ps1
```

### 6. Testar uma rodada curta

```powershell
.\run_once_windows.ps1
```

### 7. Rodar continuamente

```powershell
.\.venv\Scripts\Activate.ps1
py flight_alert_bot.py
```

## Criar o bot no Telegram

1. Abra o Telegram e fale com `@BotFather`.
2. Envie `/newbot`.
3. Escolha nome e username.
4. Copie o token gerado.
5. Nao compartilhe esse token.

## Descobrir seu CHAT_ID

1. Mande `/start` ou `oi` para o seu bot.
2. Abra no navegador:

```text
https://api.telegram.org/botSEU_TOKEN/getUpdates
```

3. Procure por `chat` > `id`.

## Criar chave da SerpApi

Crie uma conta em https://serpapi.com/ e copie sua API key.

## Observacao sobre creditos

Cada consulta consome credito da SerpApi. Para testes, use `MAX_CHECKS_PER_RUN=5`. Para rodar completo, use `MAX_CHECKS_PER_RUN=0`.
