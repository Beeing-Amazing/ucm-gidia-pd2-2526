"""
Rolly test set - 108 conversaciones independientes con datos reales.

Cada test es un mensaje nuevo al LLM sin contexto de conversaciones previas.

Estructura:
  id             : str
  category       : str
  description    : str
  message        : str        - mensaje único del conductor
  expected_tools : list[str]  - tools que deben llamarse (vacío = ninguna)
  no_tools       : bool       - True si NO debe llamar ninguna tool
  expected_data  : dict       - valores reales que Rolly debe reportar
      top_zone      : str     - zona que debe aparecer en la respuesta
      top_value     : float   - valor numérico que debe aparecer (±15%)
      value_label   : str     - qué representa el valor (para el evaluador)
      service       : str     - "yellow taxi" o "fhvhv" que debe mencionar
  tool_args      : dict       - args esperados en la llamada a la tool
  pass_criteria  : list[str]  - checks adicionales de comportamiento
"""

# ── Debes de tener estos paths ──────────────
# data/clean/taxi_zone_demand.parquet
# data/preds/TIPS-2025-04-01.json
# data/preds/DEMAND-forecast_taxi_2025-04-01.json
# data/preds/DEMAND-forecast_fhvhv_2025-04-01.json
# data/NYC511"/events_info_complete.csv

# ════════════════════════════════════════════════════════════════════
# CATÁLOGO DE CATEGORÍAS Y SUBCATEGORÍAS DE TESTS
# ════════════════════════════════════════════════════════════════════
#
# A. prediction_top_demand  →  get_top_predicted_demand_zones
#    A1. Routing correcto: yellow → is_fhvhv=False / fhvhv → is_fhvhv=True
#    A2. hours_from_now: "next hour"→1, "in 2 hours"→2, "in 3 hours"→3, "in 5 hours"→5
#    A3. top_n explícito (3, 5, 10)
#    A4. Sin servicio → no llama tool, pregunta al conductor
#    A5. Sin hora → usa hours_from_now=1 como default o pregunta
#    A6. Framing alternativo: "Uber"/"Lyft"/"rideshare" → fhvhv
#    A7. Dato real en respuesta: valor predicted_pickups ±15%
#    A8. Zona correcta en respuesta para cada hora
#
# B. prediction_zone_demand  →  get_predicted_demand_for_zone
#    B1. Zona encontrada por nombre parcial (JFK, LaGuardia, Penn Station…)
#    B2. max_hours: "next 3 hours" → max_hours=3 (sin restar 1)
#    B3. Sin max_hours → devuelve todas las horas
#    B4. Lista de horas como bullets (formato)
#    B5. Sin servicio → pregunta
#    B6. Zona inexistente → maneja error con gracia
#    B7. Valor correcto en next_hour=1 (primera predicción)
#    B8. is_fhvhv correcto según framing del conductor
#
# C. prediction_tips  →  get_tip_prediction
#    C1. Zona específica → usa get_tip_prediction (no get_top_tip_zones)
#    C2. expected_tip_usd correcto ±15%
#    C3. Muestra probabilidades por categoría ($0, $1-2, $2-3, $3-5, $5+)
#    C4. Búsqueda amplia: "airport" → devuelve JFK + LaGuardia
#    C5. Zona con tip bajo (Crown Heights) → informa sin ocultar
#    C6. Ambigüedad tip histórico vs predicho → prefiere predicción si zona concreta
#
# D. historical_demand  →  get_top_historic_demand_zones
#    D1. time_of_day: morning / afternoon / evening / night / any
#    D2. is_fhvhv: yellow=False, fhvhv=True, combinado=None
#    D3. Zona #1 real para cada combinación time_of_day × service
#    D4. top_n explícito
#    D5. Sin servicio → pregunta antes de llamar
#    D6. Framing "usually"/"historically" → histórico, no predicción
#    D7. Valor real (pickups_morning, trips_yellow, etc.) ±15%
#
# E. historical_tips  →  get_top_tip_zones  [+ get_top_historic_demand_zones]
#    E1. Yellow → West Village 12.88% / fhvhv → Windsor Terrace 5.51%
#    E2. Tip + franja horaria → doble tool (tip_zones + historic_demand)
#    E3. Cross-reference: zonas en ambos resultados destacadas
#    E4. Sin servicio → pregunta
#    E5. top_n explícito
#    E6. time_of_day correcto en llamada a historic_demand (morning/night/etc.)
#
# F. historical_zone_details  →  get_zone_details
#    F1. Búsqueda por nombre parcial (JFK, Upper East Side, airport…)
#    F2. is_fhvhv filtra columnas correctas
#    F3. Zona no encontrada → maneja error
#    F4. Respuesta incluye avg_fare, avg_tip, avg_trip_miles según servicio
#    F5. Encadenado desde get_top_tip_zones (H01)
#
# G. events  →  get_top_events_zones
#    G1. day="today" / "tomorrow" / lenguaje natural ("next Friday", "June 15th")
#    G2. top_n explícito (3 default, 5 solicitado)
#    G3. Muestra nombres de eventos cuando se pide
#    G4. Día sin eventos → respuesta de "no hay eventos"
#    G5. Fecha pasada vs futura → comportamiento coherente
#    G6. Pregunta en español → responde en español con datos de eventos
#
# H. multi_tool  →  encadenado de 2+ tools
#    H1. get_top_tip_zones + get_zone_details (top zone → detalles)
#    H2. get_top_tip_zones + get_top_historic_demand_zones (tips + franja)
#    H3. get_predicted_demand_for_zone + get_tip_prediction (zona: demanda y tip)
#    H4. get_top_predicted_demand_zones + get_top_events_zones (demanda + eventos)
#    H5. Orden correcto: todas las tools antes de dar respuesta final
#    H6. Cross-reference visible en respuesta (menciona zonas en común)
#
# I. missing_params  →  comportamiento de clarificación
#    I1. Sin is_fhvhv → siempre preguntar antes de llamar tool histórica
#    I2. Sin time_of_day en histórico → preguntar (o usar "any" como default)
#    I3. Sin hora en predicción top → preguntar o usar h=0
#    I4. Pregunta ambigua sin datos suficientes → solicita mínimo parámetros
#    I5. Conductor da info parcial → extrae lo posible, pregunta lo que falta
#
# J. off_topic  →  rechazo educado
#    J1. Temas no relacionados con taxis/NYC: tiempo, deportes, cocina, chistes…
#    J2. Navegación GPS / rutas (redirige a maps)
#    J3. Preguntas financieras/legales (bolsa, impuestos)
#    J4. Mecánica / mantenimiento del vehículo
#    J5. Política / opinión pública
#    J6. No llama ninguna tool, no alucina datos de taxi
#
# K. format  →  formato de salida
#    K1. Sin zone IDs (PULocationID) en respuesta
#    K2. Siempre incluye borough (Manhattan, Brooklyn, Queens…)
#    K3. Menciona si los datos son yellow taxi o fhvhv
#    K4. Respuesta breve para top zones (no párrafos largos)
#    K5. Lista de horas como bullets para zone demand
#    K6. Valor numérico exacto citado (no solo "the highest")
#
# L. language  →  responde en el idioma del conductor
#    L1. Español → respuesta en español
#    L2. Inglés → respuesta en inglés
#    L3. Mezcla de idiomas en pregunta → responde al idioma dominante
#    L4. Datos numéricos correctos independientemente del idioma
#
# M. edge_case  →  casos borde y robustez
#    M1. Zona inexistente → tool llamada, error manejado con gracia
#    M2. "Usually" / "historically" → histórico, NO predicción
#    M3. "Will/going to/in the next hour" → predicción, NO histórico (no time-of-day en predicciones)
#    M4. Zona específica en tips → get_tip_prediction vs get_top_tip_zones
#    M5. Fórmula hour: "next hour"→0, "2 hours"→1 (no confundir N con N-1)
#    M6. Fórmula max_hours: "4 hours"→max_hours=4 (sin restar 1)
#    M7. No responde de memoria: siempre llama tool antes de contestar
#    M8. Hour fuera de rango disponible → maneja error del forecast
#    M9. Conductor menciona "Uber" → is_fhvhv=True (no yellow)
#    M10. Conductor menciona "cab" / "yellow" → is_fhvhv=False
#
# ════════════════════════════════════════════════════════════════════

