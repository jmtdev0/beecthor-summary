# Análisis general del operador Polymarket — 19/04/2026

## Resumen ejecutivo

En general, el sistema va bien, pero todavía está en una fase frágil.

- Si tomo como referencia `account_state.json`, la equity actual es de aproximadamente `$13.02` frente a un bankroll inicial de `$7.84`. Eso equivale a `+$5.18` y aproximadamente `+66.1%`.
- Si tomo como referencia `trade_log.json`, hay `5` cierres ganadores registrados que suman `+$8.7264`.
- Esa cifra de `trade_log.json` es demasiado optimista si se mira sola, porque sigue abierta una semanal con `-$2.0332` no realizado y además falta al menos un cierre por expiry/resolution que no quedó registrado correctamente.

Conclusión corta: parece claro que sí hay edge, pero ahora mismo la calidad de la medición todavía es peor que la calidad de la lectura de mercado.

## Qué está funcionando

- La parte fuerte del sistema es la lectura direccional cuando Beecthor y Binance cuentan la misma historia.
- Las semanales funcionan especialmente bien cuando la dirección está clara pero el timing exacto del día no lo está. El mejor ejemplo reciente es la semanal de `78k`, cerrada con `+$4.9266`.
- Los diarios funcionan bien cuando dirección y timing están alineados al mismo tiempo. Los ejemplos recientes más limpios son el diario de `78k` (`+$1.4330`) y el diario de `76k dip` (`+$0.8062`).
- El sistema no está sobreoperando. De `109` ciclos registrados, `79` terminaron en `NO_ACTION`. Eso indica que el filtro existe y que no se está forzando entrada en cada revisión.
- La ejecución ha mejorado respecto a semanas anteriores. Los take profits recientes sí se están capturando y el bug duro de ejecución por `FOK` rígido ya no es el principal cuello de botella.

## Qué nos está perjudicando

- El fallo más caro no ha sido leer mal el mercado, sino perseguir la extensión siguiente cuando buena parte del movimiento ya había ocurrido.
- La semanal de `80k` es el mejor ejemplo reciente: no fue una locura teórica, pero sí una extensión demasiado exigente después de que el movimiento más limpio ya se hubiera dado.
- En diarios, el principal error es usar el vehículo correcto para la dirección equivocada en tiempo. Un daily puede perder incluso cuando el mercado luego hace lo previsto, simplemente porque lo hace un poco tarde.
- Hubo además un error de sistema: el validador duro de `nearest strike first` bloqueó una operación buena. Ese tipo de veto mecánico empeora una lectura correcta en lugar de protegerla.
- El tracking sigue siendo insuficiente. Si una posición desaparece por expiry y no deja un `trade_closed` claro, el post-mortem se degrada y el rendimiento aparente deja de ser fiable.

## Diagnóstico honesto

Mi lectura general es esta:

- La lógica de entrada no está rota.
- La lógica de elección del vehículo todavía necesita más disciplina.
- La contabilidad y reconciliación necesitan una mejora inmediata.

Dicho de otra manera: el sistema parece mejor leyendo que midiendo, y eso es peligroso porque puede hacer que se sobreestime una estrategia que aún no está lo bastante cerrada operativamente.

## Qué haría para evitar los fallos recientes

### 1. Elegir el vehículo antes que el strike

- Daily solo cuando el movimiento esperado tenga pinta de ocurrir dentro de la sesión actual, no simplemente “pronto”.
- Weekly cuando la dirección siga clara pero el timing exacto del día sea más difuso.
- Floor solo como jugada secundaria de soporte, no como sustituto automático de un price-hit claro.

### 2. Regla anti-chase explícita

- Si el primer objetivo importante ya se ha cumplido, no abrir automáticamente la siguiente extensión semanal.
- Para permitir esa segunda extensión, exigir dos cosas a la vez: continuación clara en Binance y una distancia restante todavía razonable.
- Si la nueva apuesta necesita “otra pierna más” después de un movimiento fuerte ya consumado, la carga de la prueba debe subir mucho.

### 3. Filtro de timing para diarios

- No abrir un daily si el mercado ya ha hecho gran parte del recorrido y todavía necesita una segunda aceleración para resolver.
- No abrir un daily si el razonamiento real es “seguramente ocurra mañana o durante la próxima pierna”, porque ese caso casi siempre pertenece a weekly, no a daily.
- Mantener `nearest strike first` como heurística de ranking, no como veto duro.

### 4. Reconciliación obligatoria después de cada sync

- Toda posición que salga de `open_positions` debe dejar un cierre explícito en `trade_log.json`.
- Los losers por expiry deben quedar tan bien registrados como los take profits.
- Antes de abrir una posición nueva, `account_state.json` y `trade_log.json` deben contar la misma historia.

### 5. No sacar conclusiones demasiado optimistas del mejor tramo reciente

- El tramo reciente ha sido muy bueno, pero incluye una ganadora semanal excepcional (`+$4.9266`) que no se puede asumir como evento normal de cada semana.
- Si el sistema empieza a proyectar el futuro como si ese tipo de trade fuera rutinario, el sizing y las expectativas se van a distorsionar.

## Pronóstico de ganancias para un mes de actividad

Esto no es un backtest riguroso ni una promesa. Es una proyección operativa razonable basada en:

- el historial actual registrado
- la equity actual (`~$13.02`)
- el hecho de que todavía existe cap temprano de `$1` por entrada mientras la equity no supere `$15`
- la observación de que el mayor riesgo ahora mismo no es la falta de edge, sino perseguir trades tardíos y medir mal los cierres

| Escenario | Qué tendría que pasar | PnL mensual estimado | Equity final aproximada |
|---|---|---:|---:|
| Adverso | Se repiten varios late entries, cae otra semanal exigente y el tracking sigue flojo | `-$3` a `$0` | `$10` a `$13` |
| Conservador | Se corrigen los errores más graves, pero sin capturar ninguna gran semanal asimétrica | `$0` a `+$2` | `$13` a `$15` |
| Central | Se mantiene la disciplina reciente, se elige mejor entre daily y weekly y se evita perseguir extensiones | `+$2` a `+$5` | `$15` a `$18` |
| Favorable | El mercado sigue muy legible, cae al menos una semanal muy limpia y varios diarios llegan con timing correcto | `+$6` a `+$10` | `$19` a `$23` |

## Cómo interpreto esos escenarios

- El escenario que me parece más razonable hoy no es el favorable, sino el central.
- Si el sistema sigue activo un mes y se corrigen los errores de persecución de strike y de reconciliación, la zona más creíble me parece `+$2` a `+$5`.
- El escenario favorable es posible, pero depende de que vuelva a aparecer al menos una operación muy asimétrica como la semanal de `78k`. No me parece serio tomarlo como expectativa base.
- El escenario adverso sigue siendo perfectamente posible mientras un solo weekly malo todavía pueda comerse varios aciertos pequeños.

## Mi conclusión final

La impresión general es positiva.

No parece que el problema principal sea “no sabemos leer a Beecthor” o “no hay edge”. El problema real es más concreto:

- a veces se elige tarde el trade
- a veces se usa un daily donde tocaba un weekly
- y todavía no se está midiendo todo con la limpieza suficiente

Si esas tres cosas mejoran, el operador tiene pinta de poder seguir creciendo. Si no mejoran, el sistema puede seguir acertando direcciones y aun así dejar bastante dinero por el camino.

Si tuviera que resumirlo en una frase:

> Vamos mejor de lo que parece en lectura de mercado, pero peor de lo que debería en disciplina de entrada y en contabilidad; justo ahí está ahora la mayor mejora disponible.