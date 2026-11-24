"""Modelo de goles Dixon-Coles con ponderación temporal.

Cada equipo tiene una fuerza de ataque y otra de defensa. Los goles esperados son

    λ_local     = exp(μ + ventaja_local + ataque_local + defensa_visitante)
    λ_visitante = exp(μ + ataque_visitante + defensa_local)

y el marcador se modela como dos Poisson con la corrección de Dixon-Coles
(parámetro ρ) para los resultados bajos (0-0, 1-0, 0-1, 1-1), que una Poisson
simple predice mal. Los partidos recientes pesan más (decaimiento exponencial
con constante `xi` por día) y una regularización L2 suave encoge hacia la media
a los equipos con pocos partidos.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOLES = 10


@dataclass
class Prediccion:
    lambda_local: float
    lambda_visitante: float
    matriz: np.ndarray  # matriz[i, j] = P(local marca i, visitante marca j)

    def prob(self) -> dict[str, float]:
        m = self.matriz
        total = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
        return {
            "1": float(np.tril(m, -1).sum()),
            "X": float(np.trace(m)),
            "2": float(np.triu(m, 1).sum()),
            "Over2.5": float(m[total > 2.5].sum()),
            "Under2.5": float(m[total < 2.5].sum()),
            "BTTS_Si": float(m[1:, 1:].sum()),
            "BTTS_No": float(1 - m[1:, 1:].sum()),
        }


def _tau(x, y, lh, la, rho):
    """Factor de corrección Dixon-Coles para marcadores bajos."""
    t = np.ones_like(lh, dtype=float)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


class ModeloDixonColes:
    def __init__(self, xi: float = 0.0019, reg: float = 0.5,
                 peso_tiros: float = 0.0, peso_xg: float = 0.0):
        """
        xi:  decaimiento temporal por día (0.0019 ≈ un partido de hace un año pesa la mitad).
        reg: fuerza de la regularización L2 sobre ataque/defensa.
        peso_tiros: parte del "rendimiento ofensivo" que se mide con tiros a puerta
                    (convertidos a goles con la tasa de conversión de la liga) en vez
                    de con goles reales. Los tiros son mucho menos aleatorios que los goles.
        peso_xg:    ídem con goles esperados (xG) cuando el fichero los trae; si un
                    partido no tiene xG, ese peso pasa a los tiros a puerta.
        """
        self.xi = xi
        self.reg = reg
        self.peso_tiros = peso_tiros
        self.peso_xg = peso_xg
        self.equipos: list[str] = []
        self.indice: dict[str, int] = {}
        self.mu = 0.0
        self.ventaja_local = 0.0
        self.ataque = np.array([])
        self.defensa = np.array([])
        self.rho = 0.0
        self.partidos_por_equipo: dict[str, float] = {}

    # ------------------------------------------------------------------ ajuste
    def ajustar(self, partidos: pd.DataFrame, fecha_ref: pd.Timestamp | None = None) -> "ModeloDixonColes":
        """Ajusta con partidos que tengan HomeTeam, AwayTeam, FTHG, FTAG, Date."""
        if fecha_ref is None:
            fecha_ref = partidos["Date"].max()
        df = partidos[partidos["Date"] <= fecha_ref]
        self.equipos = sorted(set(df["HomeTeam"]) | set(df["AwayTeam"]))
        self.indice = {e: i for i, e in enumerate(self.equipos)}
        n = len(self.equipos)

        h = df["HomeTeam"].map(self.indice).to_numpy()
        a = df["AwayTeam"].map(self.indice).to_numpy()
        goles_h = df["FTHG"].to_numpy(dtype=float)
        goles_a = df["FTAG"].to_numpy(dtype=float)
        gh, ga = self._objetivo(df, goles_h, goles_a)
        dias = (fecha_ref - df["Date"]).dt.days.to_numpy(dtype=float)
        w = np.exp(-self.xi * dias)
        self.partidos_por_equipo = (
            pd.Series(np.concatenate([w, w]), index=np.concatenate([df["HomeTeam"], df["AwayTeam"]]))
            .groupby(level=0).sum().to_dict()
        )

        reg = self.reg

        def nll(p):
            mu, home = p[0], p[1]
            att, dfn = p[2:2 + n], p[2 + n:]
            llh = mu + home + att[h] + dfn[a]
            lla = mu + att[a] + dfn[h]
            lh, la = np.exp(llh), np.exp(lla)
            # log-verosimilitud Poisson (sin el término constante log(k!))
            ll = w * (gh * llh - lh + ga * lla - la)
            f = -ll.sum() + reg * (att @ att + dfn @ dfn)
            rh = w * (gh - lh)  # d ll / d llh
            ra = w * (ga - la)
            g = np.empty_like(p)
            g[0] = -(rh.sum() + ra.sum())
            g[1] = -rh.sum()
            g_att = np.bincount(h, rh, n) + np.bincount(a, ra, n)
            g_def = np.bincount(a, rh, n) + np.bincount(h, ra, n)
            g[2:2 + n] = -g_att + 2 * reg * att
            g[2 + n:] = -g_def + 2 * reg * dfn
            return f, g

        p0 = np.zeros(2 + 2 * n)
        p0[0] = np.log(max(np.average(np.r_[gh, ga], weights=np.r_[w, w]), 0.1))
        res = minimize(nll, p0, jac=True, method="L-BFGS-B")
        p = res.x
        self.mu, self.ventaja_local = float(p[0]), float(p[1])
        self.ataque, self.defensa = p[2:2 + n], p[2 + n:]

        # ρ en un segundo paso, con las λ ya fijadas
        lh = np.exp(self.mu + self.ventaja_local + self.ataque[h] + self.defensa[a])
        la = np.exp(self.mu + self.ataque[a] + self.defensa[h])

        def nll_rho(rho):
            t = _tau(goles_h, goles_a, lh, la, rho)
            if np.any(t <= 0):
                return np.inf
            return -(w * np.log(t)).sum()

        self.rho = float(minimize_scalar(nll_rho, bounds=(-0.3, 0.3), method="bounded").x)
        return self

    def _objetivo(self, df: pd.DataFrame, goles_h: np.ndarray, goles_a: np.ndarray):
        """Mezcla de goles reales, goles "por tiros a puerta" y xG que se usa como dato a ajustar.

        La log-verosimilitud Poisson admite objetivos no enteros (cuasi-Poisson),
        así que el ajuste es el mismo; solo cambia qué se considera "lo que mereció marcar".
        """
        wt, wx = self.peso_tiros, self.peso_xg
        if wt + wx <= 0:
            return goles_h, goles_a

        def col(nombre):
            if nombre not in df.columns:
                return np.full(len(df), np.nan)
            return pd.to_numeric(df[nombre], errors="coerce").to_numpy(dtype=float)

        sot_h, sot_a = col("HST"), col("AST")
        xg_h, xg_a = col("HxG"), col("AxG")
        ok = np.isfinite(sot_h) & np.isfinite(sot_a)
        conversion = (goles_h[ok].sum() + goles_a[ok].sum()) / max(sot_h[ok].sum() + sot_a[ok].sum(), 1)

        def mezcla(goles, sot, xg):
            por_tiros = np.where(np.isfinite(sot), sot * conversion, goles)
            con_xg = np.where(np.isfinite(xg), xg, por_tiros)
            return (1 - wt - wx) * goles + wt * por_tiros + wx * con_xg

        return mezcla(goles_h, sot_h, xg_h), mezcla(goles_a, sot_a, xg_a)

    # ------------------------------------------------------------ predicción
    def conoce(self, equipo: str) -> bool:
        return equipo in self.indice

    def predecir(self, local: str, visitante: str) -> Prediccion:
        i, j = self.indice[local], self.indice[visitante]
        lh = float(np.exp(self.mu + self.ventaja_local + self.ataque[i] + self.defensa[j]))
        la = float(np.exp(self.mu + self.ataque[j] + self.defensa[i]))
        goles = np.arange(MAX_GOLES + 1)
        m = np.outer(poisson.pmf(goles, lh), poisson.pmf(goles, la))
        m[0, 0] *= 1 - lh * la * self.rho
        m[0, 1] *= 1 + lh * self.rho
        m[1, 0] *= 1 + la * self.rho
        m[1, 1] *= 1 - self.rho
        m /= m.sum()
        return Prediccion(lh, la, m)

    def tabla_fuerzas(self) -> pd.DataFrame:
        return (
            pd.DataFrame({
                "equipo": self.equipos,
                "ataque": np.exp(self.ataque),
                "defensa": np.exp(self.defensa),
            })
            .assign(neto=lambda d: d["ataque"] / d["defensa"])
            .sort_values("neto", ascending=False)
            .reset_index(drop=True)
        )
