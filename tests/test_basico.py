from datetime import date

import numpy as np
import pandas as pd
import pytest

from apuestas import backtest, datos
from apuestas.modelo import ModeloDixonColes
from apuestas.valor import Config, buscar_valor, kelly, prob_sin_margen


def liga_sintetica(seed=0, jornadas=4):
    """Liga de 10 equipos con fuerzas conocidas: 'E0' es el mejor y 'E9' el peor."""
    rng = np.random.default_rng(seed)
    equipos = [f"E{i}" for i in range(10)]
    ataque = np.linspace(0.4, -0.4, 10)
    defensa = np.linspace(-0.4, 0.4, 10)
    filas, dia = [], pd.Timestamp("2024-08-01")
    for _ in range(jornadas):
        for i in range(10):
            for j in range(10):
                if i == j:
                    continue
                lh = np.exp(0.1 + 0.25 + ataque[i] + defensa[j])
                la = np.exp(0.1 + ataque[j] + defensa[i])
                filas.append({"Div": "XX", "Date": dia, "HomeTeam": equipos[i], "AwayTeam": equipos[j],
                              "FTHG": rng.poisson(lh), "FTAG": rng.poisson(la), "Temporada": "2425"})
                dia += pd.Timedelta(days=1)
    return pd.DataFrame(filas)


def test_modelo_recupera_orden_de_fuerzas():
    m = ModeloDixonColes(xi=0.0).ajustar(liga_sintetica())
    orden = m.tabla_fuerzas()["equipo"].tolist()
    assert orden[0] in {"E0", "E1"} and orden[-1] in {"E8", "E9"}
    assert 0.1 < m.ventaja_local < 0.4


def test_probabilidades_suman_uno():
    m = ModeloDixonColes().ajustar(liga_sintetica())
    p = m.predecir("E0", "E9").prob()
    assert p["1"] + p["X"] + p["2"] == pytest.approx(1)
    assert p["Over2.5"] + p["Under2.5"] == pytest.approx(1)
    assert p["1"] > p["2"]


def test_prob_sin_margen_y_kelly():
    p = prob_sin_margen(np.array([2.0, 3.4, 3.8]))
    assert p.sum() == pytest.approx(1)
    assert kelly(0.5, 2.0) == 0
    assert kelly(0.6, 2.0) == pytest.approx(0.2)


def test_buscar_valor_detecta_cuota_inflada():
    hist = liga_sintetica()
    m = ModeloDixonColes().ajustar(hist)
    p1 = m.predecir("E0", "E9").prob()["1"]
    justa = 1 / p1
    partido = pd.DataFrame([{
        "Div": "XX", "Date": pd.Timestamp("2025-01-01"), "HomeTeam": "E0", "AwayTeam": "E9",
        # el mercado (media) coincide con el modelo, pero una casa paga un 30 % más por el local
        "MaxH": justa * 1.3, "MaxD": 10.0, "MaxA": 30.0,
        "AvgH": justa, "AvgD": 1 / p1 * 5, "AvgA": 1 / p1 * 15,
    }])
    res = buscar_valor(m, partido, Config(peso_modelo=1.0, cuota_max=50, mercados=("1X2",)))
    assert "1" in res["Seleccion"].tolist()
    assert res.loc[res["Seleccion"] == "1", "EV"].iloc[0] == pytest.approx(0.3, abs=1e-6)


def test_backtest_sin_cuotas_no_apuesta():
    hist = liga_sintetica(jornadas=3)
    hist["Temporada"] = np.where(hist["Date"] < hist["Date"].quantile(0.7), "2324", "2425")
    ev = backtest.ejecutar(hist, ["2425"], Config())
    assert ev.empty  # no hay columnas de cuotas: nada que evaluar


def test_temporadas():
    assert datos.temporada_actual(date(2026, 11, 24)) == "2627"
    assert datos.temporada_actual(date(2027, 3, 1)) == "2627"
    assert datos.temporadas_anteriores(3, date(2026, 11, 24)) == ["2425", "2526", "2627"]
