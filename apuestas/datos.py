"""Descarga y lectura de datos de football-data.co.uk.

Cada fichero de temporada trae, por partido, el resultado, estadísticas
(tiros, córners...) y las cuotas de varias casas, tanto de apertura como de
cierre. `fixtures.csv` trae los próximos partidos con sus cuotas actuales.
"""

from __future__ import annotations

import io
import time
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

BASE_URL = "https://www.football-data.co.uk"
CACHE_DIR = Path(__file__).resolve().parent.parent / "datos_cache"

LIGAS = {
    "SP1": "España - LaLiga",
    "SP2": "España - Segunda",
    "E0": "Inglaterra - Premier League",
    "E1": "Inglaterra - Championship",
    "E2": "Inglaterra - League One",
    "E3": "Inglaterra - League Two",
    "EC": "Inglaterra - National League",
    "I1": "Italia - Serie A",
    "I2": "Italia - Serie B",
    "D1": "Alemania - Bundesliga",
    "D2": "Alemania - 2. Bundesliga",
    "F1": "Francia - Ligue 1",
    "F2": "Francia - Ligue 2",
    "N1": "Países Bajos - Eredivisie",
    "P1": "Portugal - Primeira Liga",
    "B1": "Bélgica - Pro League",
    "T1": "Turquía - Süper Lig",
    "G1": "Grecia - Super League",
    "SC0": "Escocia - Premiership",
    "SC1": "Escocia - Championship",
}

COLUMNAS_BASE = ["Div", "Date", "HomeTeam", "AwayTeam"]


def temporada_actual(hoy: date | None = None) -> str:
    """Código de temporada estilo football-data: '2627' para 2026/27."""
    hoy = hoy or date.today()
    inicio = hoy.year if hoy.month >= 7 else hoy.year - 1
    return f"{inicio % 100:02d}{(inicio + 1) % 100:02d}"


def temporadas_anteriores(n: int, hoy: date | None = None) -> list[str]:
    """Las `n` temporadas más recientes (la actual incluida), de más antigua a más nueva."""
    actual = temporada_actual(hoy)
    inicio = 2000 + int(actual[:2])
    return [f"{(a % 100):02d}{((a + 1) % 100):02d}" for a in range(inicio - n + 1, inicio + 1)]


def _descargar(ruta: str, max_edad_horas: float) -> bytes:
    CACHE_DIR.mkdir(exist_ok=True)
    local = CACHE_DIR / ruta.replace("/", "_")
    if local.exists() and (time.time() - local.stat().st_mtime) < max_edad_horas * 3600:
        return local.read_bytes()
    req = urllib.request.Request(f"{BASE_URL}/{ruta}", headers={"User-Agent": "apuestas-valor/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        contenido = resp.read()
    local.write_bytes(contenido)
    return contenido


def _leer_csv(contenido: bytes) -> pd.DataFrame:
    texto = contenido.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(texto), on_bad_lines="skip")
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df.dropna(subset=[c for c in COLUMNAS_BASE if c in df.columns])
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    return df.dropna(subset=["Date"])


def cargar_temporada(liga: str, temporada: str, max_edad_horas: float = 12) -> pd.DataFrame:
    """Partidos jugados de una liga y temporada (p. ej. 'SP1', '2526')."""
    df = _leer_csv(_descargar(f"mmz4281/{temporada}/{liga}.csv", max_edad_horas))
    df = df.dropna(subset=["FTHG", "FTAG"])
    df["FTHG"] = df["FTHG"].astype(int)
    df["FTAG"] = df["FTAG"].astype(int)
    df = df.copy()
    df["Temporada"] = temporada
    return df.sort_values("Date").reset_index(drop=True)


def cargar_historico(liga: str, temporadas: list[str], max_edad_horas: float = 12) -> pd.DataFrame:
    partes = []
    for t in temporadas:
        try:
            partes.append(cargar_temporada(liga, t, max_edad_horas))
        except Exception as e:  # temporada aún no publicada, liga sin datos, etc.
            print(f"  aviso: no se pudo cargar {liga} {t}: {e}")
    if not partes:
        raise RuntimeError(f"Sin datos para {liga}")
    return pd.concat(partes, ignore_index=True).sort_values("Date").reset_index(drop=True)


def cargar_proximos(max_edad_horas: float = 1) -> pd.DataFrame:
    """Próximos partidos (todas las ligas principales) con sus cuotas actuales."""
    return _leer_csv(_descargar("fixtures.csv", max_edad_horas)).reset_index(drop=True)
