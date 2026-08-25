import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def build_url(base_url: str) -> str:
    if not base_url:
        raise ValueError("Informe a base da API via argumento ou variável BET_BASE_URL")

    base_url = base_url.strip()
    if base_url.endswith("/getMultiplierStatsLastMinutes"):
        return base_url

    return base_url.rstrip("/") + "/getMultiplierStatsLastMinutes"


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("BET_BASE_URL")

    try:
        url = build_url(base_url)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    payload = b"{}"

    print(f"Requisitando: {url}")

    try:
        request = Request(url, headers=headers, method="POST", data=payload)
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"Status HTTP: {response.status}")
            print("Resposta:")
            print(body)

            try:
                payload = json.loads(body)
                print("\nJSON parseado:")
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print("\nA resposta não está em JSON válido.")

    except HTTPError as exc:
        print(f"Erro HTTP {exc.code}")
        print(exc.read().decode("utf-8", errors="replace"))
    except URLError as exc:
        print(f"Erro de conexão: {exc}")
    except Exception as exc:
        print(f"Erro inesperado: {exc}")


if __name__ == "__main__":
    main()