TESTS = [

    # ──────────────────────────────────────────────────────────────
    # A. PREDICCIÓN - TOP ZONAS DE DEMANDA
    # ──────────────────────────────────────────────────────────────

    {
        "id": "A01",
        "category": "prediction_top_demand",
        "description": "Top demanda yellow h=0 - zona correcta y valor",
        "message": "Where should I go right now for pickups? I drive yellow taxi.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 1},
        "pass_criteria": ["response mentions yellow taxi"],
    },
    {
        "id": "A02",
        "category": "prediction_top_demand",
        "description": "Top demanda fhvhv h=0 - zona correcta y valor",
        "message": "Best zones for fhvhv pickups next hour?",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 892.51,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "hours_from_now": 1},
        "pass_criteria": [],
    },
    {
        "id": "A03",
        "category": "prediction_top_demand",
        "description": "Top demanda yellow h=1 (2 horas) - formula hour=1",
        "message": "Top demand zones in 2 hours? Yellow taxi.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 341.42,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 2},
        "pass_criteria": ["hours_from_now=2 not hours_from_now=1"],
    },
    {
        "id": "A04",
        "category": "prediction_top_demand",
        "description": "Top demanda fhvhv h=2 (3 horas) - formula hour=2",
        "message": "Best predicted demand zones in 3 hours, I'm a rideshare driver.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 1028.93,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "hours_from_now": 3},
        "pass_criteria": ["hours_from_now=3 not hours_from_now=2"],
    },
    {
        "id": "A05",
        "category": "prediction_top_demand",
        "description": "Top demanda yellow h=4 (5 horas) - formula hour=4",
        "message": "Top zones in 5 hours for yellow taxi?",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 473.67,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 5},
        "pass_criteria": ["hours_from_now=5 not hours_from_now=4"],
    },
    {
        "id": "A06",
        "category": "prediction_top_demand",
        "description": "Top demanda fhvhv h=4 (5 horas) - formula correcta",
        "message": "Give me top 3 predicted demand zones in 5 hours, fhvhv.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 865.86,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "hours_from_now": 5, "top_n": 3},
        "pass_criteria": ["hours_from_now=5 not hours_from_now=4"],
    },
    {
        "id": "A07",
        "category": "prediction_top_demand",
        "description": "Sin servicio - debe preguntar antes de llamar tool",
        "message": "Where should I go for pickups right now?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "A08",
        "category": "prediction_top_demand",
        "description": "Sin hora ni servicio - debe preguntar",
        "message": "Show me predicted demand.",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "A09",
        "category": "prediction_top_demand",
        "description": "Top demanda yellow h=2 (3 horas)",
        "message": "Predicted hotspots for yellow taxi in 3 hours?",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 436.64,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 3},
        "pass_criteria": ["hours_from_now=3 not hours_from_now=2"],
    },
    {
        "id": "A10",
        "category": "prediction_top_demand",
        "description": "Framing Uber/rideshare → fhvhv, h=0",
        "message": "Where will there be most demand for Uber drivers right now?",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 892.51,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "hours_from_now": 1},
        "pass_criteria": [],
    },
    {
        "id": "A11",
        "category": "prediction_top_demand",
        "description": "Top demanda fhvhv h=1 (2 horas)",
        "message": "Where should I head in 2 hours? I'm a rideshare driver.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 933.45,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "hours_from_now": 2},
        "pass_criteria": ["hours_from_now=2 not hours_from_now=1"],
    },
    {
        "id": "A12",
        "category": "prediction_top_demand",
        "description": "top_n=10 explícito, fhvhv h=0",
        "message": "Give me top 10 zones for fhvhv next hour.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 892.51,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "top_n": 10, "hours_from_now": 1},
        "pass_criteria": [],
    },

    # ──────────────────────────────────────────────────────────────
    # B. PREDICCIÓN - DEMANDA ZONA ESPECÍFICA
    # ──────────────────────────────────────────────────────────────

    {
        "id": "B01",
        "category": "prediction_zone_demand",
        "description": "JFK todas las horas, yellow - valor h=0 correcto",
        "message": "What's the predicted demand for JFK Airport? Yellow taxi.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 222.62,
            "value_label": "predicted_pickups at next_hour=1",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "JFK", "is_fhvhv": False},
        "pass_criteria": ["lists every next_hour as bullet"],
    },
    {
        "id": "B02",
        "category": "prediction_zone_demand",
        "description": "JFK todas las horas, fhvhv - valor h=0 correcto",
        "message": "Predicted demand for JFK Airport, fhvhv?",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 418.71,
            "value_label": "predicted_pickups at next_hour=1",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "JFK", "is_fhvhv": True},
        "pass_criteria": ["lists every next_hour as bullet"],
    },
    {
        "id": "B03",
        "category": "prediction_zone_demand",
        "description": "LaGuardia próximas 3 horas, fhvhv - max_hours=3",
        "message": "How is LaGuardia Airport looking for fhvhv next 3 hours?",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 892.51,
            "value_label": "predicted_pickups next_hour=1",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "LaGuardia", "is_fhvhv": True, "max_hours": 3},
        "pass_criteria": ["max_hours=3"],
    },
    {
        "id": "B04",
        "category": "prediction_zone_demand",
        "description": "Upper East Side South 4 horas, yellow",
        "message": "How is Upper East Side South predicted for next 4 hours? Yellow taxi.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups next_hour=1",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "Upper East Side South", "is_fhvhv": False, "max_hours": 4},
        "pass_criteria": ["max_hours=4 not max_hours=3"],
    },
    {
        "id": "B05",
        "category": "prediction_zone_demand",
        "description": "Midtown Center 5 horas, yellow",
        "message": "Next 5 hours demand for Midtown Center, yellow taxi.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Midtown Center",
            "top_value": 284.42,
            "value_label": "predicted_pickups next_hour=1",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "Midtown Center", "is_fhvhv": False, "max_hours": 5},
        "pass_criteria": ["max_hours=5"],
    },
    {
        "id": "B06",
        "category": "prediction_zone_demand",
        "description": "East Village todas las horas, fhvhv",
        "message": "Demand prediction for East Village, fhvhv?",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "East Village",
            "top_value": 174.33,
            "value_label": "predicted_pickups next_hour=1",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "East Village", "is_fhvhv": True},
        "pass_criteria": ["lists all hours"],
    },
    {
        "id": "B07",
        "category": "prediction_zone_demand",
        "description": "Crown Heights North 2 horas, fhvhv",
        "message": "How busy will Crown Heights North be for rideshare next 2 hours?",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Crown Heights North",
            "top_value": 289.28,
            "value_label": "predicted_pickups next_hour=1",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "Crown Heights North", "is_fhvhv": True, "max_hours": 2},
        "pass_criteria": ["max_hours=2"],
    },
    {
        "id": "B08",
        "category": "prediction_zone_demand",
        "description": "Sin servicio → debe preguntar",
        "message": "What's the predicted demand for LaGuardia Airport?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "B09",
        "category": "prediction_zone_demand",
        "description": "Penn Station yellow h=0",
        "message": "Will Penn Station/Madison Sq West be busy? Yellow taxi.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Penn Station",
            "top_value": 211.91,
            "value_label": "predicted_pickups next_hour=1",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "Penn Station", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "B10",
        "category": "prediction_zone_demand",
        "description": "Upper East Side North 1 hora, yellow",
        "message": "Predicted demand for Upper East Side North next hour, yellow taxi.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side North",
            "top_value": 330.44,
            "value_label": "predicted_pickups next_hour=1",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "Upper East Side North", "is_fhvhv": False, "max_hours": 1},
        "pass_criteria": ["max_hours=1"],
    },
    {
        "id": "B11",
        "category": "prediction_zone_demand",
        "description": "LaGuardia yellow h=0",
        "message": "Show me demand forecast for LaGuardia Airport, yellow taxi.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 206.45,
            "value_label": "predicted_pickups next_hour=1",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "LaGuardia", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "B12",
        "category": "prediction_zone_demand",
        "description": "East New York fhvhv h=0",
        "message": "Is East New York going to be busy for fhvhv?",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "East New York",
            "top_value": 268.43,
            "value_label": "predicted_pickups next_hour=1",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "East New York", "is_fhvhv": True},
        "pass_criteria": [],
    },

    # ──────────────────────────────────────────────────────────────
    # C. PREDICCIÓN - TIP PREDICTION
    # ──────────────────────────────────────────────────────────────

    {
        "id": "C01",
        "category": "prediction_tips",
        "description": "Tip predicho JFK - valor real $4.20",
        "message": "What tip can I expect at JFK Airport?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 4.20,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "JFK"},
        "pass_criteria": ["includes expected_tip_usd", "includes probabilities"],
    },
    {
        "id": "C02",
        "category": "prediction_tips",
        "description": "Tip predicho LaGuardia - valor real $4.66",
        "message": "Tip breakdown for LaGuardia Airport?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 4.66,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "LaGuardia"},
        "pass_criteria": ["shows tip categories"],
    },
    {
        "id": "C03",
        "category": "prediction_tips",
        "description": "Tip predicho East Village - valor real $2.95",
        "message": "Expected tip in East Village?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "East Village",
            "top_value": 2.95,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "East Village"},
        "pass_criteria": [],
    },
    {
        "id": "C04",
        "category": "prediction_tips",
        "description": "Tip predicho Midtown Center - valor real $2.96",
        "message": "Predicted tip for Midtown Center?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Midtown Center",
            "top_value": 2.96,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "Midtown Center"},
        "pass_criteria": [],
    },
    {
        "id": "C05",
        "category": "prediction_tips",
        "description": "Tip predicho West Village - valor real $2.85",
        "message": "Tip prediction for West Village?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 2.85,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "West Village"},
        "pass_criteria": [],
    },
    {
        "id": "C06",
        "category": "prediction_tips",
        "description": "Crown Heights North - tip bajo $0.84",
        "message": "Will I get good tips in Crown Heights North?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Crown Heights North",
            "top_value": 0.84,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "Crown Heights"},
        "pass_criteria": ["calls get_tip_prediction not get_top_tip_zones"],
    },
    {
        "id": "C07",
        "category": "prediction_tips",
        "description": "Upper East Side North - $2.84",
        "message": "Predicted tips for Upper East Side North?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side North",
            "top_value": 2.84,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "Upper East Side North"},
        "pass_criteria": [],
    },
    {
        "id": "C08",
        "category": "prediction_tips",
        "description": "Búsqueda amplia 'airport' - devuelve varias zonas",
        "message": "How much tip do I get at airports?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 4.66,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "airport"},
        "pass_criteria": ["returns multiple zones"],
    },

    # ──────────────────────────────────────────────────────────────
    # D. HISTÓRICO - DEMANDA
    # ──────────────────────────────────────────────────────────────

    {
        "id": "D01",
        "category": "historical_demand",
        "description": "Top demanda mañana yellow - Upper East Side North #1",
        "message": "Historically where are most pickups in the morning for yellow taxi?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side North",
            "top_value": 2202.6,
            "value_label": "pickups_morning",
            "service": "yellow",
        },
        "tool_args": {"time_of_day": "morning", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "D02",
        "category": "historical_demand",
        "description": "Top demanda noche fhvhv - East Village #1",
        "message": "Best zones for fhvhv pickups historically at night?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "East Village",
            "top_value": 2093.2,
            "value_label": "pickups_night",
            "service": "fhvhv",
        },
        "tool_args": {"time_of_day": "night", "is_fhvhv": True},
        "pass_criteria": [],
    },
    {
        "id": "D03",
        "category": "historical_demand",
        "description": "Top demanda any yellow - Upper East Side South #1",
        "message": "Where have yellow taxis been picking up the most overall?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 9546942,
            "value_label": "trips_yellow",
            "service": "yellow",
        },
        "tool_args": {"time_of_day": "any", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "D04",
        "category": "historical_demand",
        "description": "Top demanda tarde fhvhv - LaGuardia #1",
        "message": "Top historic demand zones afternoon for rideshare?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 3687.7,
            "value_label": "pickups_afternoon",
            "service": "fhvhv",
        },
        "tool_args": {"time_of_day": "afternoon", "is_fhvhv": True},
        "pass_criteria": [],
    },
    {
        "id": "D05",
        "category": "historical_demand",
        "description": "Top demanda tarde yellow - LaGuardia #1",
        "message": "Where do yellow taxis pick up most in the afternoon?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 3687.7,
            "value_label": "pickups_afternoon",
            "service": "yellow",
        },
        "tool_args": {"time_of_day": "afternoon", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "D06",
        "category": "historical_demand",
        "description": "Top demanda noche yellow - East Village #1",
        "message": "Where do yellow taxis pick up most at night historically?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "East Village",
            "top_value": 2093.2,
            "value_label": "pickups_night",
            "service": "yellow",
        },
        "tool_args": {"time_of_day": "night", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "D07",
        "category": "historical_demand",
        "description": "top_n=3, mañana fhvhv",
        "message": "Top 3 zones with most pickups in the morning, fhvhv?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side North",
            "top_value": 2202.6,
            "value_label": "pickups_morning",
            "service": "fhvhv",
        },
        "tool_args": {"time_of_day": "morning", "is_fhvhv": True, "top_n": 3},
        "pass_criteria": [],
    },
    {
        "id": "D08",
        "category": "historical_demand",
        "description": "Top demanda any fhvhv - LaGuardia #1",
        "message": "Where do fhvhv drivers get the most pickups historically, overall?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 0,
            "value_label": "trips_fhvhv",
            "service": "fhvhv",
        },
        "tool_args": {"time_of_day": "any", "is_fhvhv": True},
        "pass_criteria": [],
    },
    {
        "id": "D09",
        "category": "historical_demand",
        "description": "Top demanda evening yellow - Midtown Center #1",
        "message": "Where do yellow taxis pick up most in the evening historically?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Midtown Center",
            "top_value": 3840.9,
            "value_label": "pickups_evening",
            "service": "yellow",
        },
        "tool_args": {"time_of_day": "evening", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "D10",
        "category": "historical_demand",
        "description": "Sin servicio → debe preguntar",
        "message": "Historically where's the most demand?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks for service type and/or time of day"],
    },

    # ──────────────────────────────────────────────────────────────
    # E. HISTÓRICO - TIPS
    # ──────────────────────────────────────────────────────────────

    {
        "id": "E01",
        "category": "historical_tips",
        "description": "Top tip yellow - West Village 12.88%",
        "message": "Best tip zones for yellow taxi historically?",
        "expected_tools": ["get_top_tip_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "E02",
        "category": "historical_tips",
        "description": "Top tip fhvhv - Windsor Terrace 5.51%",
        "message": "Where do fhvhv drivers get best tips historically?",
        "expected_tools": ["get_top_tip_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Windsor Terrace",
            "top_value": 5.51,
            "value_label": "avg_tip_pct_fhvhv",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True},
        "pass_criteria": [],
    },
    {
        "id": "E03",
        "category": "historical_tips",
        "description": "Tips mañana yellow → doble tool - West Village + Upper East Side North",
        "message": "Historically where do yellow taxis make the most tips in the morning?",
        "expected_tools": ["get_top_tip_zones", "get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["both tools called", "time_of_day='morning'"],
    },
    {
        "id": "E04",
        "category": "historical_tips",
        "description": "Tips noche fhvhv → doble tool",
        "message": "Best tips at night for rideshare drivers historically?",
        "expected_tools": ["get_top_tip_zones", "get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 5.12,
            "value_label": "avg_tip_pct_fhvhv",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True},
        "pass_criteria": ["both tools called", "time_of_day='night'"],
    },
    {
        "id": "E05",
        "category": "historical_tips",
        "description": "top_n=3, yellow",
        "message": "Top 3 tip zones for yellow taxi?",
        "expected_tools": ["get_top_tip_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "top_n": 3},
        "pass_criteria": [],
    },
    {
        "id": "E06",
        "category": "historical_tips",
        "description": "Tips tarde yellow → doble tool",
        "message": "Best tip areas in the evening for yellow taxi?",
        "expected_tools": ["get_top_tip_zones", "get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["both tools called", "time_of_day='evening'"],
    },
    {
        "id": "E07",
        "category": "historical_tips",
        "description": "Sin servicio → pregunta",
        "message": "Best tip zones overall?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "E08",
        "category": "historical_tips",
        "description": "Tips mañana fhvhv → doble tool - LaGuardia top en tips Y en demanda matinal",
        "message": "Tip zones for fhvhv in the morning?",
        "expected_tools": ["get_top_tip_zones", "get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 0,
            "value_label": "cross_reference_zone",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True},
        "pass_criteria": ["both tools called", "time_of_day='morning'"],
    },

    # ──────────────────────────────────────────────────────────────
    # F. HISTÓRICO - ZONE DETAILS
    # ──────────────────────────────────────────────────────────────

    {
        "id": "F01",
        "category": "historical_zone_details",
        "description": "Detalles JFK Airport",
        "message": "Tell me more about JFK Airport",
        "expected_tools": ["get_zone_details"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 0,
            "value_label": "",
            "service": "",
        },
        "tool_args": {"zone_name": "JFK"},
        "pass_criteria": [],
    },
    {
        "id": "F02",
        "category": "historical_zone_details",
        "description": "Detalles LaGuardia Airport",
        "message": "Zone details about LaGuardia Airport.",
        "expected_tools": ["get_zone_details"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 0,
            "value_label": "",
            "service": "",
        },
        "tool_args": {"zone_name": "LaGuardia"},
        "pass_criteria": [],
    },
    {
        "id": "F03",
        "category": "historical_zone_details",
        "description": "Detalles Upper East Side",
        "message": "Info on Upper East Side zones.",
        "expected_tools": ["get_zone_details"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side",
            "top_value": 0,
            "value_label": "",
            "service": "",
        },
        "tool_args": {"zone_name": "Upper East Side"},
        "pass_criteria": [],
    },
    {
        "id": "F04",
        "category": "historical_zone_details",
        "description": "Detalles East Village, yellow",
        "message": "Details for yellow taxi on East Village.",
        "expected_tools": ["get_zone_details"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "East Village",
            "top_value": 0,
            "value_label": "",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "East Village", "is_fhvhv": False},
        "pass_criteria": [],
    },
    {
        "id": "F05",
        "category": "historical_zone_details",
        "description": "Detalles aeropuertos, fhvhv",
        "message": "Give me zone details for airports for fhvhv.",
        "expected_tools": ["get_zone_details"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 0,
            "value_label": "",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "airport", "is_fhvhv": True},
        "pass_criteria": [],
    },
    {
        "id": "F06",
        "category": "historical_zone_details",
        "description": "Detalles Midtown Center",
        "message": "What do you have on Midtown Center?",
        "expected_tools": ["get_zone_details"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Midtown Center",
            "top_value": 0,
            "value_label": "",
            "service": "",
        },
        "tool_args": {"zone_name": "Midtown Center"},
        "pass_criteria": [],
    },

    # ──────────────────────────────────────────────────────────────
    # G. EVENTOS
    # ──────────────────────────────────────────────────────────────

    {
        "id": "G01",
        "category": "events",
        "description": "Eventos hoy",
        "message": "Any events today?",
        "expected_tools": ["get_top_events_zones"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {"day": "today"},
        "pass_criteria": [],
    },
    {
        "id": "G02",
        "category": "events",
        "description": "Eventos mañana",
        "message": "Events tomorrow?",
        "expected_tools": ["get_top_events_zones"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {"day": "tomorrow"},
        "pass_criteria": [],
    },
    {
        "id": "G03",
        "category": "events",
        "description": "Eventos el próximo viernes",
        "message": "Any major events next Friday?",
        "expected_tools": ["get_top_events_zones"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": [],
    },
    {
        "id": "G04",
        "category": "events",
        "description": "top_n=5 explícito",
        "message": "What zones are affected by events today? Give me 5.",
        "expected_tools": ["get_top_events_zones"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {"day": "today", "top_n": 5},
        "pass_criteria": [],
    },
    {
        "id": "G05",
        "category": "events",
        "description": "Eventos con nombres",
        "message": "What events are happening today? Tell me the names.",
        "expected_tools": ["get_top_events_zones"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {"day": "today"},
        "pass_criteria": ["response lists event names"],
    },
    {
        "id": "G06",
        "category": "events",
        "description": "Fecha específica",
        "message": "Events on June 15th?",
        "expected_tools": ["get_top_events_zones"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": [],
    },

    # ──────────────────────────────────────────────────────────────
    # H. MULTI-TOOL CHAINING
    # ──────────────────────────────────────────────────────────────

    {
        "id": "H01",
        "category": "multi_tool",
        "description": "Top tip zones yellow + detalles del primero",
        "message": "Best tip zones for yellow taxi and tell me about the top one.",
        "expected_tools": ["get_top_tip_zones", "get_zone_details"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["get_top_tip_zones called first"],
    },
    {
        "id": "H02",
        "category": "multi_tool",
        "description": "Tips mañana yellow - cross-reference correcto",
        "message": "Where do yellow taxis make the most tips in the morning?",
        "expected_tools": ["get_top_tip_zones", "get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["both tools called", "cross-reference mentioned in answer"],
    },
    {
        "id": "H03",
        "category": "multi_tool",
        "description": "Tips tarde fhvhv - cross-reference",
        "message": "Best tip areas in the afternoon for fhvhv?",
        "expected_tools": ["get_top_tip_zones", "get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 5.12,
            "value_label": "avg_tip_pct_fhvhv",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True},
        "pass_criteria": ["both tools called", "time_of_day='afternoon'"],
    },
    {
        "id": "H04",
        "category": "multi_tool",
        "description": "Tips noche yellow - cross-reference",
        "message": "Best tip zones at night for yellow taxi?",
        "expected_tools": ["get_top_tip_zones", "get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["both tools called", "time_of_day='night'"],
    },

    # ──────────────────────────────────────────────────────────────
    # I. PARÁMETROS FALTANTES / CLARIFICACIÓN
    # ──────────────────────────────────────────────────────────────

    {
        "id": "I01",
        "category": "missing_params",
        "description": "Demanda sin servicio",
        "message": "Where should I drive right now?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "I02",
        "category": "missing_params",
        "description": "Tips sin servicio",
        "message": "What are the tips like around NYC?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "I03",
        "category": "missing_params",
        "description": "Demanda histórica sin time_of_day ni servicio",
        "message": "Historical demand please.",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks time_of_day and/or service type"],
    },
    {
        "id": "I04",
        "category": "missing_params",
        "description": "Demanda predicha sin hora ni servicio",
        "message": "What's predicted for me?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "I05",
        "category": "missing_params",
        "description": "Top zones sin contexto",
        "message": "Best zones?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks for clarification"],
    },
    {
        "id": "I06",
        "category": "missing_params",
        "description": "Demanda en 3 horas sin servicio",
        "message": "Where to go in 3 hours?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "I07",
        "category": "missing_params",
        "description": "Zona específica sin servicio",
        "message": "Demand prediction for JFK Airport?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },
    {
        "id": "I08",
        "category": "missing_params",
        "description": "Demanda histórica sin servicio",
        "message": "Where are the busiest zones in the morning?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["asks yellow or fhvhv"],
    },

    # ──────────────────────────────────────────────────────────────
    # J. OFF-TOPIC - RECHAZO
    # ──────────────────────────────────────────────────────────────

    {
        "id": "J01",
        "category": "off_topic",
        "description": "Tiempo meteorológico",
        "message": "What's the weather like today in NYC?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "politely declines or redirects"],
    },
    {
        "id": "J02",
        "category": "off_topic",
        "description": "Deportes",
        "message": "Who won the Yankees game last night?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J03",
        "category": "off_topic",
        "description": "Escritura creativa",
        "message": "Write me a poem about driving.",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J04",
        "category": "off_topic",
        "description": "Restaurantes",
        "message": "What's the best restaurant near Times Square?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "politely declines or redirects"],
    },
    {
        "id": "J05",
        "category": "off_topic",
        "description": "Impuestos",
        "message": "Can you help me with my taxes?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J06",
        "category": "off_topic",
        "description": "Bolsa",
        "message": "What's the stock price of Uber today?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J07",
        "category": "off_topic",
        "description": "Mecánica",
        "message": "How do I fix my car engine?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J08",
        "category": "off_topic",
        "description": "Chiste",
        "message": "Tell me a joke.",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J09",
        "category": "off_topic",
        "description": "Noticias",
        "message": "What's happening in the news today?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J10",
        "category": "off_topic",
        "description": "Navegación GPS",
        "message": "How do I get to JFK from Manhattan?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "politely declines or redirects"],
    },
    {
        "id": "J11",
        "category": "off_topic",
        "description": "Política",
        "message": "What do you think about the mayor's new policy?",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },
    {
        "id": "J12",
        "category": "off_topic",
        "description": "Cocina",
        "message": "Give me a recipe for pasta.",
        "expected_tools": [],
        "no_tools": True,
        "expected_data": {},
        "tool_args": {},
        "pass_criteria": ["no tool called", "declines"],
    },

    # ──────────────────────────────────────────────────────────────
    # K. FORMATO Y PERSONA
    # ──────────────────────────────────────────────────────────────

    {
        "id": "K01",
        "category": "format",
        "description": "Sin zone IDs en respuesta",
        "message": "Best tip zones for yellow taxi?",
        "expected_tools": ["get_top_tip_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["no 'PULocationID' or raw numeric ID in response", "includes borough"],
    },
    {
        "id": "K02",
        "category": "format",
        "description": "Menciona yellow taxi en respuesta",
        "message": "Top predicted demand zones right now, yellow taxi.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 1},
        "pass_criteria": ["response mentions yellow taxi"],
    },
    {
        "id": "K03",
        "category": "format",
        "description": "Menciona fhvhv en respuesta",
        "message": "Top demand zones now, I'm fhvhv driver.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 892.51,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "hours_from_now": 1},
        "pass_criteria": ["response mentions FHV"],
    },
    {
        "id": "K04",
        "category": "format",
        "description": "Demanda zona: lista todas las horas como bullets",
        "message": "Show all demand for JFK Airport, fhvhv.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 418.71,
            "value_label": "predicted_pickups next_hour=1",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "JFK", "is_fhvhv": True},
        "pass_criteria": ["lists every next_hour as bullet"],
    },
    {
        "id": "K05",
        "category": "format",
        "description": "Respuesta breve para top zones",
        "message": "Top demand zones now? Yellow taxi.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 1},
        "pass_criteria": ["response is concise (not multiple long paragraphs)"],
    },
    {
        "id": "K06",
        "category": "format",
        "description": "Incluye borough en cada zona",
        "message": "Top 3 historic tip zones, yellow taxi.",
        "expected_tools": ["get_top_tip_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "West Village",
            "top_value": 12.88,
            "value_label": "avg_tip_pct_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "top_n": 3},
        "pass_criteria": ["includes borough", "no 'PULocationID' or raw numeric ID in response"],
    },

    # ──────────────────────────────────────────────────────────────
    # L. IDIOMA
    # ──────────────────────────────────────────────────────────────

    {
        "id": "L01",
        "category": "language",
        "description": "Pregunta en español → responde en español, datos correctos",
        "message": "¿Dónde hay más demanda ahora? Soy taxista amarillo.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 1},
        "pass_criteria": ["response is in Spanish"],
    },
    {
        "id": "L02",
        "category": "language",
        "description": "Tips fhvhv en español",
        "message": "¿Cuáles son las mejores zonas de propinas para conductores de fhvhv?",
        "expected_tools": ["get_top_tip_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Windsor Terrace",
            "top_value": 5.51,
            "value_label": "avg_tip_pct_fhvhv",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True},
        "pass_criteria": ["response is in Spanish"],
    },
    {
        "id": "L03",
        "category": "language",
        "description": "Eventos hoy en español",
        "message": "¿Hay eventos hoy en NYC?",
        "expected_tools": ["get_top_events_zones"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {"day": "today"},
        "pass_criteria": ["response is in Spanish"],
    },
    {
        "id": "L04",
        "category": "language",
        "description": "Demanda zona en español, fhvhv - valor correcto",
        "message": "¿Cuál es la demanda predicha para JFK Airport? Soy conductor de fhvhv.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "JFK Airport",
            "top_value": 418.71,
            "value_label": "predicted_pickups next_hour=1",
            "service": "fhvhv",
        },
        "tool_args": {"zone_name": "JFK", "is_fhvhv": True},
        "pass_criteria": ["response is in Spanish"],
    },
    {
        "id": "L05",
        "category": "language",
        "description": "Histórico mañana yellow en español",
        "message": "¿Dónde recogen más por la mañana los taxis amarillos históricamente?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side North",
            "top_value": 2202.6,
            "value_label": "pickups_morning",
            "service": "yellow",
        },
        "tool_args": {"time_of_day": "morning", "is_fhvhv": False},
        "pass_criteria": ["response is in Spanish"],
    },
    {
        "id": "L06",
        "category": "language",
        "description": "Tip predicho en español - valor correcto",
        "message": "¿Cuánta propina espero en LaGuardia Airport?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 4.66,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "LaGuardia"},
        "pass_criteria": ["response is in Spanish"],
    },

    # ──────────────────────────────────────────────────────────────
    # M. CASOS BORDE
    # ──────────────────────────────────────────────────────────────

    {
        "id": "M01",
        "category": "edge_case",
        "description": "Zona inexistente - tool se llama, maneja error",
        "message": "Predicted demand for Atlantis zone, yellow taxi?",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {},
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["gracefully handles empty/error result"],
    },
    {
        "id": "M02",
        "category": "edge_case",
        "description": "'Usually' → histórico, no predicción",
        "message": "Where do yellow taxis usually pick up the most?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 9546942,
            "value_label": "trips_yellow",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["calls get_top_historic_demand_zones not get_top_predicted_demand_zones"],
    },
    {
        "id": "M03",
        "category": "edge_case",
        "description": "'Will/going to' → predicción, no histórico",
        "message": "Where are yellow taxis going to pick up the most in the next hour? I drive yellow.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 1},
        "pass_criteria": ["calls get_top_predicted_demand_zones not get_top_historic_demand_zones"],
    },
    {
        "id": "M04",
        "category": "edge_case",
        "description": "Zona específica → tip_prediction no get_top_tip_zones",
        "message": "What's the tip situation at LaGuardia Airport?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 4.66,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "LaGuardia"},
        "pass_criteria": ["calls get_tip_prediction not get_top_tip_zones"],
    },
    {
        "id": "M05",
        "category": "edge_case",
        "description": "hour formula: 'next hour' → hour=0",
        "message": "Top zones next hour? Yellow taxi.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False, "hours_from_now": 1},
        "pass_criteria": ["hours_from_now=1 not hours_from_now=2"],
    },
    {
        "id": "M06",
        "category": "edge_case",
        "description": "hour formula: '2 hours' → hour=1",
        "message": "Top zones in 2 hours? Fhvhv.",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 933.45,
            "value_label": "predicted_pickups",
            "service": "fhvhv",
        },
        "tool_args": {"is_fhvhv": True, "hours_from_now": 2},
        "pass_criteria": ["hours_from_now=2 not hours_from_now=1"],
    },
    {
        "id": "M07",
        "category": "edge_case",
        "description": "max_hours no restar 1: '4 hours' → max_hours=4",
        "message": "Demand for Upper East Side South next 4 hours, yellow taxi.",
        "expected_tools": ["get_predicted_demand_for_zone"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups next_hour=1",
            "service": "yellow",
        },
        "tool_args": {"zone_name": "Upper East Side South", "is_fhvhv": False, "max_hours": 4},
        "pass_criteria": ["max_hours=4 not max_hours=3"],
    },
    {
        "id": "M08",
        "category": "edge_case",
        "description": "No responde de memoria - llama tool siempre",
        "message": "What's the busiest zone in Manhattan for yellow taxis right now?",
        "expected_tools": ["get_top_predicted_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Upper East Side South",
            "top_value": 367.47,
            "value_label": "predicted_pickups",
            "service": "yellow",
        },
        "tool_args": {"is_fhvhv": False},
        "pass_criteria": ["calls get_top_predicted_demand_zones not get_top_historic_demand_zones"],
    },
    {
        "id": "M09",
        "category": "edge_case",
        "description": "Tip fhvhv zona específica - LaGuardia top fhvhv tip",
        "message": "Expected tip for LaGuardia Airport for fhvhv?",
        "expected_tools": ["get_tip_prediction"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "LaGuardia Airport",
            "top_value": 4.66,
            "value_label": "expected_tip_usd",
            "service": "",
        },
        "tool_args": {"zone_name": "LaGuardia"},
        "pass_criteria": [],
    },
    {
        "id": "M10",
        "category": "edge_case",
        "description": "Evening fhvhv top - East Village aparece",
        "message": "Top historic demand zones in the evening for fhvhv?",
        "expected_tools": ["get_top_historic_demand_zones"],
        "no_tools": False,
        "expected_data": {
            "top_zone": "Midtown Center",
            "top_value": 3840.9,
            "value_label": "pickups_evening",
            "service": "fhvhv",
        },
        "tool_args": {"time_of_day": "evening", "is_fhvhv": True},
        "pass_criteria": [],
    },
]


if __name__ == "__main__":
    ids = [t["id"] for t in TESTS]
    assert len(ids) == len(set(ids)), "IDs duplicados"
    print(f"Total tests: {len(TESTS)}")
    from collections import Counter
    for cat, count in Counter(t["category"] for t in TESTS).items():
        print(f"  {cat}: {count}")
