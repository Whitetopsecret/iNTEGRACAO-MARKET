-- Média e tendência por hora (fuso de Manaus)
SELECT
    date_trunc('hour', (round_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/Manaus')) AS hora_local,
    COUNT(*) AS rodadas,
    ROUND(AVG(multiplier), 2) AS media_multiplicador,
    MAX(multiplier) AS maior_multiplicador
FROM public.game_rounds
WHERE round_timestamp IS NOT NULL
  AND multiplier IS NOT NULL
GROUP BY 1
ORDER BY 1;
