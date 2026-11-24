"""Línea de comandos.

    python -m apuestas valor   --ligas SP1 E0         # apuestas de valor en próximos partidos
    python -m apuestas backtest --liga SP1             # cómo habría ido en temporadas pasadas
    python -m apuestas fuerzas --liga SP1              # ranking ataque/defensa del modelo
"""

from __future__ import annotations

import argparse

import pandas as pd

from apuestas import backtest, datos
from apuestas.modelo import ModeloDixonColes
from apuestas.valor import Config, buscar_valor

PESO_TIROS = 0.5  # elegido con el backtest: mejora Más/Menos 2,5 en todas las ligas probadas
PESO_XG = 0.0

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def _config(a) -> Config:
    return Config(
        umbral_ev=a.ev,
        peso_modelo=a.peso_modelo,
        cuota_min=a.cuota_min,
        cuota_max=a.cuota_max,
        mercados=tuple(a.mercados),
    )


def _params_modelo(a) -> dict:
    return {"xi": a.xi, "peso_tiros": a.peso_tiros, "peso_xg": a.peso_xg}


def cmd_valor(a):
    cfg = _config(a)
    proximos = datos.cargar_proximos()
    ligas = a.ligas or sorted(set(proximos["Div"]) & set(datos.LIGAS))
    temporadas = datos.temporadas_anteriores(a.temporadas)
    resultados = []
    for liga in ligas:
        partidos = proximos[proximos["Div"] == liga]
        if partidos.empty:
            print(f"{liga}: sin próximos partidos con cuotas")
            continue
        print(f"{liga} ({datos.LIGAS.get(liga, '?')}): ajustando modelo con {temporadas}...")
        hist = datos.cargar_historico(liga, temporadas)
        modelo = ModeloDixonColes(**_params_modelo(a)).ajustar(hist)
        desconocidos = {e for e in pd.concat([partidos["HomeTeam"], partidos["AwayTeam"]]) if not modelo.conoce(e)}
        if desconocidos:
            print(f"  aviso: sin historial para {sorted(desconocidos)}")
        resultados.append(buscar_valor(modelo, partidos, cfg))
    res = pd.concat(resultados, ignore_index=True) if resultados else pd.DataFrame()
    if res.empty:
        print("\nNo hay apuestas que superen el umbral de valor.")
        return
    res = res.sort_values("EV", ascending=False)
    vista = res.assign(
        Fecha=res["Fecha"].dt.strftime("%d/%m"),
        Partido=res["Local"] + " - " + res["Visitante"],
        P_modelo=(res["P_modelo"] * 100).round(1),
        P_mercado=(res["P_mercado"] * 100).round(1),
        P_final=(res["P_final"] * 100).round(1),
        Cuota_justa=res["Cuota_justa"].round(2),
        EV=(res["EV"] * 100).round(1),
        Stake=(res["Kelly"] * 100).round(2),
    )[["Fecha", "Liga", "Partido", "Mercado", "Seleccion", "xG_local", "xG_visit",
       "P_modelo", "P_mercado", "P_final", "Cuota_justa", "Cuota_max", "Cuota_B365", "EV", "Stake"]]
    print("\nApuestas con valor (probabilidades y EV en %, Stake = % del bankroll, Kelly fraccional):\n")
    print(vista.to_string(index=False))
    if a.csv:
        res.to_csv(a.csv, index=False)
        print(f"\nGuardado en {a.csv}")


def cmd_backtest(a):
    cfg = _config(a)
    temporadas = datos.temporadas_anteriores(a.temporadas)
    test = a.test or temporadas[-3:]
    hist = datos.cargar_historico(a.liga, temporadas)
    print(f"Backtest {a.liga} | entreno desde {temporadas[0]} | test {test} | "
          f"EV≥{cfg.umbral_ev:.0%} peso_modelo={cfg.peso_modelo}")
    ev = backtest.ejecutar(hist, test, cfg, **_params_modelo(a))
    r = backtest.resumen(ev, cfg)
    for k, v in r.items():
        if k.startswith("logloss"):
            print(f"  {k}: " + ", ".join(f"{c}={x:.4f}" for c, x in v.items()))
    print(f"  apuestas: {r.get('n_apuestas', 0)}")
    if r.get("n_apuestas"):
        print(f"  ROI (cuota máx): {r['roi_cuota_max']:+.1%} ± {r['roi_error_std']:.1%}")
        print(f"  ROI (Bet365):    {r['roi_b365']:+.1%}  ({r['n_b365']} apuestas)")
        print(f"  acierto: {r['acierto']:.1%}  cuota media: {r['cuota_media']:.2f}")
        print(f"  CLV medio: {r['clv_medio']:+.1%}  ({r['clv_positivo_pct']:.0%} con CLV>0)")
        print(r["por_mercado"].to_string())
    if a.csv:
        ev.to_csv(a.csv, index=False)


def cmd_fuerzas(a):
    hist = datos.cargar_historico(a.liga, datos.temporadas_anteriores(a.temporadas))
    m = ModeloDixonColes(**_params_modelo(a)).ajustar(hist)
    actuales = set(hist[hist["Temporada"] == hist["Temporada"].max()]["HomeTeam"])
    t = m.tabla_fuerzas()
    print(f"μ={m.mu:.3f} ventaja_local={m.ventaja_local:.3f} rho={m.rho:.3f}")
    print(t[t["equipo"].isin(actuales)].round(3).to_string(index=False))


def main(argv=None):
    p = argparse.ArgumentParser(prog="apuestas", description="Buscador de apuestas de valor")
    sub = p.add_subparsers(dest="cmd", required=True)

    def comunes(sp):
        sp.add_argument("--ev", type=float, default=0.05, help="EV mínimo (0.05 = 5%%)")
        sp.add_argument("--peso-modelo", type=float, default=0.5,
                        help="1 = solo modelo, 0 = solo mercado (por defecto 0.5)")
        sp.add_argument("--cuota-min", type=float, default=1.3)
        sp.add_argument("--cuota-max", type=float, default=8.0)
        sp.add_argument("--mercados", nargs="+", default=["1X2", "Goles2.5"], choices=["1X2", "Goles2.5"])
        sp.add_argument("--temporadas", type=int, default=3, help="temporadas de historial")
        sp.add_argument("--xi", type=float, default=0.0019, help="decaimiento temporal por día")
        sp.add_argument("--peso-tiros", type=float, default=PESO_TIROS,
                        help="parte del ajuste basada en tiros a puerta en vez de goles")
        sp.add_argument("--peso-xg", type=float, default=PESO_XG,
                        help="parte del ajuste basada en xG (si el fichero lo trae)")
        sp.add_argument("--csv", help="guardar resultados en CSV")

    s = sub.add_parser("valor", help="apuestas de valor en próximos partidos")
    s.add_argument("--ligas", nargs="+", help=f"códigos de liga: {', '.join(datos.LIGAS)}")
    comunes(s)
    s.set_defaults(f=cmd_valor)

    s = sub.add_parser("backtest", help="simulación en temporadas pasadas")
    s.add_argument("--liga", default="SP1")
    s.add_argument("--test", nargs="+", help="temporadas de test, p. ej. 2425 2526")
    comunes(s)
    s.set_defaults(f=cmd_backtest)

    s = sub.add_parser("fuerzas", help="ranking de equipos según el modelo")
    s.add_argument("--liga", default="SP1")
    comunes(s)
    s.set_defaults(f=cmd_fuerzas)

    a = p.parse_args(argv)
    a.f(a)
