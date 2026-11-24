"""Backtest walk-forward: ¿habría ganado dinero el buscador en temporadas pasadas?

Semana a semana se reajusta el modelo SOLO con partidos anteriores, se buscan
apuestas de valor con las cuotas de apertura y se liquidan con el resultado
real. Además se mide el CLV (closing line value): si la cuota que cogimos era
mejor que la probabilidad "justa" del cierre. Un CLV positivo sostenido es la
mejor señal de que el modelo detecta cuotas mal puestas, mucho antes de que el
ROI sea estadísticamente fiable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apuestas.modelo import ModeloDixonColes
from apuestas.valor import Config, evaluar_partido


def _gana(sel: str, gh: int, ga: int) -> bool:
    return {
        "1": gh > ga,
        "X": gh == ga,
        "2": gh < ga,
        "Over2.5": gh + ga > 2.5,
        "Under2.5": gh + ga < 2.5,
        "BTTS_Si": gh > 0 and ga > 0,
        "BTTS_No": not (gh > 0 and ga > 0),
    }[sel]


def ejecutar(historico: pd.DataFrame, temporadas_test: list[str], cfg: Config,
             **params_modelo) -> pd.DataFrame:
    """Devuelve todas las selecciones evaluadas con su resultado (columna 'Gana')."""
    test = historico[historico["Temporada"].isin(temporadas_test)]
    if test.empty:
        return pd.DataFrame()
    semanas = test["Date"].dt.to_period("W-MON").unique()
    filas = []
    for semana in sorted(semanas):
        inicio = semana.start_time
        entreno = historico[historico["Date"] < inicio]
        if len(entreno) < 100:
            continue
        modelo = ModeloDixonColes(**params_modelo).ajustar(entreno, fecha_ref=inicio)
        partidos = test[test["Date"].dt.to_period("W-MON") == semana]
        for _, f in partidos.iterrows():
            for r in evaluar_partido(modelo, f, cfg):
                r["Gana"] = _gana(r["Seleccion"], int(f["FTHG"]), int(f["FTAG"]))
                filas.append(r)
    return pd.DataFrame(filas)


def resumen(evaluadas: pd.DataFrame, cfg: Config) -> dict:
    """Métricas de calibración del modelo y de rentabilidad de las apuestas de valor."""
    out: dict = {}
    if evaluadas.empty:
        return out
    # Calidad probabilística (log-loss: menor es mejor) modelo vs mercado
    for mercado, g in evaluadas.groupby("Mercado"):
        y = g["Gana"].to_numpy(dtype=float)
        eps = 1e-12
        n_partidos = g[["Fecha", "Local", "Visitante"]].drop_duplicates().shape[0]
        out[f"logloss_{mercado}"] = {
            col: float(-(y * np.log(np.clip(g[col], eps, 1))).sum() / n_partidos)
            for col in ["P_modelo", "P_mercado", "P_final"]
        }

    apuestas = evaluadas[
        (evaluadas["EV"] >= cfg.umbral_ev)
        & (evaluadas["Cuota_max"] >= cfg.cuota_min)
        & (evaluadas["Cuota_max"] <= cfg.cuota_max)
    ]
    out["n_apuestas"] = int(len(apuestas))
    if apuestas.empty:
        return out

    def roi(col):
        c = apuestas[col]
        ok = c.notna()
        ganancia = np.where(apuestas.loc[ok, "Gana"], c[ok] - 1, -1.0)
        return float(ganancia.mean()), int(ok.sum())

    out["roi_cuota_max"], _ = roi("Cuota_max")
    out["roi_b365"], out["n_b365"] = roi("Cuota_B365")
    out["acierto"] = float(apuestas["Gana"].mean())
    out["cuota_media"] = float(apuestas["Cuota_max"].mean())
    clv = apuestas["Cuota_max"] * apuestas["P_cierre"] - 1
    out["clv_medio"] = float(clv.mean())
    out["clv_positivo_pct"] = float((clv > 0).mean())
    # Error estándar aproximado del ROI con apuesta plana
    var = (apuestas["Gana"] * (apuestas["Cuota_max"] - 1) - (~apuestas["Gana"]) * 1.0).var()
    out["roi_error_std"] = float(np.sqrt(var / len(apuestas)))
    out["por_mercado"] = (
        apuestas.assign(g=np.where(apuestas["Gana"], apuestas["Cuota_max"] - 1, -1.0),
                        clv=clv)
        .groupby(["Mercado", "Seleccion"])
        .agg(n=("g", "size"), roi=("g", "mean"), clv=("clv", "mean"))
        .round(3)
    )
    return out
