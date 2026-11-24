"""Comparación entre la probabilidad del modelo y la que implican las cuotas.

Una apuesta tiene valor cuando  prob_estimada × cuota > 1,  es decir, cuando la
casa paga más de lo que "debería" según las estadísticas.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from apuestas.modelo import ModeloDixonColes

# mercado -> (claves de selección, columnas de cuota máxima, media, Bet365, cierre Pinnacle, cierre media)
MERCADOS = {
    "1X2": {
        "selecciones": ["1", "X", "2"],
        "max": ["MaxH", "MaxD", "MaxA"],
        "media": ["AvgH", "AvgD", "AvgA"],
        "b365": ["B365H", "B365D", "B365A"],
        "cierre_ps": ["PSCH", "PSCD", "PSCA"],
        "cierre_media": ["AvgCH", "AvgCD", "AvgCA"],
    },
    "Goles2.5": {
        "selecciones": ["Over2.5", "Under2.5"],
        "max": ["Max>2.5", "Max<2.5"],
        "media": ["Avg>2.5", "Avg<2.5"],
        "b365": ["B365>2.5", "B365<2.5"],
        "cierre_ps": ["PC>2.5", "PC<2.5"],
        "cierre_media": ["AvgC>2.5", "AvgC<2.5"],
    },
}


@dataclass
class Config:
    umbral_ev: float = 0.05       # EV mínimo (5 %) para considerar una apuesta
    peso_modelo: float = 0.5      # mezcla modelo/mercado: 1 = solo modelo, 0 = solo mercado
    cuota_min: float = 1.3
    cuota_max: float = 8.0        # las cuotas muy altas tienen mucho ruido
    min_partidos_equipo: float = 8  # partidos (ponderados) mínimos para fiarse de un equipo
    fraccion_kelly: float = 0.25
    mercados: tuple[str, ...] = ("1X2", "Goles2.5")


def prob_sin_margen(cuotas: np.ndarray) -> np.ndarray:
    """Quita el margen de la casa normalizando las probabilidades implícitas."""
    imp = 1.0 / cuotas
    return imp / imp.sum()


def _cuotas(fila: pd.Series, cols: list[str]) -> np.ndarray | None:
    if not all(c in fila.index for c in cols):
        return None
    v = pd.to_numeric(fila[cols], errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(v)) or np.any(v <= 1.0):
        return None
    return v


def kelly(p: float, cuota: float) -> float:
    return max(0.0, (p * cuota - 1) / (cuota - 1))


def evaluar_partido(modelo: ModeloDixonColes, fila: pd.Series, cfg: Config) -> list[dict]:
    """Todas las selecciones de un partido con su probabilidad y EV (tengan valor o no)."""
    local, visit = fila["HomeTeam"], fila["AwayTeam"]
    if not (modelo.conoce(local) and modelo.conoce(visit)):
        return []
    if min(modelo.partidos_por_equipo.get(local, 0), modelo.partidos_por_equipo.get(visit, 0)) < cfg.min_partidos_equipo:
        return []
    pred = modelo.predecir(local, visit)
    probs = pred.prob()
    filas = []
    for mercado in cfg.mercados:
        spec = MERCADOS[mercado]
        mejores = _cuotas(fila, spec["max"])
        medias = _cuotas(fila, spec["media"])
        if mejores is None or medias is None:
            continue
        p_mercado = prob_sin_margen(medias)
        b365 = _cuotas(fila, spec["b365"])
        cierre = _cuotas(fila, spec["cierre_ps"])
        if cierre is None:
            cierre = _cuotas(fila, spec["cierre_media"])
        p_cierre = prob_sin_margen(cierre) if cierre is not None else None
        for k, sel in enumerate(spec["selecciones"]):
            p_mod = probs[sel]
            p = cfg.peso_modelo * p_mod + (1 - cfg.peso_modelo) * p_mercado[k]
            cuota = float(mejores[k])
            filas.append({
                "Fecha": fila["Date"],
                "Liga": fila.get("Div", ""),
                "Local": local,
                "Visitante": visit,
                "Mercado": mercado,
                "Seleccion": sel,
                "xG_local": round(pred.lambda_local, 2),
                "xG_visit": round(pred.lambda_visitante, 2),
                "P_modelo": p_mod,
                "P_mercado": float(p_mercado[k]),
                "P_final": p,
                "Cuota_justa": 1 / p,
                "Cuota_max": cuota,
                "Cuota_B365": float(b365[k]) if b365 is not None else np.nan,
                "EV": p * cuota - 1,
                "Kelly": cfg.fraccion_kelly * kelly(p, cuota),
                "P_cierre": float(p_cierre[k]) if p_cierre is not None else np.nan,
            })
    return filas


def buscar_valor(modelo: ModeloDixonColes, partidos: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    filas = [r for _, f in partidos.iterrows() for r in evaluar_partido(modelo, f, cfg)]
    todas = pd.DataFrame(filas)
    if todas.empty:
        return todas
    filtro = (
        (todas["EV"] >= cfg.umbral_ev)
        & (todas["Cuota_max"] >= cfg.cuota_min)
        & (todas["Cuota_max"] <= cfg.cuota_max)
    )
    return todas[filtro].sort_values("EV", ascending=False).reset_index(drop=True)
