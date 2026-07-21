# Sanctum — en español

*Donde los agentes se invocan, se ligan y se ponen a trabajar.*

Sanctum es un motor de orquestación **mínimo y local-first** para
agentes IA: un **grafo de estados cíclico** ejecutado por supersteps
(modelo Pregel/BSP). Los nodos (Sigils) corren en paralelo sobre un
estado compartido (el Aether), devuelven deltas parciales que se funden
mediante reducers por canal (Conduits), y los edges condicionales
cierran los ciclos que hacen posible el comportamiento agéntico:
pensar → actuar → observar → pensar de nuevo.

El núcleo es pura librería estándar de Python — sin APIs propietarias,
sin dependencias obligatorias — y está diseñado para funcionar de forma
confiable con los modelos locales que sí corres (7–14B vía llama-server,
Ollama, vLLM, LM Studio o GGUF in-process).

## Lo esencial en cinco minutos

```sh
pip install sanctum-engine
```

```python
from sanctum import END, Ritual

ritual = Ritual()
ritual.add_sigil("cleanse", lambda aether: {"text": aether["text"].strip()})
ritual.add_sigil("transmute", lambda aether: {"text": aether["text"].upper()})
ritual.set_entry_point("cleanse")
ritual.add_edge("cleanse", "transmute")
ritual.add_edge("transmute", END)

rite = ritual.compile()
print(rite.invoke({"text": "  fiat lux  "}))
# {'text': 'FIAT LUX'}
```

Un agente completo (ciclo ReAct con herramientas) es una sola llamada:

```python
from sanctum import Tome, spell, summon

@spell
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())

entity = summon(oracle, Tome([word_count]), role="You are a scribe.")
```

## El glosario, en una tabla

| Término | Qué es técnicamente |
|---|---|
| **Ritual** → `compile()` → **Rite** | Builder del grafo → plan ejecutable validado |
| **Sigil** | Nodo: `(aether) -> delta parcial`, sync o async |
| **Aether** / **Conduit** | Estado compartido / canal con su reducer (`overwrite`, `append`, `add`, `merge_dict`) |
| **Seal** / **Codex** | Checkpoint por superstep / su almacén (memoria, SQLite, Postgres) |
| **Omen** | Evento tipado de streaming (`astream`) |
| **Oracle** / **Arcana** | Interfaz LLM / identificador del modelo |
| **Spell** / **Tome** | Herramienta con schema JSON / su registro |
| **Ward** | Middleware que observa o veta deltas |
| **circle()** | Un Rite compilado montado como un solo Sigil (subgrafos) |
| **scatter()** | Map-reduce dinámico dentro de un Sigil |
| **summon()** | El ciclo ReAct canónico sobre la API pública |

## Novedades de la 0.3.0

- **Joins wait-all** — `add_sigil(..., join="all")`: el Sigil espera a
  *todos* sus predecesores estáticos, incluso con ramas de largo
  desigual, sobreviviendo checkpoints.
- **Circles (subgrafos)** — `circle(rite, input_map=..., output_map=...)`:
  un agente invocado se vuelve un nodo de un pipeline mayor; sus eventos
  internos se ecoan al stream exterior como `CircleEchoed`.
- **Scatter (map-reduce)** — `scatter(fn, over=..., into=...)`: fan-out
  sobre una lista de tamaño dinámico con concurrencia acotada y
  resultados en orden de item.
- **Fix del transcript** — ambos adapters HTTP traducen el vocabulario
  de spells al formato de tools de cada servidor: los modelos locales
  por fin ven los resultados de sus herramientas y el tool-calling
  converge.

## ¿Y el resto de la documentación?

La referencia completa vive en inglés (la API, sus docstrings y las
guías se generan desde el código fuente): empieza por
[Getting started](../getting-started.md), sigue con los
[conceptos](../concepts/ritual.md) y consulta la
[referencia de API](../api.md). La
[comparación honesta con LangGraph / n8n / ADK](../comparison.md) y el
[documento de diseño](../architecture.md) completan el mapa.
