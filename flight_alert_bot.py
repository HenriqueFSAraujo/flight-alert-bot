import argparse
import json
import os
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    raw = env_str(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Variavel {name} precisa ser um numero inteiro. Valor atual: {raw}") from exc


def env_float(name: str, default: float) -> float:
    raw = env_str(name, str(default))
    try:
        return float(raw.replace(",", "."))
    except ValueError as exc:
        raise RuntimeError(f"Variavel {name} precisa ser um numero. Valor atual: {raw}") from exc


def env_bool(name: str, default: bool) -> bool:
    raw = env_str(name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "sim", "s"}:
        return True
    if raw in {"0", "false", "no", "nao", "n"}:
        return False
    raise RuntimeError(f"Variavel {name} precisa ser true ou false. Valor atual: {raw}")


def env_int_list(name: str, default: str) -> List[int]:
    raw = env_str(name, default)
    values = [part.strip() for part in raw.split(",") if part.strip()]
    if not values:
        raise RuntimeError(f"Variavel {name} precisa ter pelo menos um valor.")
    try:
        return [int(value) for value in values]
    except ValueError as exc:
        raise RuntimeError(f"Variavel {name} precisa conter apenas numeros separados por virgula.") from exc


TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env_str("TELEGRAM_CHAT_ID")
SERPAPI_KEY = env_str("SERPAPI_KEY")

CURRENCY = env_str("CURRENCY", "BRL")
LANGUAGE = env_str("LANGUAGE", "pt-BR")
COUNTRY = env_str("COUNTRY", "br")
CHECK_EVERY_MINUTES = env_int("CHECK_EVERY_MINUTES", 60)

START_DATE = env_str("START_DATE", "2027-02-01")
END_DATE = env_str("END_DATE", "2027-03-31")
DATE_STEP_DAYS = env_int("DATE_STEP_DAYS", 3)
ROUND_TRIP_DURATIONS = env_int_list("ROUND_TRIP_DURATIONS", "12,14,16")

ONEWAY_TARGET_BRL = env_int("ONEWAY_TARGET_BRL", 1800)
ROUNDTRIP_TARGET_BRL = env_int("ROUNDTRIP_TARGET_BRL", 3600)

REQUEST_SLEEP_SECONDS = env_float("REQUEST_SLEEP_SECONDS", 2)
MAX_CHECKS_PER_RUN = env_int("MAX_CHECKS_PER_RUN", 0)
SEND_STARTUP_MESSAGE = env_bool("SEND_STARTUP_MESSAGE", True)
DEEP_SEARCH = env_bool("DEEP_SEARCH", False)

DB_PATH = BASE_DIR / env_str("DB_PATH", "alerts_sent.sqlite3")
ROUTES_PATH = BASE_DIR / env_str("ROUTES_PATH", "routes.json")


def require_env(*, need_telegram: bool = True, need_serpapi: bool = True) -> None:
    missing = []
    if need_telegram:
        for key, value in {
            "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
            "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        }.items():
            if not value or value.startswith("cole_aqui"):
                missing.append(key)
    if need_serpapi and (not SERPAPI_KEY or SERPAPI_KEY.startswith("cole_aqui")):
        missing.append("SERPAPI_KEY")

    if missing:
        raise RuntimeError("Variaveis faltando no .env: " + ", ".join(missing))


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(f"Data invalida: {value}. Use o formato AAAA-MM-DD.") from exc


def daterange(start: str, end: str, step_days: int = 1) -> Iterable[date]:
    if step_days < 1:
        raise RuntimeError("DATE_STEP_DAYS precisa ser maior ou igual a 1.")

    current = parse_date(start)
    last = parse_date(end)
    if current > last:
        raise RuntimeError("START_DATE nao pode ser depois de END_DATE.")

    while current <= last:
        yield current
        current += timedelta(days=step_days)


def load_routes() -> Dict[str, List[Dict[str, str]]]:
    if not ROUTES_PATH.exists():
        raise RuntimeError(f"Arquivo de rotas nao encontrado: {ROUTES_PATH}")

    with ROUTES_PATH.open("r", encoding="utf-8") as f:
        routes = json.load(f)

    for section in ("oneway", "roundtrip"):
        entries = routes.get(section, [])
        if not isinstance(entries, list):
            raise RuntimeError(f"A chave {section} em routes.json precisa ser uma lista.")
        for index, route in enumerate(entries, start=1):
            if not isinstance(route, dict) or not route.get("from") or not route.get("to"):
                raise RuntimeError(f"Rota invalida em {section}[{index}]. Use: {{\"from\": \"CNF\", \"to\": \"LIS\"}}")
    return routes


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts_sent (
                fingerprint TEXT PRIMARY KEY,
                sent_at TEXT NOT NULL
            )
            """
        )


def was_sent(fingerprint: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT 1 FROM alerts_sent WHERE fingerprint = ?", (fingerprint,)).fetchone()
    return row is not None


def mark_sent(fingerprint: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO alerts_sent (fingerprint, sent_at) VALUES (?, ?)",
            (fingerprint, datetime.now().isoformat(timespec="seconds")),
        )


def send_telegram(message: str) -> None:
    require_env(need_telegram=True, need_serpapi=False)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    response.raise_for_status()


def search_google_flights(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: Optional[str] = None,
) -> Dict[str, Any]:
    params = {
        "engine": "google_flights",
        "api_key": SERPAPI_KEY,
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "currency": CURRENCY,
        "hl": LANGUAGE,
        "gl": COUNTRY,
        "type": "1" if return_date else "2",
        "deep_search": "true" if DEEP_SEARCH else "false",
    }
    if return_date:
        params["return_date"] = return_date

    response = requests.get(SERPAPI_ENDPOINT, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def parse_price(value: Any) -> Optional[int]:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if digits:
            return int(digits)
    return None


def extract_best_price(result: Dict[str, Any]) -> Optional[Tuple[int, str, str]]:
    candidates = []
    for section in ("best_flights", "other_flights"):
        for item in result.get(section, []) or []:
            price = parse_price(item.get("price"))
            if price is None:
                continue

            airline = " + ".join(
                sorted({leg.get("airline", "") for leg in item.get("flights", []) if leg.get("airline")})
            ) or "Companhia nao informada"
            link = result.get("search_metadata", {}).get("google_flights_url") or "https://www.google.com/travel/flights"
            candidates.append((price, airline, link))

    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


def money(value: int) -> str:
    return f"R$ {value:,.0f}".replace(",", ".")


def alert_if_cheap(
    trip_type: str,
    origin: str,
    destination: str,
    outbound: str,
    return_date: Optional[str],
    target: int,
    *,
    dry_run: bool = False,
) -> bool:
    result = search_google_flights(origin, destination, outbound, return_date)
    best = extract_best_price(result)
    if not best:
        print(f"Sem preco: {origin}->{destination} {outbound} {return_date or ''}".strip())
        return False

    price, airline, link = best
    route_label = f"{origin}->{destination} {outbound} {return_date or ''}".strip()
    print(f"{route_label}: {money(price)}")

    if price > target:
        return False

    fingerprint = f"{trip_type}|{origin}|{destination}|{outbound}|{return_date or '-'}|{price}|{airline}"
    if was_sent(fingerprint):
        print("Alerta ja enviado para este preco.")
        return False

    label = "So ida" if trip_type == "oneway" else "Ida e volta"
    message = (
        "Alerta de passagem\n\n"
        f"Rota: {origin} -> {destination}\n"
        f"Tipo: {label}\n"
        f"Ida: {outbound}\n"
        + (f"Volta: {return_date}\n" if return_date else "")
        + f"Preco: {money(price)}\n"
        f"Alvo: ate {money(target)}\n"
        f"Companhia: {airline}\n\n"
        f"Ver: {link}"
    )

    if dry_run:
        print("[dry-run] Alerta encontrado, mas nao enviado:")
        print(message)
        return True

    send_telegram(message)
    mark_sent(fingerprint)
    print("Alerta enviado.")
    return True


def maybe_stop(check_count: int, max_checks: int) -> bool:
    return max_checks > 0 and check_count >= max_checks


def pause_between_requests() -> None:
    if REQUEST_SLEEP_SECONDS > 0:
        time.sleep(REQUEST_SLEEP_SECONDS)


def run_once(*, dry_run: bool = False, max_checks: int = 0) -> int:
    routes = load_routes()
    dates = list(daterange(START_DATE, END_DATE, step_days=DATE_STEP_DAYS))
    alerts_found = 0
    checks = 0

    for route in routes.get("oneway", []):
        for outbound in dates:
            if maybe_stop(checks, max_checks):
                return alerts_found
            try:
                checks += 1
                if alert_if_cheap(
                    "oneway",
                    route["from"],
                    route["to"],
                    outbound.isoformat(),
                    None,
                    ONEWAY_TARGET_BRL,
                    dry_run=dry_run,
                ):
                    alerts_found += 1
                pause_between_requests()
            except Exception as exc:
                print(f"Erro em so ida {route}: {exc}")

    return_limit = parse_date(END_DATE) + timedelta(days=30)
    for route in routes.get("roundtrip", []):
        for outbound in dates:
            for duration in ROUND_TRIP_DURATIONS:
                if maybe_stop(checks, max_checks):
                    return alerts_found

                return_day = outbound + timedelta(days=duration)
                if return_day > return_limit:
                    continue

                try:
                    checks += 1
                    if alert_if_cheap(
                        "roundtrip",
                        route["from"],
                        route["to"],
                        outbound.isoformat(),
                        return_day.isoformat(),
                        ROUNDTRIP_TARGET_BRL,
                        dry_run=dry_run,
                    ):
                        alerts_found += 1
                    pause_between_requests()
                except Exception as exc:
                    print(f"Erro em ida e volta {route}: {exc}")

    return alerts_found


def show_config() -> None:
    routes = load_routes()
    dates = list(daterange(START_DATE, END_DATE, step_days=DATE_STEP_DAYS))
    oneway_checks = len(routes.get("oneway", [])) * len(dates)
    roundtrip_checks = len(routes.get("roundtrip", [])) * len(dates) * len(ROUND_TRIP_DURATIONS)
    max_checks = MAX_CHECKS_PER_RUN or "sem limite"

    print("Configuracao atual")
    print(f"Rotas so ida: {len(routes.get('oneway', []))}")
    print(f"Rotas ida e volta: {len(routes.get('roundtrip', []))}")
    print(f"Janela de datas: {START_DATE} ate {END_DATE}, pulando de {DATE_STEP_DAYS} em {DATE_STEP_DAYS} dia(s)")
    print(f"Duracoes ida e volta: {ROUND_TRIP_DURATIONS}")
    print(f"Consultas estimadas por rodada: {oneway_checks + roundtrip_checks}")
    print(f"Limite por rodada: {max_checks}")
    print(f"Intervalo entre rodadas: {CHECK_EVERY_MINUTES} minuto(s)")
    print(f"Intervalo entre chamadas: {REQUEST_SLEEP_SECONDS} segundo(s)")
    print(f"Banco SQLite: {DB_PATH}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bot de alerta de precos de passagens no Telegram.")
    parser.add_argument("--once", action="store_true", help="Executa uma rodada e encerra.")
    parser.add_argument("--dry-run", action="store_true", help="Consulta precos, mas nao envia mensagens no Telegram.")
    parser.add_argument("--test-telegram", action="store_true", help="Envia uma mensagem de teste e encerra.")
    parser.add_argument("--show-config", action="store_true", help="Mostra a configuracao e encerra.")
    parser.add_argument("--init-db", action="store_true", help="Cria o banco SQLite e encerra.")
    parser.add_argument("--max-checks", type=int, default=MAX_CHECKS_PER_RUN, help="Limita consultas nesta execucao.")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.show_config:
        show_config()
        return

    init_db()

    if args.init_db:
        print(f"Banco pronto: {DB_PATH}")
        return

    if args.test_telegram:
        send_telegram("Teste do bot de passagens: Telegram configurado corretamente.")
        print("Mensagem de teste enviada.")
        return

    require_env(need_telegram=not args.dry_run, need_serpapi=True)

    if args.once:
        print("Iniciando checagem unica...")
        alerts_found = run_once(dry_run=args.dry_run, max_checks=args.max_checks)
        print(f"Checagem finalizada. Alertas encontrados: {alerts_found}")
        return

    if SEND_STARTUP_MESSAGE:
        send_telegram("Bot de passagens iniciado.")

    while True:
        print("Iniciando checagem...")
        alerts_found = run_once(dry_run=args.dry_run, max_checks=args.max_checks)
        print(f"Checagem finalizada. Alertas encontrados: {alerts_found}")
        print(f"Aguardando {CHECK_EVERY_MINUTES} minutos.")
        time.sleep(CHECK_EVERY_MINUTES * 60)


if __name__ == "__main__":
    main()
