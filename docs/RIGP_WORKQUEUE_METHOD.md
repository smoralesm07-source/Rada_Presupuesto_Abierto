# RIGP · Bandeja de investigación

La bandeja convierte los hallazgos analíticos en una cola de trabajo humano simple y trazable. Su objetivo no es aumentar la cantidad de indicadores, sino reducir la fricción entre detectar un patrón y revisarlo.

## Principio de experiencia usuaria

La bandeja responde cuatro preguntas operativas:

1. ¿Qué revisión ya inicié y debo continuar?
2. ¿Qué hallazgo pendiente merece ser tomado primero?
3. ¿Qué casos requieren profundización?
4. ¿Qué casos ya tienen un resultado registrado?

La vista **Ahora** prioriza primero `PROFUNDIZAR`, luego `EN_REVISION` y finalmente hallazgos `PENDIENTE` con mayor nivel de atención y puntaje. De esta forma se evita abrir nuevos casos mientras existen revisiones activas sin conclusión.

## Estados

- `PENDIENTE`: no existe revisión humana registrada.
- `EN_REVISION`: el hallazgo fue tomado y la revisión está activa.
- `PROFUNDIZAR`: la primera revisión no fue suficiente y quedan verificaciones concretas por resolver.
- `EXPLICADO`: la revisión encontró una explicación suficiente para el patrón observado.
- `ESCALADO`: existen hechos suficientes para derivar una revisión especializada. Este estado no significa que RIGP haya determinado una irregularidad o delito.

## Siguiente recomendado

RIGP muestra un solo siguiente recomendado. La selección sigue esta precedencia:

1. Hallazgos en `PROFUNDIZAR`.
2. Hallazgos `EN_REVISION`.
3. Hallazgos `PENDIENTE` de atención inmediata.
4. Hallazgos `PENDIENTE` de revisión prioritaria.

Dentro de cada grupo se ordena por nivel de atención, puntaje de prioridad y convergencia de familias de señal.

## Relación con el expediente

La bandeja no reemplaza el expediente de evidencia. Al tomar o continuar un hallazgo se abre directamente el expediente correspondiente, que concentra:

- lectura ejecutiva;
- cadena de evidencia;
- preguntas que deben quedar resueltas;
- ruta sugerida de revisión;
- validación humana y fundamento;
- retroalimentación sobre utilidad de señales.

## Alcance del piloto

En la versión estática actual, el estado de revisión se almacena en el navegador mediante `localStorage`. No existe todavía asignación multiusuario ni propiedad institucional del caso. Por esta razón la interfaz utiliza expresiones como **bandeja de investigación** o **trabajo local del piloto**, y no simula propietarios, responsables o SLA inexistentes.

La persistencia institucional deberá incorporar al menos `finding_id`, `status`, `assigned_to`, `taken_at`, `updated_at`, `outcome`, `note`, `evidence`, `useful_signals` y `low_value_signals`, con auditoría de cambios.

## Guardrail

La posición de un hallazgo en la bandeja indica prioridad de revisión. No acredita irregularidad, fraude, corrupción, delito funcionario, lavado de activos ni responsabilidad de una persona o entidad.