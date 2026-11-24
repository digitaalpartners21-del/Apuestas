# Apuestas de valor

Herramienta para encontrar **cuotas que pagan más de lo que deberían según las
estadísticas**. Se construye paso a paso; este es el paso 1.

## Cómo funciona

1. **Datos** — descarga de [football-data.co.uk](https://www.football-data.co.uk)
   los resultados de las últimas temporadas y las cuotas de varias casas
   (apertura y cierre), más los próximos partidos con sus cuotas actuales.
   Se guardan en `datos_cache/`.
2. **Modelo** — Dixon-Coles: cada equipo tiene una fuerza de ataque y otra de
   defensa, con ventaja de campo, corrección para marcadores bajos y más peso a
   los partidos recientes. Da la probabilidad de cada marcador y, de ahí,
   1X2 y Más/Menos de 2,5 goles.
3. **Valor** — se compara con las cuotas. La probabilidad final mezcla modelo
   y mercado (`--peso-modelo`, 0,5 por defecto) y una apuesta se marca si
   `probabilidad × cuota − 1 ≥ EV mínimo` (5 % por defecto). Se sugiere stake
   con Kelly fraccional (¼).
4. **Backtest** — semana a semana reentrena con lo anterior, "apuesta" con las
   cuotas de apertura y mide ROI y **CLV** (si la cuota cogida era mejor que la
   de cierre, la señal más fiable de que se ha encontrado una cuota mal puesta).

## Uso

```bash
pip install -r requirements.txt

python -m apuestas valor --ligas SP1 E0 E1        # próximos partidos con valor
python -m apuestas valor --ev 0.08 --csv hoy.csv  # todas las ligas, más exigente
python -m apuestas backtest --liga SP1 --temporadas 5
python -m apuestas fuerzas --liga SP1             # ranking ataque/defensa
pytest
```

Ligas: `SP1 SP2 E0 E1 E2 E3 EC I1 I2 D1 D2 F1 F2 N1 P1 B1 T1 G1 SC0 SC1`.

## Estado actual (paso 1): el modelo de goles solo NO bate al mercado

Backtest sobre 2024/25, 2025/26 y 2026/27 (hasta el 23/11/2026), EV ≥ 5 %,
peso del modelo 0,5, cuota máxima del mercado:

| Liga | Log-loss 1X2 modelo / mercado | Apuestas | ROI | CLV medio |
|------|------------------------------|---------:|----:|----------:|
| SP1  | 0,970 / 0,953 | 679 | −7,8 % ± 6,1 | −1,4 % |
| E0   | 1,005 / 0,994 | 745 | +3,3 % ± 6,2 | +0,4 % |
| E1   | 1,050 / 1,033 | 954 | −4,1 % ± 4,9 | −2,3 % |
| E2   | 1,038 / 1,019 | 801 | −6,7 % ± 5,1 | −1,5 % |
| I2   | 1,055 / 1,042 | 573 | −14,2 % ± 6,0 | −1,7 % |
| SP2  | 1,041 / 1,019 | 749 | −5,0 % ± 5,6 | −2,3 % |

El mercado predice mejor que un modelo basado solo en goles, y el CLV es
negativo: la mayoría de las "apuestas de valor" que marca hoy son ruido del
modelo, no errores de la casa. **No usar todavía para apostar dinero real.**

## Próximos pasos

- [ ] Usar estadísticas más predictivas que los goles: tiros a puerta (HST/AST)
      y xG, que ya vienen en los ficheros.
- [ ] Equipos que cambian de división (ascendidos/descendidos): cargar también
      la liga vecina para no infravalorarlos (p. ej. West Ham en la Championship).
- [ ] Calibrar `xi`, `reg`, `peso_modelo` y umbral con el backtest por liga.
- [ ] Filtrar solo apuestas donde el backtest dé CLV positivo (por liga/mercado).
- [ ] Más mercados (hándicap asiático, ambos marcan) y otras fuentes de cuotas.

> Las apuestas tienen expectativa negativa para la inmensa mayoría de la gente.
> Esto es una herramienta de análisis, no una garantía de beneficio.
