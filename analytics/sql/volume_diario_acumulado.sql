-- Volume diário e acumulado de massa crítica
WITH diario AS (
    SELECT
        (round_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/Manaus')::date AS data_local,
        COUNT(*) AS volume_diario
    FROM public.game_rounds
    WHERE round_timestamp IS NOT NULL
    GROUP BY 1
)
SELECT
    data_local::date AS data_local,
    volume_diario,
    SUM(volume_diario) OVER (ORDER BY data_local::date) AS acumulado_massa_critica
FROM diario
ORDER BY data_local::date;
