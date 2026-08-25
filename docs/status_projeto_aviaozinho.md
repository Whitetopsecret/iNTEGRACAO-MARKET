# Status Atualizado do Projeto Aviãozinho

## Data de registro

- 24 de agosto de 2026

## Estado atual do coletor

- O coletor principal encontra-se em fase de validação e integração, com foco em capturar dados de rodadas e preparar a pipeline para persistência.
- O fluxo atual está concentrado no módulo de coleta e no pipeline inicial do projeto, com a intenção de manter a operação funcional mesmo quando a fonte externa estiver instável.
- A implementação atual já demonstra a necessidade de um mecanismo de resiliência para evitar interrupções caso a API de estatísticas fique indisponível ou exija autenticação mais complexa.

## Teste realizado com a API de estatísticas

- Foi realizado um teste de conexão com o endpoint de estatísticas do jogo da Sorte na Bet, usando a URL descoberta no Network.
- O teste inicial com método GET retornou:
  - Status HTTP 405
  - Mensagem: "The GET method is not supported for route game/getMultiplierStatsLastMinutes. Supported methods: POST."
- Em seguida, foi tentada a chamada via POST, e a resposta retornou:
  - Status HTTP 400
  - Mensagem: "{"error":"INVALID SESSION ID"}"
- Esse resultado indica que o endpoint está acessível, mas depende de um fluxo de autenticação ou sessão válida, e não pode ser tratado como fonte confiável sem tratamento de erro robusto.

## Decisão registrada para a próxima implementação

- Antes de alterar o código principal, foi decidido registrar o estado atual e implementar um fallback resiliente com simulador.
- A ideia é manter o coletor operando mesmo quando a API real estiver indisponível, inválida ou rejeitando sessões, usando um simulador controlado para gerar dados de teste e preservar o fluxo de coleta.
- Esse fallback servirá como camada de segurança para desenvolvimento, validação e execução contínua do projeto enquanto a integração com a API real for ajustada.

## Próximo passo

- Implementar o fallback resiliente no coletor, com priorização do fluxo real quando a API responder corretamente e uso do simulador quando houver falha de conexão, método, sessão ou resposta inesperada.
